"""The frozen campaign plan: build, load, validate, derive.

A manifest pins everything a campaign's evidence depends on: the runtime release,
the backend, the generation settings, the model roster, and every task's current
version AND content digest (computed with the runtime's own ``task_snapshot``, so
the digests are exactly what each evaluation snapshot will record). It also
fixes the plan: one cell per (model, task), each executed as ONE fresh evaluation
with ``repetitions`` positions, split into Phase A (cells that passed at least
once on a task version ORACLE later strengthened) and Phase B (everything else).

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


def expected_counts(data: dict) -> dict:
    reps = int(data["repetitions"])
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
    derived["cells"] = [
        {**cell, "phase": "A"}
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
