"""The frozen campaign plan: build, load, validate, derive.

A manifest pins everything a campaign's evidence depends on: the runtime release,
the backend, the generation settings, the model roster, and every task's current
version AND content digest (computed with the runtime's own ``task_snapshot``, so
the digests are exactly what each evaluation snapshot will record). It also
fixes the plan: one cell per (model, task), each executed as ONE fresh evaluation
with ``repetitions`` positions, split into Phase A (cells that passed at least
once on a task version ORACLE later strengthened) and Phase B (everything else).

Two kinds of plan exist. ``historical-replication`` (the original six-model
``phase0-post-integrity-v1`` plan, now cancelled) splits cells into Phase A / B by
historical prior passes. ``sequential-local`` (``phase0-modern-local-v1``) runs
one MODEL per phase (M1, M2, ...), in order, under tight local storage: each
roster entry pins the model's exact registry identity (manifest digest,
family, parameter size, quantization, download size) and may be optional.

The manifest is immutable once a campaign has launched: the ledger records its
sha256 and every tool refuses a manifest whose hash no longer matches.
"""

from __future__ import annotations

import copy
import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import paths

SCHEMA_VERSION = 1
CAMPAIGN_ID = "phase0-post-integrity-v1"
ROSTER = (
    "qwen2.5-coder:7b",
    "qwen2.5-coder:3b",
    "deepseek-coder:6.7b",
    "llama3.2:latest",
    "gemma2:2b",
    "qwen3.5:9b",
)
REAL_BACKENDS = ("ollama", "openai_compat")
PHASES = ("A", "B")
KIND_HISTORICAL = "historical-replication"
KIND_SEQUENTIAL = "sequential-local"

MODERN_CAMPAIGN_ID = "phase0-modern-local-v1"
# The modern local cohort, in benchmark order (increasing local resource cost).
# Identities were resolved from the Ollama registry BEFORE any download
# (registry manifest sha256 = the digest Ollama reports locally; layer sizes;
# the config blob's family / parameter size / quantization). Never substituted:
# a pulled model whose digest differs from its pin is refused.
MODERN_LOCAL_ROSTER = (
    {"phase": "M1", "model": "qwen3.5:9b", "logical_name": "Qwen 3.5 9B", "optional": False,
     "expected_identity": {"digest": "6488c96fa5faab64bb65cbd30d4289e20e6130ef535a93ef9a49f42eda893ea7",
                           "download_bytes": 6594474236, "format": "gguf", "family": "qwen35",
                           "parameter_size": "9.7B", "quantization": "Q4_K_M"}},
    {"phase": "M2", "model": "gpt-oss:20b", "logical_name": "gpt-oss 20B", "optional": False,
     "expected_identity": {"digest": "17052f91a42e97930aa6e28a6c6c06a983e6a58dbb00434885a0cf5313e376f7",
                           "download_bytes": 13793440755, "format": "gguf", "family": "gptoss",
                           "parameter_size": "20.9B", "quantization": "MXFP4"}},
    {"phase": "M3", "model": "devstral-small-2:24b", "logical_name": "Devstral Small 2 24B", "optional": False,
     "expected_identity": {"digest": "24277f07f62db8f9cb68e9dfc679ea1818a7fbac47a50eff0a701d3f645b63c8",
                           "download_bytes": 15177373679, "format": "gguf", "family": "mistral3",
                           "parameter_size": "24.0B", "quantization": "Q4_K_M"}},
    {"phase": "M4", "model": "qwen3-coder:30b", "logical_name": "Qwen3-Coder 30B-A3B", "optional": False,
     "expected_identity": {"digest": "06c1097efce0431c2045fe7b2e5108366e43bee1b4603a7aded8f21689e90bca",
                           "download_bytes": 18556700222, "format": "gguf", "family": "qwen3moe",
                           "parameter_size": "30.5B", "quantization": "Q4_K_M"}},
    {"phase": "M5", "model": "qwen3.6:27b", "logical_name": "Qwen3.6 27B", "optional": True,
     "expected_identity": {"digest": "9d5803d493a991af27b9441c098aa56f2ed7bbd260877f075ec09b575c049bc3",
                           "download_bytes": 17769076719, "format": "gguf", "family": "qwen35",
                           "parameter_size": "27.3B", "quantization": "Q4_K_M"}},
)
# Classifications that take a roster model OUT of the expected cohort (it is
# listed separately and never ranked, never counted as a zero-score model).
MODEL_CLASSIFICATIONS = ("LOCAL_RESOURCE_LIMIT", "LOCAL_RUNTIME_UNSUPPORTED", "NOT_BENCHMARKED")


def plan_kind(data: dict) -> str:
    return data.get("kind") or KIND_HISTORICAL


def phases_of(data: dict) -> list[str]:
    if plan_kind(data) == KIND_SEQUENTIAL:
        return [entry["phase"] for entry in data.get("roster") or []]
    return list(PHASES)


def normalize_digest(value) -> str | None:
    """Ollama reports digests as plain hex; accept an optional 'sha256:' prefix."""
    if not isinstance(value, str) or not value:
        return None
    return value.split(":", 1)[1] if value.startswith("sha256:") else value


# What the repository DOCUMENTS about how the historical runs were generated
# (README.md "Evaluation provenance" and the Sept-17 qwen3.5:9b report). Not
# persisted per run; recorded here so every comparison discloses differences
# instead of implying identical conditions. Unknowns stay explicitly unknown.
HISTORICAL_GENERATION = {
    "sources": ["README.md, section 'Evaluation provenance'",
                "reports/qwen3.5-9b-evaluation-2026-09-17.md"],
    "p0_completion_runs": {
        "temperature": 0.8, "base_seed": 42, "ollama_version": "0.17.4",
        "models": "not enumerated by the README (it records digests for qwen2.5-coder:7b and llama3.2:latest)",
        "evaluation_path": ("the README's documented real-agent path, examples/eval_persist.py: job-less rows, "
                            "OllamaAgent seed = base_seed + a call counter running across the whole pack; the "
                            "script hard-codes temperature 0.8 and base seed 42"),
        "request_timeout_s": None,
        "digest_prefixes": {"qwen2.5-coder:7b": "dae161e27b0e", "llama3.2:latest": "a80c4f17acd5"},
    },
    "qwen3.5:9b": {
        "temperature": 0.6, "base_seed": 42, "request_timeout_s": 180, "ollama_version": None, "digest": None,
        "evaluation_path": ("a local app evaluation job eb54c065c0b84d099a82570f4aeee83c (runs 1101-1220); the "
                            "job linkage is not preserved in reports/runs.sqlite and that app version's "
                            "per-trial seed policy is not documented"),
        "note": "temperature differs from this campaign's 0.8",
    },
}


class ManifestError(ValueError):
    """The manifest is malformed, inconsistent, or does not match the task pack."""


@dataclass(frozen=True)
class Cell:
    model: str
    task_id: str
    phase: str

    @property
    def key(self) -> str:
        return cell_key(self.model, self.task_id)


def cell_key(model: str, task_id: str) -> str:
    return f"{model}|{task_id}"


def canonical_sha256(data: Any) -> str:
    text = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def evidence_sha256(path: str | Path) -> str | None:
    """The historical evidence DB's guard hash (None when the file is absent).

    The DB is in WAL mode: an uncheckpointed ``-wal`` beside it would change what
    a non-immutable reader sees without changing the main file, so a non-empty
    WAL is folded into the value and never matches the frozen hash."""
    target = Path(path)
    if not target.exists():
        return None
    sha = file_sha256(target)
    wal = target.with_name(target.name + "-wal")
    if wal.exists() and wal.stat().st_size > 0:
        return f"{sha}+uncheckpointed-wal:{file_sha256(wal)}"
    return sha


def open_evidence_store(path: str | Path | None = None):
    """A read-only raw store over the historical evidence DB, opened IMMUTABLE:
    SQLite then reads exactly the main file (whose hash is guarded), ignores any
    WAL, and creates no -wal/-shm side files. ``close()`` releases it."""
    import sqlite3

    import afa_runner as afa

    target = Path(path or paths.EVIDENCE_DB).expanduser().resolve()
    if not target.exists():
        raise FileNotFoundError(f"historical evidence DB not found: {target}")
    conn = sqlite3.connect(target.as_uri() + "?mode=ro&immutable=1", uri=True)
    conn.text_factory = lambda raw: raw.decode("utf-8", "replace")

    class _EvidenceStore(afa.SqliteRunStore):
        def close(self) -> None:
            try:
                super().close()
            finally:
                conn.close()

    return _EvidenceStore(connection=conn)


# --------------------------------------------------------------------------- #
# Building
# --------------------------------------------------------------------------- #


def _historical_cells(models: list[str], task_ids: list[str]) -> dict[tuple[str, str], dict]:
    """Per (model, task): versions, run counts and passes in the pre-Phase-0 DB.

    Read-only; ``valid`` excludes infrastructure-voided runs exactly as the
    kernel does, ``passes`` counts functional passes among valid runs.
    """
    from afa_kernel.types import RunStatus

    out: dict[tuple[str, str], dict] = {}
    store = open_evidence_store()
    try:
        for model in models:
            for task_id in task_ids:
                records = store.load_runs(task_id=task_id, agent=model)
                valid = [r for r in records if r.status is not RunStatus.INFRA_FAILURE]
                out[(model, task_id)] = {
                    "versions": sorted({r.task_version for r in records}),
                    "runs": len(records),
                    "valid": len(valid),
                    "passes": sum(1 for r in valid if r.score.functional_pass),
                }
    finally:
        store.close()
    return out


def build_manifest(
    *,
    created_at: str,
    runtime_tag: str,
    runtime_commit: str,
    campaign_id: str = CAMPAIGN_ID,
    models: tuple[str, ...] | list[str] = ROSTER,
    repetitions: int = 5,
    temperature: float = 0.8,
    base_seed: int = 42,
    request_timeout_s: int = 180,
    backend_kind: str = "ollama",
    backend_base_url: str = "http://127.0.0.1:11434",
    campaign_db: str = "reports/phase0-campaign.sqlite",
    runtime_dir: str = "reports/phase0-campaign",
    api_url: str = "http://127.0.0.1:8000",
) -> dict:
    """Build the campaign manifest from the checked-out task pack and evidence.

    Fails (ManifestError) if the task pack, the historical evidence and ORACLE's
    remediation manifest disagree about versions or prior passes: the plan must
    be derived from facts that agree, never from one source silently.
    """
    from afa_api import jobs, store_load

    models = list(models)
    task_manifest = json.loads(paths.TASK_MANIFEST.read_text())
    task_ids = [item["id"] for item in task_manifest]
    _, current_versions, _, _, _ = store_load._build_manifest_meta(paths.TASK_MANIFEST)
    remediation = json.loads(paths.REMEDIATION_MANIFEST.read_text())
    bumped = {t["task_id"]: t for t in remediation["tasks"]}
    historical = _historical_cells(models, task_ids)
    problems: list[str] = []

    tasks: list[dict] = []
    for item in task_manifest:
        task_id = item["id"]
        snap = jobs.task_snapshot(task_id)
        spec = json.loads((paths.TASKS_DIR / task_id / "task.json").read_text())
        if snap["task_version"] != current_versions[task_id]:
            problems.append(
                f"{task_id}: task.json version {snap['task_version']} != projection "
                f"current version {current_versions[task_id]}"
            )
        versions = {v for m in models for v in historical[(m, task_id)]["versions"]}
        historical_version = sorted(versions)[0] if len(versions) == 1 else None
        if len(versions) > 1:
            problems.append(f"{task_id}: historical runs span versions {sorted(versions)}")
        remediation_entry = bumped.get(task_id)
        if remediation_entry is not None:
            if remediation_entry["new_version"] != snap["task_version"]:
                problems.append(
                    f"{task_id}: remediation new_version {remediation_entry['new_version']} "
                    f"!= current {snap['task_version']}"
                )
            if historical_version != remediation_entry["old_version"]:
                problems.append(
                    f"{task_id}: historical version {historical_version} != remediation "
                    f"old_version {remediation_entry['old_version']}"
                )
        elif historical_version not in (None, snap["task_version"]):
            problems.append(
                f"{task_id}: not remediated but historical version {historical_version} "
                f"!= current {snap['task_version']}"
            )
        tasks.append(
            {
                "task_id": task_id,
                "task_version": snap["task_version"],
                "task_digest": snap["task_digest"],
                "domains": [[str(d), float(w)] for d, w in item.get("domains", [])],
                "activity": item.get("activity"),
                "timeout_s": spec.get("timeout_s"),
                "historical_version": historical_version,
                "version_changed_since_historical": (
                    historical_version is not None and historical_version != snap["task_version"]
                ),
            }
        )

    prior_pass: dict[tuple[str, str], dict] = {}
    for task_id, entry in bumped.items():
        for per_model in entry["known_affected_runs"]["per_model"]:
            if per_model["model"] in models and per_model["passed"] > 0:
                prior_pass[(per_model["model"], task_id)] = per_model
    for (model, task_id), per_model in prior_pass.items():
        hist = historical[(model, task_id)]
        if (hist["runs"], hist["passes"]) != (per_model["n"], per_model["passed"]):
            problems.append(
                f"{model}|{task_id}: remediation says {per_model['passed']}/{per_model['n']} "
                f"passed, historical DB says {hist['passes']}/{hist['runs']}"
            )
    if problems:
        raise ManifestError("inconsistent inputs:\n  " + "\n  ".join(problems))

    cells: list[dict] = []
    for phase in PHASES:
        for model in models:
            for task in tasks:
                key = (model, task["task_id"])
                if (phase == "A") != (key in prior_pass):
                    continue
                hist = historical[key]
                cells.append(
                    {
                        "model": model,
                        "task_id": task["task_id"],
                        "phase": phase,
                        "prior_pass": key in prior_pass,
                        "historical_version": task["historical_version"],
                        "historical_runs": hist["runs"],
                        "historical_valid": hist["valid"],
                        "historical_passes": hist["passes"],
                    }
                )

    data = {
        "schema_version": SCHEMA_VERSION,
        "campaign_id": campaign_id,
        "title": "Post-Phase-0 trusted baseline: fresh real-backend cohort",
        "created_at": created_at,
        "purpose": (
            "A completely fresh post-Phase-0 cohort executed through the ATLAS "
            "evaluation lifecycle on the promoted Phase-0 release. The 720 "
            "historical runs in reports/runs.sqlite are the PRE-Phase-0 baseline "
            "and are never substituted for, pooled with, or overwritten by this "
            "cohort."
        ),
        "code": {
            "runtime_release_tag": runtime_tag,
            "runtime_release_commit": runtime_commit,
            "runtime_paths": list(paths.RUNTIME_PATHS),
            "rule": (
                "the launcher refuses to run when the runtime paths differ from the "
                "release tag or have uncommitted changes"
            ),
        },
        "historical_evidence": {
            "path": "reports/runs.sqlite",
            "sha256": evidence_sha256(paths.EVIDENCE_DB),
            "role": "PRE-Phase-0 baseline; read-only; never a campaign write target",
            "documented_generation": HISTORICAL_GENERATION,
        },
        "remediation_manifest": {
            "path": paths.display(paths.REMEDIATION_MANIFEST),
            "sha256": file_sha256(paths.REMEDIATION_MANIFEST),
        },
        "backend": {"kind": backend_kind, "base_url": backend_base_url},
        "mode": "fresh",
        "repetitions": repetitions,
        "generation": {
            "temperature": temperature,
            "base_seed": base_seed,
            "request_timeout_s": request_timeout_s,
            "seed_policy": (
                "ATLAS per-trial seed: the worker sets seed = base_seed + idx for "
                "repeat position idx (0..repetitions-1) before each trial "
                "(set_run_seed), so position idx of every (model, task) cell uses "
                "the same seed and a resumed position re-uses its original seed"
            ),
        },
        "evaluation_granularity": (
            "one fresh evaluation per (model, task) cell: tasks=[task_id], "
            "repeats=repetitions, name=<evaluation_name_prefix>:<phase>:<model>|<task_id>"
        ),
        "evaluation_name_prefix": f"campaign:{campaign_id}",
        "evidence_scope": "real",
        "models": models,
        "tasks": tasks,
        "cells": cells,
        "runtime": {
            "campaign_db": campaign_db,
            "db_strategy": "clean",
            "runtime_dir": runtime_dir,
            "ledger": f"{runtime_dir}/ledger.json",
            "outputs": f"{runtime_dir}/outputs",
            "api_url": api_url,
        },
    }
    data["expected"] = expected_counts(data)
    validate(data)
    return data


def _pinned_tasks() -> list[dict]:
    """Every task of the checked-out pack, pinned to its current version and
    content digest exactly as an evaluation snapshot records them."""
    from afa_api import jobs, store_load

    task_manifest = json.loads(paths.TASK_MANIFEST.read_text())
    _, current_versions, _, _, _ = store_load._build_manifest_meta(paths.TASK_MANIFEST)
    problems, tasks = [], []
    for item in task_manifest:
        task_id = item["id"]
        snap = jobs.task_snapshot(task_id)
        spec = json.loads((paths.TASKS_DIR / task_id / "task.json").read_text())
        if snap["task_version"] != current_versions[task_id]:
            problems.append(f"{task_id}: task.json version {snap['task_version']} != projection "
                            f"current version {current_versions[task_id]}")
        tasks.append({
            "task_id": task_id,
            "task_version": snap["task_version"],
            "task_digest": snap["task_digest"],
            "domains": [[str(d), float(w)] for d, w in item.get("domains", [])],
            "activity": item.get("activity"),
            "timeout_s": spec.get("timeout_s"),
        })
    if problems:
        raise ManifestError("inconsistent task pack:\n  " + "\n  ".join(problems))
    return tasks


def build_modern_manifest(
    *,
    created_at: str,
    runtime_tag: str,
    runtime_commit: str,
    campaign_id: str = MODERN_CAMPAIGN_ID,
    roster: tuple[dict, ...] | list[dict] = MODERN_LOCAL_ROSTER,
    repetitions: int = 5,
    temperature: float = 0.8,
    base_seed: int = 42,
    request_timeout_s: int = 180,
    backend_base_url: str = "http://127.0.0.1:11434",
    campaign_db: str = "reports/phase0-modern-local.sqlite",
    runtime_dir: str = "reports/phase0-modern-local",
    api_url: str = "http://127.0.0.1:8000",
    ollama_server_version: str = "0.31.1",
    minimum_ranked_models: int = 3,
) -> dict:
    """The sequential-by-model local campaign: one phase per roster model, every
    model x every task x ``repetitions``, with one frozen task pack and one
    generation setting for all models."""
    roster = [copy.deepcopy(entry) for entry in roster]
    tasks = _pinned_tasks()
    models = [entry["model"] for entry in roster]
    cells = [{"model": entry["model"], "task_id": task["task_id"], "phase": entry["phase"]}
             for entry in roster for task in tasks]
    data = {
        "schema_version": SCHEMA_VERSION,
        "kind": KIND_SEQUENTIAL,
        "campaign_id": campaign_id,
        "title": "AgentForge Modern Local Benchmark: sequential local cohort",
        "created_at": created_at,
        "purpose": (
            "A new post-Phase-0 baseline of modern, locally runnable, zero-cost coding models, "
            "benchmarked ONE MODEL AT A TIME under tight local storage (install or reuse one "
            "target, smoke it, run its 24 tasks x 5 fresh repetitions, validate and freeze its "
            "receipt, then its weights may be removed). Evidence lives in the campaign database "
            "and ledger, never in the model files. Not directly comparable with the historical "
            "pre-Phase-0 runs in reports/runs.sqlite (older task versions, other runtime)."
        ),
        "code": {
            "runtime_release_tag": runtime_tag,
            "runtime_release_commit": runtime_commit,
            "runtime_paths": list(paths.RUNTIME_PATHS),
            "rule": ("the launcher refuses to run when the runtime paths differ from the release tag "
                     "or have uncommitted changes"),
        },
        "historical_evidence": {
            "path": "reports/runs.sqlite",
            "sha256": evidence_sha256(paths.EVIDENCE_DB),
            "role": "PRE-Phase-0 baseline; read-only; never a campaign write target; not compared as "
                    "the same experiment",
        },
        "backend": {"kind": "ollama", "base_url": backend_base_url},
        "mode": "fresh",
        "repetitions": repetitions,
        "generation": {
            "temperature": temperature,
            "base_seed": base_seed,
            "request_timeout_s": request_timeout_s,
            "seed_policy": (
                "ATLAS per-trial seed: the worker sets seed = base_seed + idx for repeat position idx "
                "(0..repetitions-1) before each trial (set_run_seed), so position idx of every "
                "(model, task) cell uses the same seed and a resumed position re-uses its original seed"
            ),
            "request": ("the Phase-0 runtime's OllamaAgent calls /api/generate with only temperature and "
                        "seed; every other inference setting (context length, thinking) is the Ollama "
                        "server's default for that model, identical for every model of the campaign"),
        },
        "evaluation_granularity": (
            "one fresh evaluation per (model, task) cell: tasks=[task_id], repeats=repetitions, "
            "name=<evaluation_name_prefix>:<phase>:<model>|<task_id>; phase = the model's roster phase"
        ),
        "evaluation_name_prefix": f"campaign:{campaign_id}",
        "evidence_scope": "real",
        "execution": {
            "order": [entry["phase"] for entry in roster],
            "one_model_at_a_time": True,
            "ollama_server_version": ollama_server_version,
            "minimum_ranked_models": minimum_ranked_models,
            "official_rule": (
                "the leaderboard is OFFICIAL only when every roster model is either COMPLETE (24 cells, 120 "
                "accepted runs) or explicitly classified, and at least minimum_ranked_models models are COMPLETE"),
            "storage_policy": (
                "reuse an installed target; otherwise free space by removing authorized model weights "
                "(a completed target whose receipt is accepted first, then unused Ollama models, then "
                "MLX weights) and pull ONLY that target; never delete campaign evidence"
            ),
            "smoke": {"tasks": ["fix-binary-search", "async-batched", "sanitize-filename",
                                "refactor-order-validation"], "repetitions": 1},
        },
        "roster": roster,
        "models": models,
        "tasks": tasks,
        "cells": cells,
        "runtime": {
            "campaign_db": campaign_db,
            "db_strategy": "clean",
            "runtime_dir": runtime_dir,
            "ledger": f"{runtime_dir}/ledger.json",
            "outputs": f"{runtime_dir}/outputs",
            "receipts": f"{runtime_dir}/receipts",
            "inventories": f"{runtime_dir}/inventories",
            "smoke_dir": f"{runtime_dir}/smoke",
            "api_url": api_url,
        },
    }
    data["expected"] = expected_counts(data)
    validate(data)
    return data


def expected_counts(data: dict) -> dict:
    reps = int(data["repetitions"])
    if plan_kind(data) == KIND_SEQUENTIAL:
        roster = data.get("roster") or []
        per_model = len(data["tasks"]) * reps
        required = [e for e in roster if not e.get("optional")]
        return {
            "models": len(data["models"]),
            "required_models": len(required),
            "optional_models": len(roster) - len(required),
            "tasks": len(data["tasks"]),
            "cells": len(data["cells"]),
            "runs_per_cell": reps,
            "runs_per_model": per_model,
            "total_runs": len(data["cells"]) * reps,
            "minimum_runs": len(required) * per_model,
            "phases": {e["phase"]: {"model": e["model"],
                                     "cells": sum(1 for c in data["cells"] if c["phase"] == e["phase"]),
                                     "runs": sum(1 for c in data["cells"] if c["phase"] == e["phase"]) * reps}
                       for e in roster},
        }
    by_phase = {p: [c for c in data["cells"] if c["phase"] == p] for p in PHASES}
    return {
        "models": len(data["models"]),
        "tasks": len(data["tasks"]),
        "cells": len(data["cells"]),
        "runs_per_cell": reps,
        "runs_per_model": len(data["tasks"]) * reps,
        "total_runs": len(data["cells"]) * reps,
        "phase_A_cells": len(by_phase["A"]),
        "phase_A_runs": len(by_phase["A"]) * reps,
        "phase_B_cells": len(by_phase["B"]),
        "phase_B_runs": len(by_phase["B"]) * reps,
    }


def derive_subset(
    data: dict,
    *,
    campaign_id: str,
    models: list[str],
    task_ids: list[str],
    repetitions: int,
    campaign_db: str,
    runtime_dir: str,
    api_url: str | None = None,
    purpose: str,
) -> dict:
    """A smaller campaign with identical pins (dry runs, rehearsals).

    Every selected cell becomes a Phase-A cell of the derived campaign; the task
    pins, backend and generation settings are copied unchanged.
    """
    unknown_models = [m for m in models if m not in data["models"]]
    known_tasks = {t["task_id"] for t in data["tasks"]}
    unknown_tasks = [t for t in task_ids if t not in known_tasks]
    if unknown_models or unknown_tasks:
        raise ManifestError(f"unknown models {unknown_models} / tasks {unknown_tasks}")
    derived = copy.deepcopy(data)
    derived["campaign_id"] = campaign_id
    derived["title"] = f"Derived subset of {data['campaign_id']}"
    derived["purpose"] = purpose
    derived["derived_from"] = {"campaign_id": data["campaign_id"], "sha256": canonical_sha256(data)}
    derived["evaluation_name_prefix"] = f"campaign:{campaign_id}"
    derived["models"] = [m for m in data["models"] if m in models]
    derived["tasks"] = [t for t in data["tasks"] if t["task_id"] in task_ids]
    derived["repetitions"] = repetitions
    sequential = plan_kind(data) == KIND_SEQUENTIAL
    if sequential:
        # a sequential plan keeps each model's phase (one model per phase); a derived
        # plan (smoke, rehearsal) of only optional models makes them required for itself
        derived["roster"] = [copy.deepcopy(e) for e in data["roster"] if e["model"] in models]
        if derived["roster"] and all(e.get("optional") for e in derived["roster"]):
            for e in derived["roster"]:
                e["optional"] = False
        derived["execution"] = {**data.get("execution", {}),
                                "order": [e["phase"] for e in derived["roster"]]}
    derived["cells"] = [
        {**cell, "phase": cell["phase"] if sequential else "A"}
        for cell in data["cells"]
        if cell["model"] in models and cell["task_id"] in task_ids
    ]
    derived["cells"].sort(
        key=lambda c: (derived["models"].index(c["model"]),
                       [t["task_id"] for t in derived["tasks"]].index(c["task_id"]))
    )
    derived["runtime"] = {
        **data["runtime"],
        "campaign_db": campaign_db,
        "runtime_dir": runtime_dir,
        "ledger": f"{runtime_dir}/ledger.json",
        "outputs": f"{runtime_dir}/outputs",
        **({"receipts": f"{runtime_dir}/receipts", "inventories": f"{runtime_dir}/inventories",
            "smoke_dir": f"{runtime_dir}/smoke"} if sequential else {}),
        **({"api_url": api_url} if api_url else {}),
    }
    derived["expected"] = expected_counts(derived)
    validate(derived)
    return derived


# --------------------------------------------------------------------------- #
# Validation and access
# --------------------------------------------------------------------------- #


def validate(data: dict) -> None:
    """Structural and internal-consistency validation (no filesystem access)."""
    problems: list[str] = []

    def need(cond: bool, message: str) -> None:
        if not cond:
            problems.append(message)

    need(data.get("schema_version") == SCHEMA_VERSION, "unsupported schema_version")
    need(isinstance(data.get("campaign_id"), str) and bool(data.get("campaign_id")), "campaign_id missing")
    need(data.get("evaluation_name_prefix") == f"campaign:{data.get('campaign_id')}",
         "evaluation_name_prefix must be exactly 'campaign:<campaign_id>' (a campaign never names "
         "its evaluations under another campaign)")
    backend = data.get("backend") or {}
    need(backend.get("kind") in REAL_BACKENDS,
         f"backend.kind must be a real backend {REAL_BACKENDS} (mock is never campaign evidence)")
    need(isinstance(backend.get("base_url"), str) and backend.get("base_url", "").startswith("http"),
         "backend.base_url must be an explicit http(s) URL")
    need(data.get("mode") == "fresh", "mode must be 'fresh'")
    need(data.get("evidence_scope") == "real", "evidence_scope must be 'real'")
    reps = data.get("repetitions")
    need(isinstance(reps, int) and not isinstance(reps, bool) and 1 <= reps <= 100,
         "repetitions must be an int in 1..100")
    gen = data.get("generation") or {}
    for key, kind in (("temperature", (int, float)), ("base_seed", int), ("request_timeout_s", int)):
        need(isinstance(gen.get(key), kind) and not isinstance(gen.get(key), bool),
             f"generation.{key} missing or mistyped")
    models = data.get("models") or []
    need(len(models) == len(set(models)) and all(isinstance(m, str) and m.strip() for m in models),
         "models must be unique non-empty names")
    tasks = data.get("tasks") or []
    task_ids = [t.get("task_id") for t in tasks]
    need(len(task_ids) == len(set(task_ids)) and all(task_ids), "task ids must be unique")
    for task in tasks:
        need(isinstance(task.get("task_version"), str) and task.get("task_version"),
             f"{task.get('task_id')}: task_version missing")
        need(str(task.get("task_digest", "")).startswith("sha256:"),
             f"{task.get('task_id')}: task_digest missing")
    cells = data.get("cells") or []
    keys = [(c.get("model"), c.get("task_id")) for c in cells]
    need(len(keys) == len(set(keys)), "duplicate cells")
    need(set(keys) == {(m, t) for m in models for t in task_ids},
         "cells must cover exactly models x tasks")
    need(plan_kind(data) in (KIND_HISTORICAL, KIND_SEQUENTIAL), f"unknown manifest kind {plan_kind(data)!r}")
    if plan_kind(data) == KIND_SEQUENTIAL:
        roster = data.get("roster") or []
        need(isinstance(roster, list) and roster and all(isinstance(e, dict) for e in roster),
             "a sequential plan needs a roster")
        roster = [e for e in roster if isinstance(e, dict)] if isinstance(roster, list) else []
        phases = [e.get("phase") for e in roster]
        need([e.get("model") for e in roster] == models, "roster models must equal models, in order")
        need(len(phases) == len(set(phases)) and all(isinstance(p, str) and p for p in phases),
             "every roster model needs its own phase")
        need(any(not e.get("optional") for e in roster), "at least one roster model must be required")
        for entry in roster:
            ident = entry.get("expected_identity") or {}
            digest = normalize_digest(ident.get("digest"))
            need(isinstance(digest, str) and len(digest) == 64 and all(ch in "0123456789abcdef" for ch in digest),
                 f"{entry.get('model')}: expected_identity.digest must be a 64-hex sha256")
            need(isinstance(ident.get("download_bytes"), int) and ident.get("download_bytes", 0) > 0,
                 f"{entry.get('model')}: expected_identity.download_bytes missing")
            need(isinstance(entry.get("logical_name"), str) and entry.get("logical_name"),
                 f"{entry.get('model')}: logical_name missing")
            need(isinstance(entry.get("optional"), bool), f"{entry.get('model')}: optional must be a bool")
        phase_of = {e.get("model"): e.get("phase") for e in roster}
        need(all(c.get("phase") == phase_of.get(c.get("model")) for c in cells),
             "every cell's phase must be its model's roster phase")
        need(backend.get("kind") == "ollama", "a sequential local plan runs on the local ollama backend")
        execution = data.get("execution") or {}
        need(execution.get("ollama_server_version") is None or isinstance(execution.get("ollama_server_version"), str),
             "execution.ollama_server_version must be a string")
        floor = execution.get("minimum_ranked_models", 1)
        need(isinstance(floor, int) and not isinstance(floor, bool) and floor >= 1,
             "execution.minimum_ranked_models must be an int >= 1")
    else:
        need(all(c.get("phase") in PHASES for c in cells), "cell phase must be A or B")
    for name in ("campaign_db", "ledger", "outputs", "runtime_dir"):
        need(isinstance((data.get("runtime") or {}).get(name), str), f"runtime.{name} missing")
    db_path = str((data.get("runtime") or {}).get("campaign_db", ""))
    need(Path(db_path).name != "runs.sqlite", "campaign_db must never be the evidence DB")
    if not problems and data.get("expected") is not None:
        need(data["expected"] == expected_counts(data), "expected counts do not match the plan")
    if problems:
        raise ManifestError("invalid campaign manifest:\n  " + "\n  ".join(problems))


class Manifest:
    """A loaded, validated manifest with convenient accessors."""

    def __init__(self, data: dict, path: Path | None = None) -> None:
        validate(data)
        self.data = data
        self.path = path
        self.sha256 = canonical_sha256(data)
        self.task_by_id = {t["task_id"]: t for t in data["tasks"]}

    @classmethod
    def load(cls, path: str | Path = paths.DEFAULT_MANIFEST) -> "Manifest":
        resolved = paths.resolve(path)
        try:
            data = json.loads(resolved.read_text())
        except (OSError, ValueError) as exc:
            raise ManifestError(f"cannot read manifest {resolved}: {exc}") from exc
        return cls(data, resolved)

    # identity
    @property
    def campaign_id(self) -> str:
        return self.data["campaign_id"]

    @property
    def models(self) -> list[str]:
        return list(self.data["models"])

    @property
    def task_ids(self) -> list[str]:
        return [t["task_id"] for t in self.data["tasks"]]

    @property
    def repetitions(self) -> int:
        return int(self.data["repetitions"])

    @property
    def backend(self) -> dict:
        return dict(self.data["backend"])

    @property
    def generation(self) -> dict:
        return dict(self.data["generation"])

    @property
    def expected(self) -> dict:
        return expected_counts(self.data)

    @property
    def kind(self) -> str:
        return plan_kind(self.data)

    @property
    def is_sequential(self) -> bool:
        return self.kind == KIND_SEQUENTIAL

    @property
    def phases(self) -> list[str]:
        return phases_of(self.data)

    def roster_entry(self, model: str) -> dict:
        for entry in self.data.get("roster") or []:
            if entry["model"] == model:
                return entry
        raise KeyError(model)

    def phase_entry(self, phase: str) -> dict:
        for entry in self.data.get("roster") or []:
            if entry["phase"] == phase:
                return entry
        raise KeyError(phase)

    def pinned_digests(self) -> dict[str, str]:
        """{model: expected digest} of a sequential plan (empty otherwise)."""
        return {e["model"]: normalize_digest(e["expected_identity"]["digest"])
                for e in self.data.get("roster") or []}

    def runtime_subdir(self, name: str) -> Path:
        return paths.resolve(self.data["runtime"].get(name) or f"{self.data['runtime']['runtime_dir']}/{name}")

    # runtime locations
    def db_path(self) -> Path:
        return paths.resolve(self.data["runtime"]["campaign_db"])

    def ledger_path(self) -> Path:
        return paths.resolve(self.data["runtime"]["ledger"])

    def outputs_dir(self) -> Path:
        return paths.resolve(self.data["runtime"]["outputs"])

    def runtime_dir(self) -> Path:
        return paths.resolve(self.data["runtime"]["runtime_dir"])

    @property
    def api_url(self) -> str:
        return self.data["runtime"]["api_url"]

    # the plan
    def cells(self, phase: str | None = None) -> list[Cell]:
        return [
            Cell(c["model"], c["task_id"], c["phase"])
            for c in self.data["cells"]
            if phase in (None, "all") or c["phase"] == phase
        ]

    def cell_meta(self, key: str) -> dict:
        for cell in self.data["cells"]:
            if cell_key(cell["model"], cell["task_id"]) == key:
                return cell
        raise KeyError(key)

    def evaluation_name(self, cell: Cell) -> str:
        return f"{self.data['evaluation_name_prefix']}:{cell.phase}:{cell.key}"

    def job_body(self, cell: Cell) -> dict:
        """The exact POST /api/v1/jobs body for one campaign cell."""
        gen = self.generation
        return {
            "model": cell.model,
            "backend": self.backend,
            "tasks": [cell.task_id],
            "repeats": self.repetitions,
            "base_seed": gen["base_seed"],
            "temperature": gen["temperature"],
            "request_timeout_s": gen["request_timeout_s"],
            "mode": "fresh",
            "name": self.evaluation_name(cell),
        }

    def task_domains(self) -> dict[str, list[tuple[str, float]]]:
        return {t["task_id"]: [(d, float(w)) for d, w in t["domains"]] for t in self.data["tasks"]}


def dump(data: dict, path: str | Path) -> None:
    target = paths.resolve(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
