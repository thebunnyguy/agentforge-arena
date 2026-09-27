"""Campaign analysis: Phase-A early warning, pre- vs post-Phase-0 comparison,
and the official post-Phase-0 baseline.

THE COHORT. Every fresh number here comes from campaign-owned evidence only: for
each manifest cell, the ACTIVE ledger entry, in state ``succeeded``, whose
evaluation passes ``cohort.check_cell_evaluation`` (the single definition of a
valid campaign cell); its runs are loaded with ``cohort.load_cell_records``.
Runs are NEVER selected because they are real, current-version, or for the right
model and task: an evaluation the ledger does not own, a superseded entry, or a
cell whose checks fail contributes nothing. Every output records the evaluation
ids and (campaign-database) run ids it used, and the ownership of every used run
is re-verified against ``runs.job_id`` before anything is reported.

Statistics are the kernel's: each side is aggregated by ``afa_runner``'s
``task_aggregate`` / ``leaderboard`` / ``domain_profile`` over a scratch
in-memory store holding ONLY the selected records (one store per side, so the
historical and fresh sides can never pool).

The historical evidence (``reports/runs.sqlite``) is opened read-only and is
never written. It is the PRE-Phase-0 baseline: it is compared against, never
pooled with, the campaign cohort.
"""

from __future__ import annotations

import dataclasses
import enum
import math
from dataclasses import dataclass, field
from typing import Any

from . import cohort, paths
from . import validate as validate_mod
from .ledger import SUCCEEDED, SUPERSEDED, Ledger, utc_now
from .manifest import Cell, Manifest, evidence_sha256, file_sha256, open_evidence_store

import afa_runner as afa  # noqa: E402  (import bootstrap in paths)
from afa_kernel.types import RunStatus  # noqa: E402

IMPROVED = "improved"
REGRESSED = "regressed"
STABLE = "stable"
INSUFFICIENT = "incomparable/insufficient"
PHASE_A_STATUSES = (IMPROVED, REGRESSED, STABLE, INSUFFICIENT)
STATUS_LABELS = {
    IMPROVED: "observed difference: fresh pass rate above the historical one (Wilson 95% intervals disjoint)",
    REGRESSED: "observed difference: fresh pass rate below the historical one (Wilson 95% intervals disjoint)",
    STABLE: "no observed difference beyond sampling noise (Wilson 95% intervals overlap)",
    INSUFFICIENT: "not compared: fresh evidence missing/invalid or too few valid runs on a side",
}
PHASE_A_RULE = (
    "incomparable/insufficient when the fresh cell is missing or invalid, or either side has "
    "n_valid < repetitions or n_valid == 0; otherwise improved if fresh wilson_low > historical "
    "wilson_high, regressed if fresh wilson_high < historical wilson_low, else stable "
    "(Wilson 95% score intervals from the kernel)"
)
PHASE_A_INTERPRETATION = (
    "Every status in this report is an OBSERVED DIFFERENCE between two measurements, never a "
    "claim that a model got better or worse. Phase-A cells are cells that passed at least once "
    "historically on a task whose version ORACLE later CHANGED (a strengthened hidden-test "
    "oracle): a lower fresh pass rate can mean the old tests were too lenient, not that the model "
    "changed. The execution stack also differs (evaluation lifecycle, seed policy, runtime "
    "release, possibly the Ollama version and model weights); see the per-cell task versions and "
    "the pre- vs post-Phase-0 execution-stack disclosure."
)

NOT_COMPARABLE = "NOT DIRECTLY COMPARABLE"
SAME_VERSION = "SAME TASK VERSION - direct comparison more defensible; execution stack differs"
NO_HISTORY = "NO HISTORICAL EVIDENCE"
NO_FRESH = "no fresh evidence yet"
BASELINE_WARNING = (
    "The historical side is the PRE-Phase-0 baseline (reports/runs.sqlite, read-only); the new side "
    "is this campaign's cohort. Where the task version changed the benchmark itself changed: those "
    "cells are NOT DIRECTLY COMPARABLE. Where the version is the same, the comparison is more "
    "defensible but the execution stack still differs (see the disclosure). Numbers are observed "
    "differences, never claims that a model got better or worse; versions are never pooled."
)

# The historical execution stack is DOCUMENTED (README.md "Evaluation
# provenance"; reports/qwen3.5-9b-evaluation-2026-09-17.md), not persisted per
# run. Nothing below is inferred; unknowns are None.
HISTORICAL_STACK = {
    "status": "DOCUMENTED, not persisted per run",
    "sources": ["README.md, section 'Evaluation provenance'", "reports/qwen3.5-9b-evaluation-2026-09-17.md"],
    "p0_completion_runs": {
        "ollama_version": "0.17.4", "temperature": 0.8, "base_seed": 42, "request_timeout_s": None,
        "recorded_digests": {"qwen2.5-coder:7b": "dae161e27b0e", "llama3.2:latest": "a80c4f17acd5"},
        "other_model_digests": "not recorded",
        "evaluation_path": "examples/eval_persist.py (the README's documented real-agent path): job-less rows, "
                           "no evaluation snapshot; seed = base_seed + a per-model call counter across the pack",
        "models": "not enumerated by the README",
    },
    "per_model_exceptions": {
        "qwen3.5:9b": {"temperature": 0.6, "base_seed": 42, "ollama_version": None, "digest": None,
                       "request_timeout_s": 180,
                       "evaluation_path": "local app evaluation job eb54c065c0b84d099a82570f4aeee83c (runs "
                                          "1101-1220); job linkage not preserved in reports/runs.sqlite",
                       "seed_policy": "not documented for that app version",
                       "note": "Ollama version not documented; model digest not recorded"},
    },
    "not_documented": ["which models' runs were the P0 completion runs",
                       "request timeout of the P0 completion runs",
                       "Ollama version of the qwen3.5:9b evaluation",
                       "digests other than qwen2.5-coder:7b and llama3.2:latest"],
}

EVIDENCE_SCOPE = {
    "class": "real",
    "ownership": "campaign-owned only: the active 'succeeded' ledger entry of each manifest cell whose "
                 "evaluation passes every campaign check (cohort.check_cell_evaluation)",
    "excludes": ["mock / synthetic runs", "legacy (unattested) runs", "old task versions",
                 "provenance conflicts", "evaluations the campaign ledger does not own",
                 "superseded ledger entries", "cells failing a campaign check",
                 "the pre-Phase-0 historical evidence"],
}


class AnalysisError(RuntimeError):
    """An internal integrity assertion failed; nothing is reported."""


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


def _plain(value: Any) -> Any:
    """Faithful JSON-ready form of kernel dataclasses (enums -> .value)."""
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {f.name: _plain(getattr(value, f.name)) for f in dataclasses.fields(value)}
    if isinstance(value, enum.Enum):
        return value.value
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_plain(v) for v in value]
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _scratch_store(records: list) -> "afa.SqliteRunStore":
    """An in-memory raw store holding ONLY ``records`` (new scratch ids)."""
    store = afa.SqliteRunStore(":memory:")
    for record in records:
        store.save_run(record)
    return store


def _side(records: list) -> dict:
    """Kernel aggregate of one (model, task) side; ids are source-DB ids."""
    out: dict[str, Any] = {"n_runs": len(records), "run_ids": sorted(int(r.run_id) for r in records)}
    if not records:
        out.update(n_valid=0, voided=0, passes=0, pass_rate=None, wilson_low=None, wilson_high=None,
                   scores=None)
        return out
    store = _scratch_store(records)
    try:
        agg = afa.task_aggregate(store, records[0].agent, records[0].task_id)
    finally:
        store.close()
    out.update(
        n_valid=agg.n_valid, voided=len(records) - agg.n_valid, passes=agg.n_pass,
        pass_rate=agg.pass_rate if agg.n_valid else None,
        wilson_low=agg.wilson_low, wilson_high=agg.wilson_high,
        scores=({k: getattr(agg, k) for k in ("mean_s", "median_s", "min_s", "max_s", "std_s")}
                if agg.n_valid else None),
    )
    return out


def _wilson(c: int, n: int) -> dict:
    from afa_kernel.confidence import wilson_interval

    lo, hi = wilson_interval(c, n)
    return {"n_valid": n, "passes": c, "pass_rate": (c / n) if n else None, "wilson_low": lo, "wilson_high": hi}


def _historical_records(store, model: str, task_id: str) -> list:
    return store.load_runs(task_id=task_id, agent=model)


def _historical_store(manifest: Manifest):
    if not paths.EVIDENCE_DB.exists():
        raise AnalysisError(f"historical evidence DB not found: {paths.EVIDENCE_DB}")
    sha = evidence_sha256(paths.EVIDENCE_DB)
    if sha != manifest.data["historical_evidence"]["sha256"]:
        raise AnalysisError(f"historical evidence DB hash is {sha}, the frozen plan pins "
                            f"{manifest.data['historical_evidence']['sha256']}; refusing to compare against it")
    return open_evidence_store(paths.EVIDENCE_DB)


def _historical_meta(manifest: Manifest) -> dict:
    sha = evidence_sha256(paths.EVIDENCE_DB)
    return {
        "path": paths.display(paths.EVIDENCE_DB),
        "opened": "read-only, immutable (never written; exactly the hashed file)",
        "sha256": sha,
        "matches_manifest": sha == manifest.data["historical_evidence"]["sha256"],
        "role": "PRE-Phase-0 baseline",
    }


# --------------------------------------------------------------------------- #
# The cohort
# --------------------------------------------------------------------------- #


@dataclass
class CohortCell:
    cell: Cell
    state: str
    evaluation_id: str | None
    ok: bool = False
    problems: list[str] = field(default_factory=list)
    check: cohort.CellCheck | None = None
    records: list = field(default_factory=list)

    @property
    def run_ids(self) -> list[int]:
        return sorted(int(r.run_id) for r in self.records)


@dataclass
class Cohort:
    manifest: Manifest
    ledger: Ledger | None
    db_present: bool
    cells: dict[str, CohortCell]

    def valid(self) -> list[CohortCell]:
        return [c for c in self.cells.values() if c.ok]

    def evidence(self) -> dict:
        valid = self.valid()
        return {
            "rule": EVIDENCE_SCOPE["ownership"],
            "campaign_db": paths.display(self.manifest.db_path()),
            "ledger": paths.display(self.manifest.ledger_path()),
            "ledger_sha256": file_sha256(self.manifest.ledger_path()) if self.ledger else None,
            "evaluation_ids": sorted(c.evaluation_id for c in valid),
            "run_ids": sorted(r for c in valid for r in c.run_ids),
            "by_cell": {c.cell.key: {"evaluation_id": c.evaluation_id, "run_ids": c.run_ids} for c in valid},
        }

    def summary(self) -> dict:
        return {
            "ledger": "loaded" if self.ledger else "absent (campaign not launched)",
            "campaign_db_present": self.db_present,
            "cells_planned": len(self.cells),
            "cells_with_valid_evidence": len(self.valid()),
            "excluded": [
                {"cell": c.cell.key, "state": c.state, "evaluation_id": c.evaluation_id, "problems": c.problems}
                for c in self.cells.values() if not c.ok and c.state != "not_started"
            ],
        }


def load_cohort(manifest: Manifest) -> Cohort:
    """The campaign-owned cohort, cell by cell (read-only)."""
    ledger_path = manifest.ledger_path()
    ledger = (Ledger.load(ledger_path, campaign_id=manifest.campaign_id, manifest_sha256=manifest.sha256)
              if ledger_path.exists() else None)
    from .launcher import reference_digests, reference_ollama_version

    reference = reference_digests(ledger, manifest) if (ledger or manifest.is_sequential) else {}
    reference_version = reference_ollama_version(ledger) if ledger else None
    db_path = manifest.db_path()
    conn = cohort.open_readonly(db_path) if db_path.exists() else None
    cells: dict[str, CohortCell] = {}
    try:
        for cell in manifest.cells():
            entry = ledger.active_entry(cell.key) if ledger else None
            cc = CohortCell(cell, entry["state"] if entry else "not_started",
                            entry.get("evaluation_id") if entry else None)
            cells[cell.key] = cc
            if entry is None:
                cc.problems.append("no active ledger entry")
            elif entry["state"] != SUCCEEDED:
                cc.problems.append(f"active ledger entry is {entry['state']!r}, not 'succeeded'")
            elif conn is None:
                cc.problems.append("campaign database is missing")
            else:
                # the validator's acceptance predicate (cohort checks + every position
                # valid + model identity), never a looser one
                verdict = validate_mod.assess_cell(conn, manifest, cell, entry, reference, reference_version)
                check = verdict["check"]
                cc.check = check
                if not verdict["accepted"]:
                    cc.problems += verdict["problems"] or ["not accepted by the campaign checks"]
                    continue
                records = cohort.load_cell_records(db_path, check)
                version = manifest.task_by_id[cell.task_id]["task_version"]
                for r in records:
                    if (r.run_id not in check.run_ids or r.agent != cell.model or r.task_id != cell.task_id
                            or r.task_version != version):
                        raise AnalysisError(f"{cell.key}: record {r.run_id} is not evidence of this cell")
                cc.records, cc.ok = records, True
        if conn is not None:
            _verify_ownership(conn, cells)
    finally:
        if conn is not None:
            conn.close()
    return Cohort(manifest, ledger, db_path.exists(), cells)


def _verify_ownership(conn, cells: dict[str, CohortCell]) -> int:
    """Every used run id must be owned (runs.job_id) by its cell's cohort evaluation."""
    owner = {rid: c.evaluation_id for c in cells.values() if c.ok for rid in c.run_ids}
    if not owner:
        return 0
    ids = list(owner)
    marks = ",".join("?" for _ in ids)
    rows = {int(r["id"]): r["job_id"] for r in conn.execute(f"SELECT id, job_id FROM runs WHERE id IN ({marks})", ids)}
    bad = [rid for rid, eid in owner.items() if rows.get(rid) != eid]
    if bad:
        raise AnalysisError(f"run ids not owned by their cohort evaluation: {sorted(bad)}")
    return len(owner)


# --------------------------------------------------------------------------- #
# 1) Phase-A early warning
# --------------------------------------------------------------------------- #


def phase_a_status(historical: dict, fresh: dict | None, repetitions: int) -> tuple[str, str]:
    """The Phase-A status rule (see PHASE_A_RULE)."""
    if fresh is None:
        return INSUFFICIENT, "no valid campaign-owned evidence for this cell"
    for name, side in (("historical", historical), ("fresh", fresh)):
        if side["n_valid"] == 0:
            return INSUFFICIENT, f"{name} side has no valid runs"
        if side["n_valid"] < repetitions:
            return INSUFFICIENT, f"{name} side has {side['n_valid']} valid runs < {repetitions}"
    if fresh["wilson_low"] > historical["wilson_high"]:
        return IMPROVED, STATUS_LABELS[IMPROVED]
    if fresh["wilson_high"] < historical["wilson_low"]:
        return REGRESSED, STATUS_LABELS[REGRESSED]
    return STABLE, STATUS_LABELS[STABLE]


def _refuse_sequential(manifest: Manifest, what: str) -> None:
    if manifest.is_sequential:
        raise AnalysisError(f"{what} does not apply to a sequential-local campaign: it is a NEW baseline on the "
                            "current task pack, not a replication of the historical pre-Phase-0 runs")


def phase_a_comparison(manifest: Manifest) -> dict:
    _refuse_sequential(manifest, "the Phase-A early-warning comparison")
    co = load_cohort(manifest)
    reps = manifest.repetitions
    rows: list[dict] = []
    hist_ids: list[int] = []
    store = _historical_store(manifest)
    try:
        for cell in manifest.cells("A"):
            meta = manifest.cell_meta(cell.key)
            task = manifest.task_by_id[cell.task_id]
            old_v = meta.get("historical_version")
            all_hist = _historical_records(store, cell.model, cell.task_id)
            hist_records = [r for r in all_hist if old_v is not None and r.task_version == old_v]
            historical = _side(hist_records)
            historical["task_version"] = old_v
            historical["excluded_other_version_runs"] = len(all_hist) - len(hist_records)
            hist_ids += historical["run_ids"]
            cc = co.cells[cell.key]
            fresh = _side(cc.records) if cc.ok else None
            if fresh is not None:
                fresh.update(evaluation_id=cc.evaluation_id, task_version=task["task_version"])
            status, reason = phase_a_status(historical, fresh, reps)
            if fresh is None:
                reason = f"{reason} (ledger state {cc.state}: {'; '.join(cc.problems)})"
            warnings = []
            if (historical["n_runs"], historical["n_valid"], historical["passes"]) != (
                    meta.get("historical_runs"), meta.get("historical_valid"), meta.get("historical_passes")):
                warnings.append("historical counts differ from the frozen plan")
            rows.append({
                "cell": cell.key, "model": cell.model, "task_id": cell.task_id, "phase": cell.phase,
                "prior_pass": bool(meta.get("prior_pass")),
                "old_task_version": old_v, "new_task_version": task["task_version"],
                "task_version_changed": old_v is not None and old_v != task["task_version"],
                "historical": historical,
                "fresh": fresh,
                "fresh_state": cc.state, "fresh_evaluation_id": cc.evaluation_id if cc.ok else None,
                "fresh_problems": [] if cc.ok else cc.problems,
                "status": status, "status_label": STATUS_LABELS[status], "status_reason": reason,
                "observed_pass_rate_difference": (
                    fresh["pass_rate"] - historical["pass_rate"]
                    if status != INSUFFICIENT else None),
                "warnings": warnings,
            })
    finally:
        store.close()
    by_status = {s: sum(1 for r in rows if r["status"] == s) for s in PHASE_A_STATUSES}
    by_model = {m: {s: sum(1 for r in rows if r["model"] == m and r["status"] == s) for s in PHASE_A_STATUSES}
                for m in manifest.models if any(r["model"] == m for r in rows)}
    return {
        "report": "phase-a-comparison",
        "campaign_id": manifest.campaign_id,
        "manifest_sha256": manifest.sha256,
        "generated_at": utc_now(),
        "interpretation": PHASE_A_INTERPRETATION,
        "wording": "observed difference",
        "status_rule": PHASE_A_RULE,
        "repetitions": reps,
        "historical_evidence": _historical_meta(manifest),
        "cohort": co.summary(),
        "summary": {"cells": len(rows), "prior_pass_cells": sum(1 for r in rows if r["prior_pass"]),
                    "by_status": by_status, "by_model": by_model},
        "cells": rows,
        "evidence": {**co.evidence(), "historical_run_ids": sorted(hist_ids)},
    }


# --------------------------------------------------------------------------- #
# 2) Pre- vs post-Phase-0 comparison
# --------------------------------------------------------------------------- #


def _counts(side: dict) -> dict:
    return {
        "runs": side["n_runs"], "valid": side["n_valid"], "passes": side["passes"],
        "pass_rate": side["pass_rate"], "wilson_low": side["wilson_low"], "wilson_high": side["wilson_high"],
        "mean_s": (side["scores"] or {}).get("mean_s"), "run_ids": side["run_ids"],
    }


def _norm_digest(value: Any) -> str | None:
    if not isinstance(value, str) or not value:
        return None
    return value.split(":", 1)[1] if value.startswith("sha256:") else value


def _launches(ledger: Ledger | None) -> list[dict]:
    out = []
    for launch in (ledger.data.get("launches", []) if ledger else []):
        inv = launch.get("inventory") or {}
        out.append({
            "started_at": launch.get("started_at"), "ended_at": launch.get("ended_at"),
            "phase": launch.get("phase"), "outcome": launch.get("outcome"),
            "tooling_head": launch.get("tooling_head"),
            "runtime_release_tag": launch.get("runtime_release_tag"),
            "runtime_release_commit": launch.get("runtime_release_commit"),
            "api_url": launch.get("api_url"), "api_db_path": launch.get("api_db_path"),
            "check_code": launch.get("check_code"), "warmup": launch.get("warmup"),
            "ollama_version": inv.get("ollama_version"),
            "inventory_captured_at": inv.get("captured_at"),
            "inventory_source": inv.get("source"),
            "digests": {m: (e or {}).get("digest") for m, e in (inv.get("models") or {}).items()},
            "historical_evidence_sha256_start": launch.get("historical_evidence_sha256_start"),
            "historical_evidence_sha256_end": launch.get("historical_evidence_sha256_end"),
        })
    return out


def _historical_persisted_facts(store) -> dict:
    conn = store.connection
    cols = {r[1] for r in conn.execute("PRAGMA table_info(runs)")}
    total = conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
    return {
        "runs": total,
        "runs_without_evaluation": cohort.jobless_run_count(conn),
        "backend_kind_column": ("present" if "backend_kind" in cols
                                else "absent (the provider of each run is not persisted)"),
    }


def execution_stack(manifest: Manifest, ledger: Ledger | None, historical_facts: dict | None = None) -> dict:
    gen = manifest.generation
    launches = _launches(ledger)
    ollama_versions = sorted({l["ollama_version"] for l in launches if l["ollama_version"]})
    fresh_digests: dict[str, list[str]] = {}
    for launch in launches:
        for model, digest in launch["digests"].items():
            if digest and digest not in fresh_digests.setdefault(model, []):
                fresh_digests[model].append(digest)
    hist = HISTORICAL_STACK
    differences = [
        "lifecycle: historical rows are job-less in reports/runs.sqlite (P0 runs: eval_persist.py script output; "
        "qwen3.5:9b: an app job whose linkage was not preserved); fresh runs come from one ATLAS evaluation per "
        "cell with a creation snapshot pinning task version and digest",
        "seed policy: P0 runs used base_seed + a per-model call counter across the pack (qwen3.5:9b: not "
        "documented); fresh seed = base_seed + repeat position",
    ]
    per_model = {}
    for model in manifest.models:
        exc = hist["per_model_exceptions"].get(model)
        h_temp = exc["temperature"] if exc else hist["p0_completion_runs"]["temperature"]
        h_seed = exc["base_seed"] if exc else hist["p0_completion_runs"]["base_seed"]
        h_ollama = exc["ollama_version"] if exc else hist["p0_completion_runs"]["ollama_version"]
        h_digest = None if exc else hist["p0_completion_runs"]["recorded_digests"].get(model)
        fresh = [_norm_digest(d) for d in fresh_digests.get(model, [])]
        if not h_digest:
            digest_cmp = "historical digest not recorded: model identity cannot be verified as the same weights"
        elif not fresh:
            digest_cmp = "no fresh digest recorded yet (no launch inventory)"
        elif all(d and d.startswith(h_digest) for d in fresh):
            digest_cmp = f"same digest prefix {h_digest}"
        else:
            digest_cmp = f"DIFFERENT digest (historical {h_digest}, fresh {', '.join(d[:12] for d in fresh if d)})"
        if not h_ollama:
            ollama_cmp = "historical Ollama version not documented"
        elif not ollama_versions:
            ollama_cmp = "no fresh Ollama version recorded yet"
        elif ollama_versions == [h_ollama]:
            ollama_cmp = f"same Ollama version {h_ollama}"
        else:
            ollama_cmp = f"DIFFERENT Ollama version (historical {h_ollama}, fresh {', '.join(ollama_versions)})"
        per_model[model] = {
            "historical": {"temperature": h_temp, "base_seed": h_seed, "ollama_version": h_ollama,
                           "digest": h_digest, "documented_as": ("README per-model statement" if exc else "README 'P0 completion runs' settings "
                                             "(per-model membership not enumerated there)")},
            "fresh": {"temperature": gen["temperature"], "base_seed": gen["base_seed"],
                      "ollama_versions": ollama_versions, "digests": fresh_digests.get(model, [])},
            "temperature": ("same" if float(h_temp) == float(gen["temperature"])
                            else f"DIFFERENT (historical {h_temp}, fresh {gen['temperature']})"),
            "ollama_version": ollama_cmp,
            "digest": digest_cmp,
        }
    return {
        "historical": {**hist, "persisted_facts": historical_facts},
        "fresh": {
            "status": "RECORDED (frozen campaign manifest, ledger launch records, per-evaluation snapshots)",
            "lifecycle": manifest.data.get("evaluation_granularity"),
            "backend": manifest.backend,
            "temperature": gen["temperature"], "base_seed": gen["base_seed"],
            "request_timeout_s": gen["request_timeout_s"], "seed_policy": gen.get("seed_policy"),
            "runtime_release_tag": manifest.data["code"]["runtime_release_tag"],
            "runtime_release_commit": manifest.data["code"]["runtime_release_commit"],
            "launches": launches,
            "ollama_versions": ollama_versions,
            "inventory_note": "Ollama inventory is an EXTERNAL snapshot taken by the launcher, not "
                              "AgentForge-persisted provenance",
        },
        "differences": differences,
        "per_model": per_model,
    }


def baseline_comparison(manifest: Manifest) -> dict:
    _refuse_sequential(manifest, "the pre- vs post-Phase-0 comparison")
    co = load_cohort(manifest)
    rows: list[dict] = []
    hist_ids: list[int] = []
    store = _historical_store(manifest)
    try:
        facts = _historical_persisted_facts(store)
        for cell in manifest.cells():
            meta = manifest.cell_meta(cell.key)
            new_v = manifest.task_by_id[cell.task_id]["task_version"]
            records = _historical_records(store, cell.model, cell.task_id)
            versions = sorted({r.task_version for r in records})
            old_by_version = {v: _counts(_side([r for r in records if r.task_version == v])) for v in versions}
            hist_ids += [r.run_id for r in records]
            differ = None if not versions else versions != [new_v]
            label = NO_HISTORY if differ is None else (NOT_COMPARABLE if differ else SAME_VERSION)
            cc = co.cells[cell.key]
            new = _counts(_side(cc.records)) if cc.ok else None
            rows.append({
                "cell": cell.key, "model": cell.model, "task_id": cell.task_id, "phase": cell.phase,
                "prior_pass": bool(meta.get("prior_pass")),
                "old_versions": versions, "new_version": new_v, "versions_differ": differ,
                "comparability": label,
                "old": old_by_version[versions[0]] if len(versions) == 1 else None,
                "old_by_version": old_by_version,
                "new": new,
                "new_status": "fresh campaign evidence" if new else NO_FRESH,
                "fresh_evaluation_id": cc.evaluation_id if cc.ok else None,
                "fresh_state": cc.state,
            })
    finally:
        store.close()
    pooled = {}
    for model in manifest.models:
        same = [r for r in rows if r["model"] == model and r["versions_differ"] is False]
        used = [r for r in same if r["new"] is not None]
        pooled[model] = {
            "label": "SAME-TASK-VERSION tasks only (historical version == campaign version) that have fresh "
                     "evidence; never pooled across versions; execution stack differs",
            "tasks": [r["task_id"] for r in used],
            "same_version_tasks_pending": [r["task_id"] for r in same if r["new"] is None],
            "version_changed_tasks_excluded": sum(1 for r in rows if r["model"] == model and r["versions_differ"]),
            "old": _wilson(sum(r["old"]["passes"] for r in used), sum(r["old"]["valid"] for r in used)),
            "new": _wilson(sum(r["new"]["passes"] for r in used), sum(r["new"]["valid"] for r in used)),
        }
    return {
        "report": "pre-vs-post-phase0-comparison",
        "campaign_id": manifest.campaign_id,
        "manifest_sha256": manifest.sha256,
        "generated_at": utc_now(),
        "warning": BASELINE_WARNING,
        "comparability_labels": {"versions_differ": NOT_COMPARABLE, "same_version": SAME_VERSION,
                                 "no_history": NO_HISTORY, "no_fresh": NO_FRESH},
        "historical_evidence": _historical_meta(manifest),
        "execution_stack": execution_stack(manifest, co.ledger, facts),
        "cohort": co.summary(),
        "summary": {
            "cells": len(rows),
            "versions_differ": sum(1 for r in rows if r["versions_differ"]),
            "same_version": sum(1 for r in rows if r["versions_differ"] is False),
            "no_history": sum(1 for r in rows if r["versions_differ"] is None),
            "with_fresh_evidence": sum(1 for r in rows if r["new"] is not None),
        },
        "same_version_pooled_by_model": pooled,
        "cells": rows,
        "evidence": {**co.evidence(), "historical_run_ids": sorted(hist_ids)},
    }


# --------------------------------------------------------------------------- #
# 3) The official post-Phase-0 baseline
# --------------------------------------------------------------------------- #


def official_baseline(manifest: Manifest, *, allow_incomplete: bool = False) -> dict | None:
    receipt = validate_mod.validate_campaign(manifest, phase="all")
    complete = bool(receipt["complete"])
    if not complete and not allow_incomplete:
        return None
    co = load_cohort(manifest)
    valid = co.valid()
    model_states = (receipt.get("cohort") or {}).get("models") or {}
    if manifest.is_sequential:
        # Only models whose FULL batch is accepted are ranked; a partial, classified
        # or not-started model is listed apart, never beside complete ones.
        ranked = set(receipt["cohort"]["ranked_models"])
        valid = [c for c in valid if c.cell.model in ranked]
        if len(valid) != sum(1 for c in co.cells.values() if c.cell.model in ranked):
            raise AnalysisError("a model the validator reports COMPLETE is missing accepted cells in the cohort")
    elif complete and len(valid) != len(co.cells):
        raise AnalysisError("completeness receipt says complete but the cohort is missing cells")
    records = [r for c in valid for r in c.records]
    used = {int(r.run_id) for r in records}
    if used != {rid for c in valid for rid in (c.check.run_ids if c.check else [])}:
        raise AnalysisError("records used differ from the cohort evaluations' run ids")
    store = _scratch_store(records)
    try:
        board = afa.leaderboard(store)
        n_expected = sum(1 for r in records if r.status is not RunStatus.INFRA_FAILURE)
        if sum(e.n for e in board) != n_expected:
            raise AnalysisError("leaderboard n differs from the cohort's valid runs")
        tasks = manifest.task_ids
        leaderboard_rows = []
        for entry in board:
            cells = [c for c in valid if c.cell.model == entry.agent]
            leaderboard_rows.append({
                **_plain(entry),
                "coverage": {"cells_with_fresh_evidence": len(cells), "manifest_tasks": len(tasks),
                             "fraction": len(cells) / len(tasks) if tasks else 0.0},
                "voided_runs": sum(c.check.voided for c in cells if c.check),
                "evaluation_ids": sorted(c.evaluation_id for c in cells),
            })
        matrix = []
        for task_id in tasks:
            task = manifest.task_by_id[task_id]
            row = {"task_id": task_id, "task_version": task["task_version"], "task_digest": task["task_digest"],
                   "domains": task["domains"], "cells": {}}
            for model in manifest.models:
                cc = co.cells.get(f"{model}|{task_id}")
                if manifest.is_sequential and model not in {e.agent for e in board}:
                    row["cells"][model] = {"evidence": None, "note": "not ranked (" + (
                        (next((v["state"] for v in model_states.values() if v["model"] == model), "NOT COMPLETE"))
                    ) + ")"}
                    continue
                if cc is None or not cc.ok:
                    state = cc.state if cc is not None else "not_started"
                    note = NO_FRESH if state == "not_started" else f"no valid evidence ({state}; excluded)"
                    row["cells"][model] = {"evidence": None, "note": note}
                    continue
                agg = afa.task_aggregate(store, model, task_id)
                row["cells"][model] = {"evidence": "campaign-owned", "evaluation_id": cc.evaluation_id,
                                       "run_ids": cc.run_ids, "n_runs": len(cc.records),
                                       "aggregate": _plain(agg)}
            matrix.append(row)
        domains = {e.agent: _plain(afa.domain_profile(store, e.agent, manifest.task_domains())) for e in board}
    finally:
        store.close()
    with_evidence = {e["agent"] for e in leaderboard_rows}
    ledger = co.ledger
    entries = ledger.entries if ledger else []
    provenance = {
        "campaign_id": manifest.campaign_id,
        "manifest_sha256": manifest.sha256,
        "manifest_path": paths.display(manifest.path) if manifest.path else None,
        "created_at": manifest.data.get("created_at"),
        "runtime_release": dict(manifest.data["code"]),
        "backend": manifest.backend,
        "generation": manifest.generation,
        "repetitions": manifest.repetitions,
        "evaluation_granularity": manifest.data.get("evaluation_granularity"),
        "tasks": [{"task_id": t["task_id"], "task_version": t["task_version"], "task_digest": t["task_digest"]}
                  for t in manifest.data["tasks"]],
        "ledger": {"path": paths.display(manifest.ledger_path()),
                   "sha256": file_sha256(manifest.ledger_path()) if ledger else None,
                   "created_at": ledger.data.get("created_at") if ledger else None},
        "launches": _launches(ledger),
        "evaluation_per_cell": {c.cell.key: c.evaluation_id for c in valid},
        "superseded_entries": [
            {"cell": e["cell"], "evaluation_id": e.get("evaluation_id"), "reason": e.get("superseded_reason"),
             "superseded_at": e.get("superseded_at")}
            for e in entries if e["state"] == SUPERSEDED],
        "disowned_evaluations": list(ledger.data.get("disowned", [])) if ledger else [],
        "model_identity": {
            "reference_digests": receipt.get("model_identity", {}).get("reference_digests", {}),
            "reference_ollama_version": receipt.get("model_identity", {}).get("reference_ollama_version"),
            "per_cell": {c.cell.key: {"at_submit": (ledger.active_entry(c.cell.key) or {}).get("model_digest_at_submit"),
                                       "at_finalize": (ledger.active_entry(c.cell.key) or {}).get("model_digest_at_finalize")}
                         for c in valid} if ledger else {},
            "source": "external Ollama inventory snapshots recorded by the launcher (not AgentForge-persisted)",
        },
        "excluded_cells": co.summary()["excluded"],
        "completeness_receipt": {
            "complete": complete, "generated_at": receipt["generated_at"], "expected": receipt["expected"],
            "present": receipt["present"], "missing": receipt["missing"], "extra": receipt["extra"],
            "evidence_classes": receipt["evidence_classes"], "voided_positions": receipt["voided_positions"],
            "problems": receipt["problems"], "warnings": receipt["warnings"],
            "ledger_sha256": receipt["ledger"]["sha256"],
        },
        "historical_evidence": {**_historical_meta(manifest), "role": "not used by this report"},
    }
    sequential = manifest.is_sequential
    return {
        "report": "modern-local-leaderboard" if sequential else "post-phase0-baseline",
        "campaign_id": manifest.campaign_id,
        "manifest_sha256": manifest.sha256,
        "generated_at": utc_now(),
        "official": complete,
        "label": (("OFFICIAL modern local leaderboard" if complete else "PROVISIONAL - campaign incomplete")
                  if sequential else
                  ("OFFICIAL post-Phase-0 baseline" if complete else "PROVISIONAL - campaign incomplete")),
        **({"model_states": model_states, "cohort": receipt.get("cohort")} if sequential else {}),
        "missing_cells": list(receipt["missing"]["cells"]),
        "evidence_scope": EVIDENCE_SCOPE,
        "leaderboard": leaderboard_rows,
        "models_without_evidence": [m for m in manifest.models if m not in with_evidence],
        "roster": manifest.data.get("roster"),
        "task_matrix": matrix,
        "domain_profiles": domains,
        "provenance": provenance,
        "evidence": {**co.evidence(), "runs_verified_owned": len(used)},
    }


# --------------------------------------------------------------------------- #
# Markdown
# --------------------------------------------------------------------------- #


def _f(value: Any, digits: int = 3) -> str:
    return "-" if value is None else f"{value:.{digits}f}"


def _ci(side: dict | None) -> str:
    if not side or side.get("wilson_low") is None or not side.get("n_valid"):
        return "-"
    return f"[{_f(side['wilson_low'])}, {_f(side['wilson_high'])}]"


def _pv(side: dict | None, valid_key: str = "n_valid") -> str:
    if not side or not side.get(valid_key):
        return "-"
    return f"{side['passes']}/{side[valid_key]} ({_f(side['pass_rate'])})"


def _row(*cells: Any) -> str:
    """One Markdown table row; '|' inside a cell (cell keys are model|task) is escaped."""
    return "| " + " | ".join(str(c).replace("|", "\\|") for c in cells) + " |"


def _head(*names: str) -> list[str]:
    return [_row(*names), "|" + "---|" * len(names)]


def render_phase_a(result: dict) -> str:
    s = result["summary"]
    hist = result["historical_evidence"]
    lines = [
        f"# Phase-A comparison - {result['campaign_id']}",
        "",
        f"> **Interpretation - observed differences only.** {result['interpretation']}",
        "",
        f"- Status rule: {result['status_rule']}.",
        f"- Historical: `{hist['path']}` opened read-only (sha256 `{hist['sha256'][:16]}...`, matches "
        f"manifest: {'yes' if hist['matches_manifest'] else 'NO'}).",
        f"- Fresh: campaign-owned cohort only ({result['cohort']['cells_with_valid_evidence']} valid cells; "
        f"ledger {result['cohort']['ledger']}).",
        f"- Manifest `{result['manifest_sha256']}`, generated {result['generated_at']}.",
        "",
        "## Summary",
        "",
        *_head("status", "meaning", "cells"),
    ]
    lines += [_row(st, STATUS_LABELS[st], n) for st, n in s["by_status"].items()]
    lines += ["", *_head("model", *PHASE_A_STATUSES)]
    lines += [_row(m, *(c[st] for st in PHASE_A_STATUSES)) for m, c in s["by_model"].items()]
    lines += ["", "## Cells", "",
              *_head("cell", "prior pass", "task version (old -> new)", "historical passes/valid (rate)",
                     "historical Wilson 95%", "fresh passes/valid (rate)", "fresh Wilson 95%",
                     "fresh evaluation", "status")]
    for r in result["cells"]:
        changed = "" if r["task_version_changed"] else " (unchanged)"
        lines.append(_row(
            r["cell"], "yes" if r["prior_pass"] else "no",
            f"{r['old_task_version']} -> {r['new_task_version']}{changed}",
            _pv(r["historical"]), _ci(r["historical"]), _pv(r["fresh"]), _ci(r["fresh"]),
            r["fresh_evaluation_id"] or f"none ({r['fresh_state']})", f"{r['status']}: {r['status_reason']}"))
    return "\n".join(lines) + "\n"


def render_baseline_comparison(result: dict) -> str:
    stack = result["execution_stack"]
    hist, fresh = stack["historical"], stack["fresh"]
    p0 = hist["p0_completion_runs"]
    lines = [
        f"# Pre- vs post-Phase-0 comparison - {result['campaign_id']}",
        "",
        f"> **Read this first.** {result['warning']}",
        "",
        "## EXECUTION-STACK DISCLOSURE",
        "",
        f"### Historical (pre-Phase-0) side - {hist['status']}",
        "",
        f"- Sources: {'; '.join(hist['sources'])}.",
        f"- P0 completion runs (models {p0['models']}): {p0['evaluation_path']}.",
        f"- P0 completion runs: Ollama {p0['ollama_version']}, temperature {p0['temperature']}, base seed "
        f"{p0['base_seed']}, request timeout {p0['request_timeout_s'] or 'not documented'}; digests recorded "
        "only for " + ", ".join(f"`{m}` `{d}`" for m, d in p0["recorded_digests"].items()) + ".",
    ]
    for model, exc in hist["per_model_exceptions"].items():
        lines.append(f"- `{model}`: {exc['evaluation_path']}; temperature {exc['temperature']}, base seed "
                     f"{exc['base_seed']}, request timeout {exc['request_timeout_s']} s; seed policy "
                     f"{exc['seed_policy']}; {exc['note']}.")
    lines.append(f"- Not documented: {', '.join(hist['not_documented'])}.")
    if hist.get("persisted_facts"):
        pf = hist["persisted_facts"]
        lines.append(f"- Persisted (read-only check): {pf['runs']} runs, {pf['runs_without_evaluation']} "
                     f"without an evaluation; backend_kind column {pf['backend_kind_column']}.")
    lines += [
        "",
        f"### Fresh (post-Phase-0) side - {fresh['status']}",
        "",
        f"- Lifecycle: {fresh['lifecycle']}.",
        f"- Backend `{fresh['backend']['kind']}` at {fresh['backend']['base_url']}; temperature "
        f"{fresh['temperature']}, base seed {fresh['base_seed']}, request timeout {fresh['request_timeout_s']} s.",
        f"- Seed policy: {fresh['seed_policy']}.",
        f"- Runtime release `{fresh['runtime_release_tag']}` ({fresh['runtime_release_commit']}).",
        f"- Ollama version(s) recorded at launch: {', '.join(fresh['ollama_versions']) or 'none recorded yet'} "
        f"({fresh['inventory_note']}).",
    ]
    for launch in fresh["launches"]:
        lines.append(f"- Launch {launch['started_at']} phase {launch['phase']} ({launch['outcome']}): tooling "
                     f"head `{launch['tooling_head']}`, app DB `{launch['api_db_path']}`, Ollama "
                     f"{launch['ollama_version']}, runtime-code check {launch['check_code']}, warm-up "
                     f"{launch['warmup']}.")
    lines += ["", "### Known differences", ""]
    lines += [f"- {d}" for d in stack["differences"]]
    lines += ["", *_head("model", "temperature", "Ollama version", "model digest")]
    lines += [_row(m, d["temperature"], d["ollama_version"], d["digest"]) for m, d in stack["per_model"].items()]
    lines += ["", "## Per-model pooled - SAME-TASK-VERSION tasks only", "",
              "Pooled only over tasks whose historical version equals the campaign version and that have "
              "fresh evidence; never pooled across versions; the execution stack still differs.", "",
              *_head("model", "tasks pooled", "old passes/valid (rate)", "old Wilson 95%",
                     "new passes/valid (rate)", "new Wilson 95%", "same-version tasks pending")]
    for m, p in result["same_version_pooled_by_model"].items():
        lines.append(_row(m, len(p["tasks"]), _pv(p["old"]), _ci(p["old"]), _pv(p["new"]), _ci(p["new"]),
                          len(p["same_version_tasks_pending"])))
    lines += ["", "## Per cell", "",
              *_head("cell", "old version(s)", "new version", "comparability", "old passes/valid (rate)",
                     "old mean S", "new passes/valid (rate)", "new mean S")]
    for r in result["cells"]:
        old, new = r["old"], r["new"]
        old_txt = (_pv(old, "valid") if old else "; ".join(
            f"v{v}: {_pv(c, 'valid')}" for v, c in r["old_by_version"].items()) or "-")
        lines.append(_row(r["cell"], ", ".join(r["old_versions"]) or "-", r["new_version"], r["comparability"],
                          old_txt, _f(old["mean_s"]) if old else "-",
                          _pv(new, "valid") if new else r["new_status"], _f(new["mean_s"]) if new else "-"))
    return "\n".join(lines) + "\n"


def render_official_baseline(result: dict) -> str:
    prov = result["provenance"]
    lines = [f"# {result['label']} - {result['campaign_id']}", ""]
    if not result["official"]:
        missing = result["missing_cells"]
        what = "modern local leaderboard" if result.get("model_states") else "post-Phase-0 baseline"
        lines += [f"> **PROVISIONAL - campaign incomplete.** This is NOT the official {what}. "
                  f"{len(missing)} cell(s) lack valid campaign-owned evidence: " + ", ".join(missing), ""]
    if result.get("model_states"):
        lines += ["Only models whose full 24 tasks x 5 repetitions batch is accepted are ranked; every other "
                  "roster model is listed below with its state and is never ranked beside complete models.", "",
                  "## Roster", "", *_head("phase", "model", "logical model", "state", "accepted runs", "note")]
        for phase_name, info in result["model_states"].items():
            note = (info["classification"] or {}).get("reason", "") if info.get("classification") else (
                "optional" if info["optional"] else "")
            lines.append(_row(phase_name, info["model"], info["logical_name"], info["state"], info["accepted_runs"],
                              note))
        lines.append("")
    scope = result["evidence_scope"]
    lines += [
        f"- Evidence scope: `{scope['class']}`, {scope['ownership']}.",
        f"- Excludes: {', '.join(scope['excludes'])}.",
        f"- Evaluations used: {len(result['evidence']['evaluation_ids'])}; runs used (ownership verified): "
        f"{result['evidence']['runs_verified_owned']}.",
        "",
        "## Leaderboard (kernel Wilson 95% lower-bound ranking)",
        "",
        *_head("rank", "model", "n", "pass rate", "Wilson 95%", "coverage", "voided", "provisional"),
    ]
    for e in result["leaderboard"]:
        rank = "-" if e["rank_low"] is None else (str(e["rank_low"]) if e["rank_low"] == e["rank_high"]
                                                   else f"{e['rank_low']}-{e['rank_high']}")
        cov = e["coverage"]
        lines.append(_row(rank, e["agent"], e["n"], _f(e["pass_rate"]),
                          f"[{_f(e['wilson_low'])}, {_f(e['wilson_high'])}]",
                          f"{cov['cells_with_fresh_evidence']}/{cov['manifest_tasks']}", e["voided_runs"],
                          "yes" if e["provisional"] else "no"))
    for m in result["models_without_evidence"]:
        if result.get("model_states"):
            continue  # listed in the roster table above; never ranked
        lines.append(_row("-", m, 0, "-", "-", f"0/{len(result['task_matrix'])}", 0, NO_FRESH))
    models = list(result["task_matrix"][0]["cells"]) if result["task_matrix"] else []
    lines += ["", "## Task matrix (passes/valid, Wilson 95%)", "", *_head("task (version)", *models)]
    for row in result["task_matrix"]:
        cells = []
        for m in models:
            c = row["cells"][m]
            a = c.get("aggregate")
            cells.append(c["note"] if a is None else
                         f"{a['n_pass']}/{a['n_valid']} [{_f(a['wilson_low'], 2)}, {_f(a['wilson_high'], 2)}]")
        lines.append(_row(f"{row['task_id']} ({row['task_version']})", *cells))
    lines += ["", "## Domain profiles", ""]
    for model, scores in result["domain_profiles"].items():
        lines += [f"### {model}", "",
                  *_head("domain", "pooled pass rate", "Wilson 95%", "n_eff", "tasks", "runs", "displayable")]
        lines += [_row(d["domain"], _f(d["pooled_pass_rate"]), f"[{_f(d['wilson_low'])}, {_f(d['wilson_high'])}]",
                       _f(d["n_eff"], 1), d["n_tasks"], d["n_runs"], "yes" if d["displayable"] else "no")
                  for d in scores]
        lines.append("")
    gen = prov["generation"]
    receipt = prov["completeness_receipt"]
    release = prov["runtime_release"]
    lines += [
        "## Provenance",
        "",
        f"- Campaign `{prov['campaign_id']}`, manifest `{prov['manifest_sha256']}`.",
        f"- Runtime release `{release['runtime_release_tag']}` ({release['runtime_release_commit']}).",
        f"- Backend `{prov['backend']['kind']}` at {prov['backend']['base_url']}; temperature {gen['temperature']}, "
        f"base seed {gen['base_seed']}, request timeout {gen['request_timeout_s']} s; {prov['repetitions']} "
        "repetitions per cell.",
        f"- Seed policy: {gen.get('seed_policy')}.",
        f"- Completeness receipt: complete={receipt['complete']}, {receipt['present']['cells_complete']}/"
        f"{receipt['expected']['cells']} cells, {receipt['present']['runs']}/{receipt['expected']['runs']} runs, "
        f"{len(receipt['problems'])} problem(s).",
    ]
    for launch in prov["launches"]:
        digests = ", ".join(f"{m} {(d or '-')[:12]}" for m, d in launch["digests"].items())
        lines.append(f"- Launch {launch['started_at']} phase {launch['phase']} ({launch['outcome']}): tooling "
                     f"`{launch['tooling_head']}`, app DB `{launch['api_db_path']}`, Ollama "
                     f"{launch['ollama_version']}; digests: {digests or 'none'}.")
    for e in prov["superseded_entries"]:
        lines.append(f"- Superseded (never counted): {e['cell']} evaluation {e['evaluation_id']} - {e['reason']}")
    for e in prov["disowned_evaluations"]:
        lines.append(f"- Disowned (never counted): evaluation {e['evaluation_id']} - {e['reason']}")
    for model, digest in prov["model_identity"]["reference_digests"].items():
        source = ("pinned registry digest in the frozen manifest" if result.get("model_states")
                  else "external Ollama inventory, first launch")
        lines.append(f"- Model identity ({source}): {model} `{digest}`")
    lines += ["", *_head("task", "version", "digest")]
    lines += [_row(t["task_id"], t["task_version"], f"`{t['task_digest']}`") for t in prov["tasks"]]
    lines += ["", *_head("cell", "evaluation")]
    lines += [_row(k, v) for k, v in prov["evaluation_per_cell"].items()]
    return "\n".join(lines) + "\n"
