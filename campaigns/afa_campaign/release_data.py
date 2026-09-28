"""Benchmark release datasets for the web UI.

Turns a release definition (``campaigns/releases/<id>.json``: the editorial
facts no artifact carries, each with its source) plus the frozen evidence it
names into one normalized, web-consumable JSON file
(``web/src/data/benchmark-releases/<id>.json``)::

    campaign result artifacts + release definition
            -> build_release()  (cross-checks every duplicated value; fails loudly)
            -> web dataset      (deterministic bytes; ``--check`` detects drift)

Two source kinds exist:

``campaign``       a completed campaign's committed results (manifest, official
                   leaderboard, completeness receipt, model receipts,
                   SHA256SUMS). Every number is copied from the artifact that
                   produced it — ranks, pass rates and Wilson intervals are the
                   kernel's, never recomputed here.
``historical-db``  the read-only pre-Phase-0 evidence database, opened
                   immutable after its hash is checked. Only recorded counts are
                   shown: no ranks, no intervals, nothing the database does not
                   hold.

The generator reads the frozen evidence and writes only the web dataset.
"""
from __future__ import annotations

import datetime
import json
import math
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any

from . import paths
from .manifest import canonical_sha256, file_sha256

SCHEMA_VERSION = 1
RELEASES_DIR = paths.REPO / "campaigns" / "releases"
WEB_DATA_DIR = paths.REPO / "web" / "src" / "data" / "benchmark-releases"
STATUSES = ("OFFICIAL", "EXPERIMENTAL", "SUPERSEDED", "HISTORICAL")
EVIDENCE_CLASSES = ("real", "synthetic", "legacy", "conflict")  # afa_api/evidence.py


class ReleaseDataError(RuntimeError):
    """The release's evidence is inconsistent; no dataset is written."""


class _Checks:
    def __init__(self, release_id: str) -> None:
        self.release_id = release_id
        self.problems: list[str] = []

    def need(self, condition: bool, message: str) -> bool:
        if not condition:
            self.problems.append(message)
        return bool(condition)

    def equal(self, what: str, *values: Any) -> bool:
        first = values[0]
        return self.need(all(v == first for v in values[1:]), f"{what} disagrees across artifacts: {values!r}")

    def raise_if_any(self) -> None:
        if self.problems:
            listed = "\n  - ".join(self.problems)
            raise ReleaseDataError(f"release {self.release_id}: {len(self.problems)} problem(s):\n  - {listed}")


def _load(path: Path) -> Any:
    with open(path, encoding="utf-8") as handle:
        return json.load(handle)


def _rel(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _source(root: Path, path: Path) -> dict:
    return {"path": _rel(root, path), "sha256": file_sha256(path)}


def definitions(root: Path | None = None) -> list[dict]:
    folder = (root or paths.REPO) / "campaigns" / "releases"
    out = []
    for path in sorted(folder.glob("*.json")):
        try:
            out.append(_load(path))
        except json.JSONDecodeError as exc:
            raise ReleaseDataError(f"{path.name}: not valid JSON ({exc})") from None
    return out


def _common(defn: dict, checks: _Checks) -> dict:
    checks.need(defn.get("schema_version") == SCHEMA_VERSION, f"definition schema_version must be {SCHEMA_VERSION}")
    checks.need(defn.get("status") in STATUSES, f"status must be one of {STATUSES}")
    for key in ("id", "title", "short_title", "released_at", "summary"):
        checks.need(isinstance(defn.get(key), str) and defn[key].strip() != "", f"definition needs a non-empty {key}")
    try:
        datetime.date.fromisoformat(str(defn.get("released_at")))
        iso = len(str(defn.get("released_at"))) == 10
    except ValueError:
        iso = False
    checks.need(iso, "released_at must be an ISO date (YYYY-MM-DD)")
    git = defn.get("git") or {}
    for key in ("repository_url", "tag", "commit"):  # the ref every evidence link points at
        checks.need(isinstance(git.get(key), str) and git[key] != "", f"definition needs git.{key}")
    return {
        "schema_version": SCHEMA_VERSION,
        "id": defn.get("id"),
        "title": defn.get("title"),
        "short_title": defn.get("short_title"),
        "status": defn.get("status"),
        "released_at": defn.get("released_at"),
        "summary": defn.get("summary"),
        "repository": {"url": git.get("repository_url"), "ref": git.get("tag"), "commit": git.get("commit")},
    }


def _caveats(defn: dict, models: dict[str, dict], checks: _Checks) -> list[dict]:
    out = []
    facts = {f["id"]: f for f in defn.get("documented_facts", [])}
    for caveat in defn.get("caveats", []):
        model = caveat.get("model")
        checks.need(model is None or model in models, f"caveat {caveat.get('id')} names unknown model {model!r}")
        prose = " ".join([caveat.get("summary", ""), *caveat.get("points", [])])
        for check in caveat.get("checks", []):
            actual = (models.get(model) or {}).get("totals", {}).get(check["field"])
            checks.need(actual == check["equals"],
                        f"caveat {caveat['id']}: {model} {check['field']} is {actual!r}, the caveat says {check['equals']!r}")
            checks.need(str(check["equals"]) in prose,  # the verified number is the one the reader sees
                        f"caveat {caveat['id']}: its text does not state the checked {check['field']} {check['equals']}")
        fact = caveat.get("documented_fact")
        checks.need(fact is None or fact in facts, f"caveat {caveat.get('id')} cites unknown documented fact {fact!r}")
        if fact in facts:
            checks.need(f"{facts[fact]['value']} of {facts[fact]['of']}" in prose,
                        f"caveat {caveat['id']}: its text does not state the documented {facts[fact]['value']} of "
                        f"{facts[fact]['of']}")
        out.append({k: caveat.get(k) for k in ("id", "model", "kind", "label", "summary", "points", "source")}
                   | {"verified_fields": [c["field"] for c in caveat.get("checks", [])], "documented_fact": fact})
    for model in models.values():
        model["caveat_ids"] = [c["id"] for c in out if c["model"] == model["id"]]
    return out


def _consistent_rate(checks: _Checks, what: str, rate: float, passes: int, runs: int, low: float, high: float) -> None:
    """A served rate must be its counts' ratio and lie inside its own interval (checked, never recomputed)."""
    checks.need(runs > 0 and abs(rate - passes / runs) < 1e-9, f"{what}: pass rate {rate} disagrees with {passes}/{runs}")
    checks.need(0 <= low <= rate <= high <= 1, f"{what}: pass rate {rate} lies outside its Wilson interval [{low}, {high}]")


def _evidence_links(defn: dict, root: Path, checks: _Checks) -> list[dict]:
    links = []
    for link in defn.get("evidence_links", []):
        checks.need((root / link["path"]).exists(), f"evidence link {link['path']} does not exist")
        links.append({"label": link["label"], "path": link["path"], "kind": link["kind"]})
    return links


# --------------------------------------------------------------------------- #
# campaign releases
# --------------------------------------------------------------------------- #


def _sha256sums(path: Path) -> dict[str, dict[str, str]]:
    """``<sha>  original|committed  <relpath>`` (the campaign's 3-column format)."""
    out: dict[str, dict[str, str]] = {"original": {}, "committed": {}}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        sha, kind, rel = line.split(None, 2)
        out[kind][rel.strip()] = sha
    return out


def _build_campaign(defn: dict, root: Path, checks: _Checks) -> dict:
    src = defn["source"]
    cdir = root / src["campaign_dir"]
    manifest_path = cdir / "manifest.json"
    board_path = cdir / src["leaderboard"]
    comp_path = cdir / src["completeness"]
    sums_path = cdir / src["sha256sums"]
    receipt_paths = sorted((cdir / src["receipts"]).glob("*.json"))
    changes_path = root / src["task_version_changes"]
    manifest, board, comp = _load(manifest_path), _load(board_path), _load(comp_path)
    receipts = {r["model"]: r for r in (_load(p) for p in receipt_paths)}
    receipt_files = {_load(p)["model"]: p for p in receipt_paths}

    # --- the committed results are the ones SHA256SUMS froze ------------------
    sums = _sha256sums(sums_path)
    results = sums_path.parent
    listed = set(sums["committed"])
    present = {_rel(results, p) for p in results.rglob("*") if p.is_file() and p.name != "SHA256SUMS"}
    checks.equal("the files SHA256SUMS lists vs the committed result files", sorted(listed), sorted(present))
    for rel, sha in sorted(sums["committed"].items()):
        checks.need((results / rel).is_file() and file_sha256(results / rel) == sha,
                    f"results/{rel} does not match its SHA256SUMS hash")

    # --- one campaign, one frozen plan, one official complete result ----------
    campaign_id = manifest["campaign_id"]
    manifest_sha = canonical_sha256(manifest)
    checks.equal("campaign_id", campaign_id, board["campaign_id"], comp["campaign_id"],
                 *[r["campaign_id"] for r in receipts.values()])
    checks.equal("manifest_sha256", manifest_sha, board["manifest_sha256"], comp["manifest_sha256"],
                 *[r["manifest_sha256"] for r in receipts.values()])
    checks.need(board.get("official") is True, "the leaderboard is not OFFICIAL")
    checks.need(board.get("cohort", {}).get("meets_minimum") is True, "the cohort does not meet its minimum")
    checks.need(comp.get("complete") is True, "the completeness receipt is not complete")
    checks.need(comp.get("problems") == [], f"the completeness receipt lists problems: {comp.get('problems')}")
    checks.need(board.get("missing_cells") == [], "the leaderboard lists missing cells")
    checks.need(board["provenance"]["completeness_receipt"]["complete"] is True, "the leaderboard's receipt is not complete")
    classes = comp.get("evidence_classes", {})
    checks.need(set(classes) <= set(EVIDENCE_CLASSES), f"unknown evidence classes {sorted(set(classes) - set(EVIDENCE_CLASSES))}")
    for bad in ("synthetic", "legacy", "conflict"):
        checks.need(classes.get(bad, 0) == 0, f"{classes.get(bad)} {bad} run(s) in an official release")
    checks.equal("roster", manifest["roster"], board["roster"])
    generation = manifest["generation"]
    checks.equal("generation settings", generation, board["provenance"]["generation"],
                 *[r["generation"] for r in receipts.values()])
    ollama_version = manifest["execution"]["ollama_server_version"]
    runtime = manifest["code"]
    checks.equal("runtime release", (runtime["runtime_release_tag"], runtime["runtime_release_commit"]),
                 (board["provenance"]["runtime_release"]["runtime_release_tag"],
                  board["provenance"]["runtime_release"]["runtime_release_commit"]),
                 *[(r["agentforge_release"]["tag"], r["agentforge_release"]["commit"]) for r in receipts.values()])

    # --- tasks: the pinned pack, identical in every artifact ------------------
    tasks = manifest["tasks"]
    matrix = {t["task_id"]: t for t in board["task_matrix"]}
    checks.equal("task ids", [t["task_id"] for t in tasks], [t["task_id"] for t in board["task_matrix"]],
                 [t["task_id"] for t in board["provenance"]["tasks"]])
    for task in tasks:
        tid = task["task_id"]
        checks.equal(f"{tid} version/digest", (task["task_version"], task["task_digest"]),
                     (matrix[tid]["task_version"], matrix[tid]["task_digest"]),
                     *[(p["task_version"], p["task_digest"]) for p in board["provenance"]["tasks"] if p["task_id"] == tid])
        checks.equal(f"{tid} domains", [list(d) for d in task["domains"]], [list(d) for d in matrix[tid]["domains"]])
    changes = {c["task_id"]: c for c in _load(changes_path)["tasks"]}
    for tid, change in changes.items():
        pinned = next((t["task_version"] for t in tasks if t["task_id"] == tid), None)
        checks.need(pinned == change["new_version"], f"{tid}: pinned {pinned} but ORACLE remediation names {change['new_version']}")

    # --- models ---------------------------------------------------------------
    rows = {row["agent"]: row for row in board["leaderboard"]}
    states = {s["model"]: s for s in board["model_states"].values()}
    reference = board["provenance"]["model_identity"]["reference_digests"]
    per_cell_identity = board["provenance"]["model_identity"]["per_cell"]
    comp_cells = {c["cell"]: c for c in comp["cells"]}
    eval_per_cell = board["provenance"]["evaluation_per_cell"]
    checks.equal("receipt models vs roster", sorted(receipts), sorted(r["model"] for r in manifest["roster"]))
    models: dict[str, dict] = {}
    for entry in manifest["roster"]:
        tag, ident = entry["model"], entry["expected_identity"]
        state, row, rec = states.get(tag, {}), rows.get(tag), receipts.get(tag)
        checks.need(rec is not None, f"{tag}: no model receipt")
        if rec is None:
            continue
        checks.equal(f"{tag} expected identity", ident, rec["expected_identity"])
        observed = rec["observed_identity"]
        details = observed["ollama_details"]
        checks.equal(f"{tag} digest", ident["digest"], reference.get(tag), comp["model_identity"]["reference_digests"].get(tag),
                     *observed["digests"])
        checks.need(observed.get("digest_matches_pin") is True, f"{tag}: observed digest does not match the pin")
        checks.equal(f"{tag} family/size/quantization/format",
                     (ident["family"], ident["parameter_size"], ident["quantization"], ident["format"]),
                     (details["family"], details["parameter_size"], details["quantization_level"], details["format"]))
        checks.equal(f"{tag} Ollama versions", [ollama_version], observed["ollama_versions"])
        checks.equal(f"{tag} logical name", entry["logical_name"], rec["logical_name"], state.get("logical_name"))
        totals, agg = rec["totals"], rec["aggregate"]
        per_model = comp["per_model"][tag]
        task_rows, pass_sum, identity_ok = [], 0, 0
        rec_cells = {c["task_id"]: c for c in rec["cells"]}
        checks.equal(f"{tag} receipt cells", sorted(rec_cells), sorted(t["task_id"] for t in tasks))
        for task in tasks:
            tid, key = task["task_id"], f"{tag}|{task['task_id']}"
            cell = matrix[tid]["cells"].get(tag) or {}
            if cell.get("evidence") is None:
                task_rows.append({"task_id": tid, "task_version": task["task_version"], "evidence": False,
                                  "note": cell.get("note", "no campaign evidence")})
                continue
            a, rc, cc = cell["aggregate"], rec_cells[tid], comp_cells[key]
            checks.equal(f"{key} task pin", (task["task_version"], task["task_digest"]), (rc["task_version"], rc["task_digest"]))
            checks.equal(f"{key} passes", a["n_pass"], rc["passed"], cc["passed"])
            checks.equal(f"{key} valid runs", a["n_valid"], rc["valid"], cc["valid"], cell["n_runs"])
            checks.equal(f"{key} evaluation", cell["evaluation_id"], rc["evaluation_id"], cc["evaluation_id"], eval_per_cell[key])
            checks.equal(f"{key} run ids", cell["run_ids"], rc["run_ids"])
            checks.need(abs(a["timeout_rate"] * a["n_valid"] - rc["timeouts"]) < 1e-9,
                        f"{key}: timeout rate {a['timeout_rate']} disagrees with {rc['timeouts']} timeouts")
            checks.need(cc["ok"] is True and cc["problems"] == [], f"{key}: completeness cell not ok")
            ids = per_cell_identity[key]
            if ids["at_submit"] == ids["at_finalize"] == rc["model_digest_at_submit"] == rc["model_digest_at_finalize"] \
                    == cc["model_digest"] == ident["digest"]:
                identity_ok += 1
            checks.equal(f"{key} Ollama version", ollama_version, rc["ollama_version"])
            _consistent_rate(checks, key, a["pass_rate"], a["n_pass"], a["n_valid"], a["wilson_low"], a["wilson_high"])
            pass_sum += a["n_pass"]
            task_rows.append({
                "task_id": tid, "task_version": task["task_version"], "evidence": True,
                "runs": a["n_valid"], "passes": a["n_pass"], "pass_rate": a["pass_rate"],
                "wilson_low": a["wilson_low"], "wilson_high": a["wilson_high"], "mean_final_score": a["mean_s"],
                "timeouts": rc["timeouts"], "request_timeout_hits": rc["request_timeout_hits"],
                "agent_errors": rc["agent_errors"], "voided": rc["voided"], "provisional": a["provisional"],
                "evaluation_id": cell["evaluation_id"],
            })
        checks.need(identity_ok == len(tasks), f"{tag}: {len(tasks) - identity_ok} cell(s) not at the pinned digest")
        checks.equal(f"{tag} passes", totals["passed"], per_model["passed"], pass_sum)
        n = row["n"] if row else totals["valid"]
        checks.equal(f"{tag} accepted runs", n, totals["valid"], per_model["valid"], agg["kernel_leaderboard_entry"]["n"],
                     rec["accepted_runs"])
        if row:
            checks.equal(f"{tag} pass rate / Wilson", (row["pass_rate"], row["wilson_low"], row["wilson_high"]),
                         (agg["pass_rate"], agg["wilson_low"], agg["wilson_high"]),
                         tuple(agg["kernel_leaderboard_entry"][k] for k in ("pass_rate", "wilson_low", "wilson_high")))
            checks.equal(f"{tag} timeouts / full request timeouts / agent errors / voided",
                         (row["timeouts"], row["request_timeout_hits"], row["agent_errors"], row["voided_runs"]),
                         (totals["timeouts"], totals["request_timeout_hits"], totals["agent_errors"], totals["voided"]))
            checks.equal(f"{tag} evaluations", sorted(row["evaluation_ids"]), sorted(rec["evaluation_ids"]))
            checks.need(1 <= row["rank_low"] <= row["rank_high"] <= len(board["leaderboard"]),
                        f"{tag}: rank {row['rank_low']}-{row['rank_high']} is outside 1..{len(board['leaderboard'])}")
        _consistent_rate(checks, tag, agg["pass_rate"], totals["passed"], n, agg["wilson_low"], agg["wilson_high"])
        domains = [{k: d[k] for k in ("domain", "pooled_pass_rate", "wilson_low", "wilson_high", "n_eff", "n_tasks",
                                      "n_runs", "stability", "displayable")}
                   for d in board["domain_profiles"].get(tag, [])]
        for d in domains:
            checks.need(0 <= d["wilson_low"] <= d["pooled_pass_rate"] <= d["wilson_high"] <= 1,
                        f"{tag} {d['domain']}: pooled rate outside its Wilson interval")
        models[tag] = {
            "id": tag,
            "display_name": entry["logical_name"],
            "phase": entry["phase"],
            "optional": entry["optional"],
            "state": state.get("state"),
            "ranked": bool(state.get("ranked")) and row is not None,
            "classification": state.get("classification"),
            "rank": {"low": row["rank_low"], "high": row["rank_high"], "provisional": row["provisional"]} if row else None,
            "identity": {
                "ollama_tag": tag,
                "digest": ident["digest"],
                "family": ident["family"],
                "parameter_size": ident["parameter_size"],
                "quantization": ident["quantization"],
                "format": ident["format"],
                "download_bytes": ident["download_bytes"],
                "context_length": details.get("context_length"),
                "digest_verified_cells": identity_ok,
                "ollama_version": ollama_version,
            },
            "totals": {
                "runs": n, "passes": totals["passed"], "pass_rate": agg["pass_rate"],
                "wilson_low": agg["wilson_low"], "wilson_high": agg["wilson_high"],
                "mean_final_score": agg["mean_final_score"], "timeouts": totals["timeouts"],
                "request_timeout_hits": totals["request_timeout_hits"], "agent_errors": totals["agent_errors"],
                "voided": totals["voided"],
            },
            "coverage": {"tasks_with_evidence": row["coverage"]["cells_with_fresh_evidence"] if row else per_model["cells_complete"],
                         "tasks_total": len(tasks)},
            "run_window": {"started_at": rec["started_at"], "finished_at": rec["finished_at"]},
            "tooling_heads": rec["tooling_heads"],
            "receipt": _rel(root, receipt_files[tag]),
            "domains": domains,
            "tasks": task_rows,
            "caveat_ids": [],
            "documented_facts": [f for f in defn.get("documented_facts", []) if f.get("model") == tag],
        }
    # the official order is the leaderboard's own; unranked models follow in roster order
    ordered = [models[r["agent"]] for r in board["leaderboard"] if r["agent"] in models]
    ordered += [m for m in models.values() if m not in ordered]
    checks.equal("ranked order", [m["id"] for m in ordered if m["rank"]], [r["agent"] for r in board["leaderboard"]])
    # the kernel orders ranked rows by Wilson lower bound (kernel/afa_kernel/ranking.py rank_by_lcb): verify, never re-sort
    rows_in_order = board["leaderboard"]
    checks.need(all(a["wilson_low"] >= b["wilson_low"] and a["rank_low"] <= b["rank_low"]
                    for a, b in zip(rows_in_order, rows_in_order[1:])),
                "the leaderboard's row order is not the kernel's Wilson-lower-bound order")

    # --- integrity: every count read from the receipts, none assumed ----------
    launches = board["provenance"]["launches"]
    historical_sha = manifest["historical_evidence"]["sha256"]
    expected, present_counts = comp["expected"], comp["present"]
    integrity = {
        "complete": comp["complete"],
        "official": board["official"],
        "problems": comp["problems"],
        "warnings": comp["warnings"],
        "planned_runs": expected["runs"],
        "accepted_runs": present_counts["runs"],
        "valid_runs": present_counts["valid_runs"],
        "planned_evaluations": expected["cells"],
        "accepted_evaluations": present_counts["cells_complete"],
        "models_total": expected["models"],
        "models_complete": present_counts["models_complete"],
        "tasks_total": len(tasks),
        "task_coverage_min": min(m["coverage"]["tasks_with_evidence"] for m in models.values()),
        "missing_runs": comp["missing"]["positions"],
        "missing_evaluations": len(comp["missing"]["cells"]),
        "extra_runs": comp["extra"]["campaign_owned_positions_beyond_plan"],
        "untracked_evaluations": len(comp["extra"]["untracked_campaign_evaluations"]),
        "disowned_evaluations": len(comp["extra"]["disowned_evaluations"]),
        "superseded_entries": len(board["provenance"]["superseded_entries"]),
        "voided_runs": comp["voided_positions"],
        "evidence_classes": {cls: classes.get(cls, 0) for cls in EVIDENCE_CLASSES},
        "backend_kind": board["provenance"]["backend"]["kind"],
        "task_pins": {"tasks": len(tasks), "basis": "every accepted run is at its task's pinned version and content "
                      "digest (checked per run by the campaign validator; the completeness receipt is complete with no problems)"},
        "model_identity": {"cells_at_pinned_digest": sum(m["identity"]["digest_verified_cells"] for m in models.values()),
                           "cells_total": expected["cells"], "ollama_version": ollama_version},
        "runtime": {"tag": runtime["runtime_release_tag"], "commit": runtime["runtime_release_commit"],
                    "paths": runtime["runtime_paths"],
                    "launches_with_code_check": sum(1 for launch in launches if launch.get("check_code") is True),
                    "launches": len(launches)},
        "historical_evidence_unchanged": all(
            launch.get("historical_evidence_sha256_start") == launch.get("historical_evidence_sha256_end") == historical_sha
            for launch in launches),
        "not_claimed": defn.get("integrity_not_claimed", []),
    }
    checks.equal("accepted runs", integrity["accepted_runs"], integrity["planned_runs"],
                 board["cohort"]["accepted_runs_of_complete_models"], board["evidence"]["runs_verified_owned"])
    checks.equal("run total", integrity["accepted_runs"], sum(m["totals"]["runs"] for m in models.values()))
    checks.need(integrity["historical_evidence_unchanged"], "a launch recorded a changed historical evidence hash")

    methodology = {
        "campaign_id": campaign_id,
        "campaign_title": manifest["title"],
        "plan_kind": manifest["kind"],
        "mode": manifest["mode"],
        "backend": {"kind": manifest["backend"]["kind"], "base_url": manifest["backend"]["base_url"]},
        "ollama_version": ollama_version,
        "temperature": generation["temperature"],
        "base_seed": generation["base_seed"],
        "seeds": [generation["base_seed"] + i for i in range(manifest["repetitions"])],
        "seed_policy": generation["seed_policy"],
        "request": generation["request"],
        "request_timeout_s": generation["request_timeout_s"],
        "repetitions": manifest["repetitions"],
        "evaluation_granularity": board["provenance"]["evaluation_granularity"],
        "official_rule": manifest["execution"]["official_rule"],
        "minimum_ranked_models": manifest["execution"]["minimum_ranked_models"],
        "ranking_method": defn["ranking_method"],
        "one_model_at_a_time": manifest["execution"]["one_model_at_a_time"],
        "runtime_release": {"tag": runtime["runtime_release_tag"], "commit": runtime["runtime_release_commit"],
                            "paths": runtime["runtime_paths"], "rule": runtime["rule"]},
        "manifest_sha256": manifest_sha,
        "ledger_sha256": board["provenance"]["ledger"]["sha256"],
        "historical_evidence": {"path": manifest["historical_evidence"]["path"], "sha256": historical_sha},
        "evidence_scope": board["evidence_scope"],
        "model_identity_source": board["provenance"]["model_identity"]["source"],
    }
    counts = {
        "models": len(models), "models_ranked": sum(1 for m in models.values() if m["ranked"]),
        "tasks": len(tasks), "repetitions": manifest["repetitions"],
        "evaluations": integrity["accepted_evaluations"], "runs": integrity["accepted_runs"],
        "runs_per_model": manifest["repetitions"] * len(tasks),
    }
    checks.equal("evaluations = models x tasks", counts["evaluations"], counts["models"] * counts["tasks"])
    checks.equal("runs = evaluations x repetitions", counts["runs"], counts["evaluations"] * counts["repetitions"])
    task_pack = [{
        "task_id": t["task_id"], "task_version": t["task_version"], "task_digest": t["task_digest"],
        "domains": [{"domain": d, "weight": w} for d, w in t["domains"]],
        "activity": t["activity"], "timeout_s": t["timeout_s"],
        "version_changed_since_pre_phase0": t["task_id"] in changes,
    } for t in tasks]
    domain_names = sorted({d for t in tasks for d, _ in t["domains"]})
    for model in models.values():
        checks.equal(f"{model['id']} domains", [d["domain"] for d in model["domains"]], domain_names)
    caveats = _caveats(defn, models, checks)
    links = _evidence_links(defn, root, checks) + [
        {"label": f"Model receipt — {m['display_name']}", "path": m["receipt"], "kind": "receipt", "model": m["id"]}
        for m in ordered]
    sources = [_source(root, p) for p in (manifest_path, board_path, comp_path, sums_path, *receipt_paths, changes_path)]
    return {
        "campaign_id": campaign_id,
        "comparable": True,
        "ranked": True,
        "counts": counts,
        "headline": {"inference": defn["headline"]["inference"], "paid_api_cost": defn["headline"]["paid_api_cost"]},
        "environment": defn["environment"] | {"ollama_version": ollama_version, "backend": manifest["backend"]["kind"]},
        "methodology": methodology,
        "integrity": integrity,
        "domains": domain_names,
        "task_pack": task_pack,
        "models": ordered,
        "caveats": caveats,
        "evidence_links": links,
        "sources": sources,
    }


# --------------------------------------------------------------------------- #
# the pre-Phase-0 historical database
# --------------------------------------------------------------------------- #


def _build_historical(defn: dict, root: Path, checks: _Checks) -> dict:
    src = defn["source"]
    db_path = root / src["database"]
    actual = file_sha256(db_path)
    checks.need(actual == src["sha256"], f"{src['database']} sha256 {actual} is not the recorded {src['sha256']}")
    checks.raise_if_any()  # never read an evidence database whose hash is wrong
    con = sqlite3.connect(f"file:{db_path.resolve()}?mode=ro&immutable=1", uri=True)
    try:
        rows = con.execute(
            "SELECT r.agent, r.task_id, r.task_version, r.idx, r.status, r.created_at, s.functional_pass, s.final_score,"
            " s.voided, s.formula_version FROM runs r JOIN run_scores s ON s.run_id = r.id ORDER BY r.id").fetchall()
        run_count = con.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
    finally:
        con.close()
    checks.equal("historical runs with scores", len(rows), run_count)
    generation = _load(root / src["documented_generation"])["historical_evidence"]
    checks.equal("historical evidence hash", generation["sha256"], src["sha256"])
    changes = {c["task_id"]: c for c in _load(root / src["task_version_changes"])["tasks"]}
    modern_defn = next((d for d in definitions(root) if d["id"] == src["compare_with_release"]), None)
    checks.need(modern_defn is not None, f"unknown comparison release {src['compare_with_release']}")
    modern_tasks = {t["task_id"]: t["task_version"]
                    for t in _load(root / modern_defn["source"]["campaign_dir"] / "manifest.json")["tasks"]}
    task_order = list(modern_tasks)  # the comparison release's pack order
    versions: dict[str, set] = {}
    for agent, task, version, *_ in rows:
        versions.setdefault(task, set()).add(version)
    checks.need(all(len(v) == 1 for v in versions.values()), "a historical task has more than one version")
    checks.equal("historical task ids", sorted(versions), sorted(modern_tasks))
    changed = sorted(t for t in versions if next(iter(versions[t])) != modern_tasks.get(t))
    checks.equal("changed task versions", changed, sorted(changes))
    for task in changed:
        checks.equal(f"{task} old version", next(iter(versions[task])), changes[task]["old_version"])
    checks.need(len(changed) == 18, f"expected 18 changed task definitions, found {len(changed)}")
    formulas = sorted({r[9] for r in rows})
    checks.equal("released_at vs the last recorded run (a historical release's date)", defn["released_at"],
                 max(r[5] for r in rows)[:10])
    by_model: dict[str, list] = {}
    for row in rows:
        by_model.setdefault(row[0], []).append(row)
    models = []
    for tag in sorted(by_model):
        runs = by_model[tag]
        passes = sum(1 for r in runs if r[6])
        status = Counter(r[4] for r in runs)
        task_rows = []
        for task in task_order:
            cell = sorted((r for r in runs if r[1] == task), key=lambda r: r[3])
            checks.equal(f"{tag}|{task} positions", [r[3] for r in cell], list(range(5)))
            task_rows.append({"task_id": task, "task_version": cell[0][2], "evidence": True, "runs": len(cell),
                              "passes": sum(1 for r in cell if r[6]), "timeouts": sum(1 for r in cell if r[4] == "timeout"),
                              "voided": sum(1 for r in cell if r[8])})
        documented = generation["documented_generation"].get(tag)
        prefixes = generation["documented_generation"]["p0_completion_runs"]["digest_prefixes"]
        models.append({
            "id": tag, "display_name": tag, "ranked": False, "rank": None, "state": "RECORDED",
            "identity": {"ollama_tag": tag, "digest": None, "digest_prefix_documented": prefixes.get(tag)},
            "totals": {"runs": len(runs), "passes": passes, "timeouts": status.get("timeout", 0),
                       "voided": sum(1 for r in runs if r[8]),
                       "mean_final_score": math.fsum(r[7] for r in runs) / len(runs)},
            "coverage": {"tasks_with_evidence": len({r[1] for r in runs}), "tasks_total": len(versions)},
            "run_window": {"started_at": min(r[5] for r in runs), "finished_at": max(r[5] for r in runs)},
            # only a model the documentation names gets settings; the P0 group does not enumerate its models
            "generation": ({"group": tag} | {k: documented.get(k) for k in ("temperature", "base_seed", "request_timeout_s",
                                                                               "ollama_version")})
            if documented else None,
            "domains": [],
            "tasks": task_rows,
            "caveat_ids": [],
            "documented_facts": [],
        })
    # listed alphabetically by Ollama tag (sorted(by_model) above): an unranked record gets a neutral order
    p0 = generation["documented_generation"]["p0_completion_runs"]
    groups = [
        {"group": "p0_completion_runs", "temperature": p0["temperature"], "base_seed": p0["base_seed"],
         "request_timeout_s": p0["request_timeout_s"], "ollama_version": p0["ollama_version"], "models": p0["models"]},
        *({"group": tag, "temperature": g["temperature"], "base_seed": g["base_seed"],
           "request_timeout_s": g["request_timeout_s"], "ollama_version": g["ollama_version"], "models": tag}
          for tag, g in generation["documented_generation"].items() if tag not in ("sources", "p0_completion_runs")),
    ]
    task_pack = [{"task_id": t, "task_version": next(iter(versions[t])), "task_digest": None,
                  "current_version": modern_tasks[t], "version_changed_since_pre_phase0": t in changes,
                  "domains": [], "activity": None, "timeout_s": None} for t in task_order]
    model_map = {m["id"]: m for m in models}
    caveats = _caveats(defn, model_map, checks)
    return {
        "campaign_id": None,
        "comparable": False,
        "ranked": False,
        "comparability": defn["comparability"],
        "counts": {"models": len(models), "models_ranked": 0, "tasks": len(versions), "repetitions": 5,
                   "evaluations": None, "runs": len(rows), "runs_per_model": len(rows) // max(len(models), 1)},
        "environment": None,
        "methodology": {"scoring_formula": formulas, "generation_groups": groups,
                        "generation_sources": generation["documented_generation"]["sources"],
                        "not_recorded": defn["not_recorded"],
                        "task_versions_changed": len(changed),
                        "run_window": {"started_at": min(r[5] for r in rows), "finished_at": max(r[5] for r in rows)}},
        "integrity": None,
        "domains": [],
        "task_pack": task_pack,
        "models": models,
        "caveats": caveats,
        "evidence_links": _evidence_links(defn, root, checks),
        "sources": [_source(root, root / p) for p in (src["database"], src["documented_generation"], src["task_version_changes"])],
    }


BUILDERS = {"campaign": _build_campaign, "historical-db": _build_historical}


def build_release(defn: dict, root: Path | None = None) -> dict:
    root = root or paths.REPO
    checks = _Checks(str(defn.get("id", "?")))
    release = _common(defn, checks)
    builder = BUILDERS.get(defn.get("source", {}).get("kind"))
    checks.need(builder is not None, f"unknown source kind {defn.get('source', {}).get('kind')!r}")
    checks.raise_if_any()
    try:
        release |= builder(defn, root, checks)
    except (KeyError, ValueError, TypeError, IndexError) as exc:
        checks.raise_if_any()
        raise ReleaseDataError(f"release {defn.get('id')}: malformed definition or evidence ({exc!r})") from None
    kind = defn["source"]["kind"]
    checks.need((release["status"] == "HISTORICAL") == (kind == "historical-db"),
                "a historical-db release must have status HISTORICAL, and only it")
    checks.need(release["status"] != "OFFICIAL" or (kind == "campaign" and release["ranked"]
                                                    and release["integrity"]["official"]),
                "an OFFICIAL release must be a ranked campaign release whose leaderboard is OFFICIAL")
    release["sources"].insert(0, _source(root, root / "campaigns" / "releases" / f"{defn['id']}.json"))
    checks.raise_if_any()
    return release


def render(release: dict) -> str:
    return json.dumps(release, indent=2, ensure_ascii=False) + "\n"


def output_path(release_id: str, root: Path | None = None) -> Path:
    return (root or paths.REPO) / "web" / "src" / "data" / "benchmark-releases" / f"{release_id}.json"


def generate(root: Path | None = None, *, check: bool = False, release_ids: list[str] | None = None) -> list[str]:
    """Write (or, with ``check``, compare) every release dataset. Returns messages;
    raises ReleaseDataError on inconsistent evidence or, in check mode, drift."""
    root = root or paths.REPO
    defs = definitions(root)
    if not defs:
        raise ReleaseDataError("no release definitions under campaigns/releases/")
    known = {d.get("id") for d in defs}
    unknown = sorted(set(release_ids or ()) - known)
    if unknown:
        raise ReleaseDataError(f"unknown release id(s) {unknown}; known: {sorted(known)}")
    messages, drift = [], []
    if not release_ids:  # a dataset without a definition would ship unverifiable numbers
        orphans = sorted(_rel(root, p) for p in output_path("x", root).parent.glob("*.json")
                         if p.stem not in known)
        if orphans:
            raise ReleaseDataError("dataset(s) without a release definition: " + ", ".join(orphans))
    for defn in defs:
        if release_ids and defn["id"] not in release_ids:
            continue
        text = render(build_release(defn, root))
        target = output_path(defn["id"], root)
        if check:
            current = target.read_text(encoding="utf-8") if target.exists() else None
            if current != text:
                drift.append(_rel(root, target))
            else:
                messages.append(f"{_rel(root, target)} matches its sources")
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text, encoding="utf-8")
            messages.append(f"wrote {_rel(root, target)}")
    if drift:
        raise ReleaseDataError("release dataset(s) out of date with their sources (run "
                               "`PYTHONPATH=campaigns python3 -m afa_campaign release-data`): " + ", ".join(drift))
    return messages
