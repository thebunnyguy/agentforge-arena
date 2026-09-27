"""Campaign completeness validator and receipt.

Answers one question from campaign-OWNED evidence only: is the planned matrix
(every cell x every repetition position, per the frozen manifest) present,
exactly once, as valid fresh real-backend evidence at the frozen task versions
and digests? It never counts "rows for this model and task that happen to be in
the database": only evaluations referenced by active ledger entries.

The receipt is a machine-readable proof (expected / present / missing / extra,
per model, per cell) and the exit status is 0 only when the scope is complete
and every check passed.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import cohort, paths
from .ledger import SUCCEEDED, SUPERSEDED, Ledger, LedgerError, utc_now
from .manifest import Manifest, evidence_sha256, file_sha256, normalize_digest

RECEIPT_VERSION = 1


UNSETTLED_RESUMES = ("requested", "unknown")


def executed_resumes(entry: dict) -> list:
    """Resume records that (may) have run: all but the refused ones and those the
    app's own resume events proved were never executed."""
    return [r for r in entry.get("resumes") or []
            if not (isinstance(r, dict) and r.get("outcome") in ("refused", "not_sent", "not_executed"))]


def resume_problems(conn, entry: dict) -> list[str]:
    """The app must not have resumed the evaluation more often than the tooling
    did (a resume outside the tooling had no code, identity or busy check and no
    warm-up), and every tooling resume's outcome must be settled."""
    records = executed_resumes(entry)
    problems = []
    if any(isinstance(r, dict) and r.get("outcome") in UNSETTLED_RESUMES for r in records):
        problems.append("a resume's outcome was never settled (a launch settles it from the app's resume events "
                        "while the evaluation is in flight; an entry already accepted by older tooling must be "
                        "superseded)")
    if cohort.resume_event_count(conn, entry.get("evaluation_id")) > len(records):
        problems.append("the app resumed this evaluation more often than the campaign tooling did: it was "
                        "resumed outside the tooling (no code, identity or busy check, no warm-up)")
    return problems


def rehearsal_problems(manifest: Manifest, entry: dict) -> list[str]:
    """Flags recorded when the evaluation was STARTED (submission, resumes) that
    make it non-official whatever happens later."""
    problems = []
    records = [r for r in executed_resumes(entry) if isinstance(r, dict)]
    if entry.get("code_check_at_submit") is not True or any(r.get("check_code") is not True for r in records):
        problems.append("submitted or resumed without a passing runtime-code check (--no-code-check or an older "
                        "launcher): not official evidence")
    if manifest.backend["kind"] == "ollama" and (
            entry.get("warmed_up_at_submit") is not True or any(r.get("warmed_up") is not True for r in records)):
        problems.append("the model was not loaded before every start of this evaluation (--no-warmup): a cold load "
                        "may have been charged to a trial's time budget; not official evidence")
    return problems


def assess_cell(conn, manifest: Manifest, cell, entry: dict | None, reference: dict[str, str],
                reference_version: str | None = None) -> dict:
    """THE acceptance predicate for one cell, shared by the validator, the
    monitor and the analysis: an active 'succeeded' entry whose evaluation
    passes every cohort check, with every position VALID (no voids), that ran
    alone on the app, that was submitted, resumed and finalized under a passing
    runtime-code check, and - on Ollama - whose model identity (digest at
    submission and at acceptance) and server version equal the campaign's
    first-launch reference, with no identity violation observed while it ran
    and the model loaded before every (re)start."""
    out = {"accepted": False, "check": None, "problems": [], "warnings": [], "model_digest": None}
    if entry is None or entry.get("state") != SUCCEEDED or conn is None:
        return out
    check = cohort.check_cell_evaluation(conn, manifest, cell, entry.get("evaluation_id"))
    out["check"] = check
    out["problems"] += check.problems
    out["warnings"] += check.warnings
    problems = out["problems"]
    if check.voided:
        # A campaign cell needs every position VALID; voids are never counted
        # against the model, so the cell is re-evaluated fresh (supersede),
        # never accepted short.
        problems.append(
            f"{check.voided} infrastructure-voided position(s): only {check.valid}/"
            f"{manifest.repetitions} valid - supersede the cell for a fresh re-evaluation")
    if entry.get("concurrency_violation"):
        problems.append(f"another evaluation ran alongside it: {entry['concurrency_violation']}")
    overlapping = cohort.overlapping_evaluations(conn, entry.get("evaluation_id"))
    if overlapping:
        problems.append(f"trials of evaluation(s) {overlapping} ran at the same time as this evaluation's")
    problems += resume_problems(conn, entry)
    problems += rehearsal_problems(manifest, entry)
    if entry.get("code_check_at_finalize") is not True:
        problems.append("not accepted under a passing runtime-code check (--no-code-check or an older launcher): "
                        "not official evidence")
    if manifest.backend["kind"] == "ollama":
        ref = reference.get(cell.model)
        at_submit = entry.get("model_digest_at_submit")
        at_finalize = entry.get("model_digest_at_finalize")
        if manifest.is_sequential:  # pins are bare hex; compare normalized digests
            at_submit, at_finalize = normalize_digest(at_submit), normalize_digest(at_finalize)
        out["model_digest"] = at_finalize
        if not ref:
            problems.append("no first-launch model digest recorded for this model")
        elif at_finalize != ref or at_submit != ref:
            problems.append(
                f"model identity not proven: digests at submit/finalize {at_submit}/{at_finalize} "
                f"vs campaign reference {ref}")
        versions = (entry.get("ollama_version_at_submit"), entry.get("ollama_version_at_finalize"))
        if not reference_version:
            problems.append("no first-launch Ollama server version recorded")
        elif versions != (reference_version, reference_version):
            problems.append(f"Ollama server version at submit/finalize {versions[0]}/{versions[1]} vs campaign "
                            f"reference {reference_version}")
        if entry.get("identity_violation"):
            problems.append(f"model identity violation observed while it ran: {entry['identity_violation']}")
    out["accepted"] = check.ok and not problems
    return out


def _scope_expectations(manifest: Manifest, phase: str, excluded_phases: set[str] | None = None) -> dict:
    cells = [c for c in manifest.cells(phase) if c.phase not in (excluded_phases or set())]
    reps = manifest.repetitions
    models = sorted({c.model for c in cells}, key=manifest.models.index)
    tasks_per_model = {m: sum(1 for c in cells if c.model == m) for m in models}
    return {
        "scope": phase,
        "cells": len(cells),
        "runs": len(cells) * reps,
        "models": len(models),
        "runs_per_cell": reps,
        "tasks_per_model": tasks_per_model,
        "runs_per_model": {m: n * reps for m, n in tasks_per_model.items()},
    }


def validate_campaign(
    manifest: Manifest,
    *,
    phase: str = "all",
    check_task_files: bool = True,
) -> dict:
    from .launcher import check_task_pins, reference_digests, reference_ollama_version  # avoids an import cycle

    problems: list[str] = []
    warnings: list[str] = []
    ledger_path = manifest.ledger_path()
    try:
        ledger: Ledger | None = Ledger.load(
            ledger_path, campaign_id=manifest.campaign_id, manifest_sha256=manifest.sha256
        )
    except LedgerError as exc:
        ledger = None
        problems.append(f"ledger: {exc}")
    # A sequential-local campaign may end with fewer models than its roster: a
    # model explicitly CLASSIFIED (local resource limit, unsupported runtime, not
    # benchmarked) leaves the expected cohort - listed apart, never ranked and
    # never counted as a zero-score model.
    classified = dict((ledger.data.get("model_status") or {}) if (ledger and manifest.is_sequential) else {})
    if phase != "all" and phase in classified:
        problems.append(f"{manifest.phase_entry(phase)['model']} ({phase}) is classified "
                        f"{classified[phase]['status']}: it is not benchmarked")
    expected = _scope_expectations(manifest, phase, set(classified) if phase == "all" else None)

    reference = reference_digests(ledger, manifest) if (ledger or manifest.is_sequential) else {}
    reference_version = reference_ollama_version(ledger) if ledger else None
    identity_required = manifest.backend["kind"] == "ollama"
    db_path = manifest.db_path()
    conn = None
    if db_path.exists():
        conn = cohort.open_readonly(db_path)
    else:
        problems.append(f"campaign database {db_path} does not exist")

    cells_out: list[dict] = []
    classes: dict[str, int] = {}
    per_model: dict[str, dict] = {
        m: {"cells_expected": n, "cells_complete": 0, "runs": 0, "valid": 0, "passed": 0, "voided": 0}
        for m, n in expected["tasks_per_model"].items()
    }
    present_runs = 0
    valid_runs = 0
    complete_cells = 0
    voided_total = 0
    missing_cells: list[str] = []
    missing_positions = 0
    try:
        for cell in [c for c in manifest.cells(phase) if not (phase == "all" and c.phase in classified)]:
            entries = ledger.entries_for(cell.key) if ledger else []
            active = [e for e in entries if e["state"] != SUPERSEDED]
            row = {
                "cell": cell.key, "phase": cell.phase, "state": None, "evaluation_id": None,
                "ok": False, "runs": 0, "valid": 0, "passed": 0, "voided": 0,
                "problems": [], "warnings": [],
                "superseded_evaluations": [e.get("evaluation_id") for e in entries if e["state"] == SUPERSEDED],
            }
            if len(active) > 1:
                row["problems"].append(f"{len(active)} active ledger entries")
            entry = active[0] if active else None
            if entry is None:
                row["state"] = "not_started"
            else:
                row["state"] = entry["state"]
                row["evaluation_id"] = entry.get("evaluation_id")
            if entry is not None and entry["state"] == SUCCEEDED and conn is not None:
                verdict = assess_cell(conn, manifest, cell, entry, reference, reference_version)
                check = verdict["check"]
                row.update(ok=verdict["accepted"], runs=check.n_runs, valid=check.valid, passed=check.passed,
                           voided=check.voided, model_digest=verdict["model_digest"])
                row["problems"] += verdict["problems"]
                row["warnings"] += verdict["warnings"]
                for cls, n in check.classes.items():
                    classes[cls] = classes.get(cls, 0) + n
                # voided positions are disclosed for every succeeded cell (a cell
                # with voids is never accepted, so it is also listed as missing)
                per_model[cell.model]["voided"] += check.voided
                voided_total += check.voided
                if verdict["accepted"]:
                    # present counts ONLY accepted evidence (the shared predicate),
                    # exactly as status and the analysis count it
                    stats = per_model[cell.model]
                    stats["runs"] += check.n_runs
                    stats["valid"] += check.valid
                    stats["passed"] += check.passed
                    present_runs += check.n_runs
                    valid_runs += check.valid
                    complete_cells += 1
                    stats["cells_complete"] += 1
            if not row["ok"] or row["problems"]:
                missing_cells.append(cell.key)
                missing_positions += manifest.repetitions - (row["valid"] if row["ok"] else 0)
            problems += [f"{cell.key}: {p}" for p in row["problems"]]
            warnings += [f"{cell.key}: {w}" for w in row["warnings"]]
            cells_out.append(row)

        # disclosure only: accepted evidence of CLASSIFIED models (excluded from the cohort)
        classified_accepted: dict[str, dict] = {}
        if phase == "all" and classified and conn is not None and ledger is not None:
            for cell in manifest.cells():
                if cell.phase not in classified:
                    continue
                active = [e for e in ledger.entries_for(cell.key) if e["state"] != SUPERSEDED]
                if active and active[0]["state"] == SUCCEEDED:
                    verdict = assess_cell(conn, manifest, cell, active[0], reference, reference_version)
                    if verdict["accepted"]:
                        slot = classified_accepted.setdefault(cell.phase, {"cells": 0, "runs": 0})
                        slot["cells"] += 1
                        slot["runs"] += verdict["check"].n_runs
        untracked: list[dict] = []
        disowned = sorted(ledger.disowned_ids()) if ledger else []
        if conn is not None:
            known = (ledger.evaluation_ids(active_only=False) | ledger.disowned_ids()) if ledger else set()
            untracked = [
                e for e in cohort.evaluations_named(conn, manifest.data["evaluation_name_prefix"])
                if e["id"] not in known
            ]
            if untracked:
                problems.append(
                    f"{len(untracked)} evaluation(s) carry this campaign's name but are not owned by the "
                    "ledger (duplicates/orphans): " + ", ".join(e["id"] for e in untracked)
                )
        if ledger is not None:
            planned = {c.key for c in manifest.cells()}
            stray = [e["cell"] for e in ledger.active_entries() if e["cell"] not in planned]
            if stray:
                problems.append(f"ledger entries for cells outside the manifest: {stray}")
    finally:
        if conn is not None:
            conn.close()

    if ledger is not None:
        # The audit is tied to evidence: every accepted cell must itself have been
        # submitted, resumed and finalized under a passing code check (assess_cell).
        # A rehearsal launch that touched no accepted evidence is only disclosed.
        for launch in ledger.data.get("launches", []):
            if launch.get("check_code") is not True or launch.get("warmup") is False:
                warnings.append(
                    f"launch {launch.get('started_at')} ran with runtime-code check {launch.get('check_code')} "
                    f"and warm-up {launch.get('warmup')}; evidence it submitted, resumed or finalized is not "
                    "accepted")
    if check_task_files:
        drift = check_task_pins(manifest)
        problems += [f"TASK PACK CHANGED SINCE THE CAMPAIGN WAS FROZEN - {d}" for d in drift]
    hist = manifest.data["historical_evidence"]
    hist_path = paths.resolve(hist["path"])
    hist_sha = evidence_sha256(hist_path)
    if hist_sha != hist["sha256"]:
        problems.append(f"historical evidence DB sha256 is {hist_sha}, expected {hist['sha256']}")
    for cls in ("synthetic", "conflict", "legacy"):
        if classes.get(cls):
            problems.append(f"{classes[cls]} campaign run(s) classify as {cls!r}")
    if voided_total:
        warnings.append(f"{voided_total} infrastructure-voided position(s) in succeeded cells (never accepted: "
                        "supersede those cells)")

    models_complete = sum(
        1 for m, s in per_model.items() if s["cells_complete"] == s["cells_expected"]
    )
    complete = (not problems and complete_cells == expected["cells"] and present_runs == expected["runs"]
                and valid_runs == expected["runs"])
    cohort_info = (_cohort_summary(manifest, phase, per_model, classified, classified_accepted)
                   if manifest.is_sequential else None)
    return {
        "receipt_version": RECEIPT_VERSION,
        "campaign_id": manifest.campaign_id,
        "manifest_sha256": manifest.sha256,
        "scope": phase,
        "generated_at": utc_now(),
        "campaign_db": paths.display(db_path),
        "ledger": {
            "path": paths.display(ledger_path),
            "sha256": file_sha256(ledger_path) if ledger_path.exists() else None,
        },
        "historical_evidence_sha256": hist_sha,
        "expected": expected,
        "present": {
            "cells_complete": complete_cells,
            "runs": present_runs,
            "valid_runs": valid_runs,
            "models_complete": models_complete,
        },
        "model_identity": {"reference_digests": reference, "reference_ollama_version": reference_version,
                           "required": identity_required},
        "missing": {"cells": missing_cells, "positions": missing_positions},
        "extra": {
            "untracked_campaign_evaluations": [e["id"] for e in untracked],
            "disowned_evaluations": disowned,
            "campaign_owned_positions_beyond_plan": sum(
                1 for p in problems if "outside its trial positions" in p
            ),
        },
        "evidence_classes": classes,
        "voided_positions": voided_total,
        "per_model": per_model,
        **({"cohort": cohort_info} if cohort_info is not None else {}),
        "cells": cells_out,
        "problems": problems,
        "warnings": warnings,
        "complete": complete,
    }


def _cohort_summary(manifest: Manifest, phase: str, per_model: dict, classified: dict,
                    classified_accepted: dict | None = None) -> dict:
    """Per-model state of a sequential-local campaign: COMPLETE (every cell
    accepted), a classification (not benchmarked, never ranked), NOT_STARTED or
    INCOMPLETE (never ranked beside complete models)."""
    models = {}
    for entry in manifest.data["roster"]:
        if phase not in ("all", entry["phase"]):
            continue
        stats = per_model.get(entry["model"])
        record = classified.get(entry["phase"])
        if record:
            state = record["status"]
        elif stats and stats["cells_complete"] == stats["cells_expected"] and stats["cells_expected"]:
            state = "COMPLETE"
        elif stats and (stats["cells_complete"] or stats["runs"]):
            state = "INCOMPLETE"
        else:
            state = "NOT_STARTED"
        partial = (classified_accepted or {}).get(entry["phase"]) if record else None
        models[entry["phase"]] = {
            "model": entry["model"], "logical_name": entry["logical_name"], "optional": entry["optional"],
            "state": state,
            "accepted_cells": (partial or {}).get("cells", 0) if record else (stats or {}).get("cells_complete", 0),
            "accepted_runs": (partial or {}).get("runs", 0) if record else (stats or {}).get("runs", 0),
            "ranked": state == "COMPLETE",
            "classification": record,
        }
    complete = [m for m in models.values() if m["state"] == "COMPLETE"]
    required = [m for m in models.values() if not m["optional"]]
    floor = int((manifest.data.get("execution") or {}).get("minimum_ranked_models", 1))
    return {
        "models": models,
        "ranked_models": [m["model"] for m in complete],
        "accepted_runs_of_complete_models": sum(m["accepted_runs"] for m in complete),
        "required_models_complete": sum(1 for m in required if m["state"] == "COMPLETE"),
        "required_models": len(required),
        "minimum_runs": manifest.expected.get("minimum_runs"),
        "minimum_ranked_models": floor,
        "meets_minimum": len(complete) >= floor,
    }


def render(receipt: dict) -> str:
    exp, pres = receipt["expected"], receipt["present"]
    lines = [
        f"campaign {receipt['campaign_id']} - scope {receipt['scope']}",
        f"  expected: {exp['cells']} cells, {exp['runs']} runs ({exp['models']} models, "
        f"{exp['runs_per_cell']} per cell)",
        f"  present : {pres['cells_complete']} complete cells, {pres['runs']} runs "
        f"({pres['valid_runs']} valid), {pres['models_complete']} complete models",
        f"  missing : {len(receipt['missing']['cells'])} cells / {receipt['missing']['positions']} positions",
        f"  extra   : {len(receipt['extra']['untracked_campaign_evaluations'])} untracked campaign evaluations; "
        f"{len(receipt['extra']['disowned_evaluations'])} disowned (acknowledged, excluded)",
        f"  classes : {receipt['evidence_classes'] or '{}'}; voided positions: {receipt['voided_positions']}",
    ]
    for model, stats in receipt["per_model"].items():
        lines.append(
            f"    {model:22s} cells {stats['cells_complete']:3d}/{stats['cells_expected']:<3d} "
            f"runs {stats['runs']:4d}  passed {stats['passed']:4d}/{stats['valid']:<4d} voided {stats['voided']}"
        )
    cohort = receipt.get("cohort")
    if cohort:
        lines.append(f"  cohort  : ranked {cohort['ranked_models'] or '[]'}; required models complete "
                     f"{cohort['required_models_complete']}/{cohort['required_models']}; accepted runs "
                     f"{cohort['accepted_runs_of_complete_models']} (minimum {cohort['minimum_runs']})")
        for phase_name, info in cohort["models"].items():
            lines.append(f"    {phase_name} {info['model']:22s} {info['state']:26s} "
                         f"{info['accepted_runs']} accepted runs{' (ranked)' if info['ranked'] else ' (not ranked)'}"
                         f"{' (optional)' if info['optional'] else ''}")
        if not cohort["meets_minimum"]:
            lines.append(f"  cohort below its floor: {len(cohort['ranked_models'])} complete model(s) < "
                         f"{cohort['minimum_ranked_models']}")
    for problem in receipt["problems"][:40]:
        lines.append(f"  PROBLEM: {problem}")
    if len(receipt["problems"]) > 40:
        lines.append(f"  ... {len(receipt['problems']) - 40} more problems (see the JSON receipt)")
    for warning in receipt["warnings"][:20]:
        lines.append(f"  warning: {warning}")
    lines.append("  COMPLETE" if receipt["complete"] else "  NOT COMPLETE")
    return "\n".join(lines)


def write_receipt(receipt: dict, path: str | Path) -> Path:
    target = paths.resolve(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(receipt, indent=2, ensure_ascii=False) + "\n")
    return target
