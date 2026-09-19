"""Deterministic evaluation-scoped JSON and Markdown reports."""
from __future__ import annotations

import json
import math
import sqlite3
from typing import Any

from . import jobs
from .schemas import Backend

REPORT_SCHEMA_VERSION = 1
_REPORT_BACKEND_KINDS = {"mock", "ollama", "openai_compat"}
_REPORT_JOB_STATUSES = {"queued", "running", "succeeded", "failed", "canceled"}
_REPORT_JOB_MODES = {"fresh", "reuse", "legacy"}


def _safe_backend(value: Any) -> dict[str, Any] | None:
    """Validate only an explicitly persisted backend kind and safe fields."""
    if (
        not isinstance(value, dict)
        or not isinstance(value.get("kind"), str)
        or value.get("kind") not in _REPORT_BACKEND_KINDS
    ):
        return None
    try:
        backend = Backend.model_validate(value)
    except (TypeError, ValueError):
        return None
    return backend.model_dump(mode="json")


def _safe_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def _safe_positive_int(value: Any) -> int | None:
    value = _safe_int(value)
    return value if value is not None and value >= 1 else None


def _safe_float(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if math.isfinite(value) else None


def _safe_model(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


def _loads_lenient(text: Any) -> Any:
    """json.loads for best-effort labelling: garbage or absurdly nested JSON is
    None. Non-finite numbers are kept out of the report field by field
    (``_safe_*``), so the rest of a partly damaged row can still be labelled."""
    try:
        return json.loads(text)
    except (TypeError, ValueError, RecursionError):
        return None


def _persisted_parameters(raw_json: Any) -> dict[str, Any]:
    """Keep only usable, non-secret fields from the stored params JSON.

    ``jobs._job_params_from_row`` intentionally supplies safe schema defaults
    for legacy listings. Reports must not mistake those defaults for provenance,
    so this projection parses the persisted payload independently.
    """
    raw = _loads_lenient(raw_json)
    if not isinstance(raw, dict):
        return {}

    result: dict[str, Any] = {}
    model = _safe_model(raw.get("model"))
    if model is not None:
        result["model"] = model
    if "name" in raw and (raw["name"] is None or isinstance(raw["name"], str)):
        result["name"] = raw["name"]
    for key in ("repeats", "request_timeout_s"):
        value = _safe_positive_int(raw.get(key))
        if value is not None:
            result[key] = value
    if "base_seed" in raw:
        value = _safe_int(raw["base_seed"])
        if value is not None:
            result["base_seed"] = value
    if "temperature" in raw:
        value = _safe_float(raw["temperature"])
        if value is not None:
            result["temperature"] = value
    if isinstance(raw.get("source_evaluation_id"), str):
        result["source_evaluation_id"] = raw["source_evaluation_id"]
    mode = raw.get("mode")
    if isinstance(mode, str) and mode in _REPORT_JOB_MODES:
        result["mode"] = mode
    backend = _safe_backend(raw.get("backend"))
    if backend is not None:
        result["backend"] = backend
    return result


def _stored_snapshot(row: sqlite3.Row) -> dict[str, Any] | None:
    raw_snapshot = row["snapshot_json"] if "snapshot_json" in row.keys() else None
    if not raw_snapshot:
        return None
    snapshot = _loads_lenient(raw_snapshot)
    return snapshot if isinstance(snapshot, dict) else None


def _tasks(snapshot: dict[str, Any] | None) -> list[dict[str, Any]]:
    raw = snapshot.get("tasks") if isinstance(snapshot, dict) else None
    if not isinstance(raw, list) or not raw:
        return []
    result: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            return []
        values = {
            key: item.get(key)
            for key in ("task_id", "task_version", "task_digest")
        }
        if not all(isinstance(value, str) and value for value in values.values()):
            return []
        result.append(values)
    return result


def _generation(
    snapshot: dict[str, Any] | None, persisted: dict[str, Any]
) -> dict[str, Any]:
    raw = snapshot.get("generation") if isinstance(snapshot, dict) else None
    raw = raw if isinstance(raw, dict) else {}

    base_seed = _safe_int(raw.get("base_seed"))
    if base_seed is None:
        base_seed = _safe_int(persisted.get("base_seed"))
    temperature = _safe_float(raw.get("temperature"))
    if temperature is None:
        temperature = _safe_float(persisted.get("temperature"))
    request_timeout_s = _safe_positive_int(raw.get("request_timeout_s"))
    if request_timeout_s is None:
        request_timeout_s = _safe_positive_int(persisted.get("request_timeout_s"))
    return {
        "base_seed": base_seed,
        "temperature": temperature,
        "request_timeout_s": request_timeout_s,
        "seed_provenance": (
            raw.get("seed_provenance")
            if isinstance(raw.get("seed_provenance"), str)
            else None
        ),
        "timeout_provenance": (
            raw.get("timeout_provenance")
            if isinstance(raw.get("timeout_provenance"), str)
            else None
        ),
    }


def _parameters(
    source_evaluation_id: str | None,
    snapshot: dict[str, Any] | None,
    persisted: dict[str, Any],
    generation: dict[str, Any],
    backend: dict[str, Any] | None,
) -> dict[str, Any]:
    repeats = _safe_positive_int(snapshot.get("repeats")) if isinstance(snapshot, dict) else None
    return {
        "model": (
            _safe_model(snapshot.get("model"))
            if isinstance(snapshot, dict)
            else None
        ) or persisted.get("model"),
        "name": persisted.get("name"),
        "repeats": repeats if repeats is not None else persisted.get("repeats"),
        "base_seed": generation["base_seed"],
        "temperature": generation["temperature"],
        "request_timeout_s": generation["request_timeout_s"],
        "backend": backend,
        "source_evaluation_id": source_evaluation_id,
    }


def _limitations(row: sqlite3.Row, trial: dict[str, Any]) -> list[str]:
    label = f"{row['task_id']} trial {int(row['idx'])}"
    result: list[str] = []
    if row["trial_state"] != "completed":
        result.append(f"{label} is {row['trial_state']}; no completed outcome is available.")
    if row["error_message"]:
        result.append(f"{label} error: {row['error_message']}")
    if row["evidence_state"] == "reused":
        result.append(
            f"{label} reuses evidence from evaluation {row['source_evaluation_id'] or 'unknown'}; "
            "it was not freshly executed."
        )
    if trial["artifact_state"] in {"absent", "partial", "unavailable"}:
        result.append(f"{label} artifacts are {trial['artifact_state']}.")
    if trial["outcome"] is None:
        result.append(f"{label} outcome evidence is unavailable or unverifiable.")
    if trial.get("integrity_error"):
        result.append(
            f"{label} provenance integrity error: {trial['integrity_error']}; "
            "it is not presented as comparable evidence."
        )
    return result


def _build_evaluation_report(
    conn: sqlite3.Connection, evaluation_id: str
) -> dict[str, Any] | None:
    # Read the control row directly so malformed legacy snapshot JSON cannot
    # fail through Job's schema validation before this report labels it unknown.
    row = conn.execute(
        "SELECT * FROM evaluation_jobs WHERE id=?", (evaluation_id,)
    ).fetchone()
    if row is None:
        return None
    persisted = _persisted_parameters(row["params_json"])
    snapshot = _stored_snapshot(row)
    snapshot_model = _safe_model(snapshot.get("model")) if isinstance(snapshot, dict) else None
    task_snapshots = _tasks(snapshot)
    snapshot_backend = (
        _safe_backend(snapshot.get("backend"))
        if isinstance(snapshot, dict) and "backend" in snapshot
        else None
    )
    backend = snapshot_backend or persisted.get("backend")
    if backend is not None and backend.get("kind") not in _REPORT_BACKEND_KINDS:
        backend = None
    generation = _generation(snapshot, persisted)
    raw_source_evaluation_id = (
        row["source_evaluation_id"]
        if "source_evaluation_id" in row.keys()
        else None
    )
    source_evaluation_id = (
        raw_source_evaluation_id
        if isinstance(raw_source_evaluation_id, str)
        else None
    )
    raw_status = row["status"]
    status = raw_status if isinstance(raw_status, str) and raw_status in _REPORT_JOB_STATUSES else None
    raw_mode = row["mode"]
    mode = raw_mode if isinstance(raw_mode, str) and raw_mode in _REPORT_JOB_MODES else None

    trials: list[dict[str, Any]] = []
    limitations: list[str] = []
    try:
        jobs.verify_persisted_params(
            row["params_json"],
            row["snapshot_json"] if "snapshot_json" in row.keys() else None,
            row["mode"] if "mode" in row.keys() else None,
            row["source_evaluation_id"] if "source_evaluation_id" in row.keys() else None,
        )
    except jobs.InvalidPersistedParams as exc:
        limitations.append(
            "Persisted evaluation parameters could not be verified against the creation "
            "record (" + str(exc).removeprefix(f"{jobs._INVALID_PREFIX}: ") + "); "
            "the values below come from the creation snapshot and this evaluation "
            "cannot be resumed or retried."
        )
    for trial_row in jobs.trial_rows(conn, evaluation_id):
        detail = jobs.trial_detail(
            conn, evaluation_id, trial_row["task_id"], int(trial_row["idx"])
        ) or {}
        trial = {
            "task_id": trial_row["task_id"],
            "idx": int(trial_row["idx"]),
            "task_version": trial_row["task_version"],
            "task_digest": trial_row["task_digest"],
            "run_id": trial_row["run_id"],
            "trial_state": trial_row["trial_state"],
            "evidence_state": trial_row["evidence_state"],
            "source_evaluation_id": trial_row["source_evaluation_id"],
            "source_run_id": trial_row["source_run_id"],
            "origin_evaluation_id": trial_row["origin_evaluation_id"],
            "outcome": detail.get("outcome"),
            "artifact_state": detail.get("artifact_state", "unavailable"),
            "comparability": detail.get("comparability"),
            "backend_kind": detail.get("backend_kind"),
            "provenance": detail.get("provenance", "unknown"),
            "error_message": trial_row["error_message"],
        }
        if detail.get("integrity_error"):
            trial["integrity_error"] = detail["integrity_error"]
        trials.append(trial)
        limitations.extend(_limitations(trial_row, trial))

    if status is None:
        limitations.append("Persisted evaluation status is unavailable or unverifiable.")
    if mode is None:
        limitations.append("Persisted evaluation mode is unavailable or unverifiable.")
    if snapshot is None or not task_snapshots:
        limitations.append("The persisted evaluation task snapshot is unavailable or unverifiable.")
    if not persisted:
        limitations.append("Persisted evaluation parameters are unavailable or unverifiable.")
    if snapshot_model is None and "model" not in persisted:
        limitations.append("Persisted model provenance is unavailable or unverifiable.")
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get("generation"), dict):
        limitations.append("Persisted generation provenance is unavailable or unverifiable.")
    for key, label in (
        ("base_seed", "base seed"),
        ("temperature", "temperature"),
        ("request_timeout_s", "request timeout"),
        ("seed_provenance", "seed provenance"),
        ("timeout_provenance", "timeout provenance"),
    ):
        if generation[key] is None:
            limitations.append(f"Persisted {label} is unavailable or unverifiable.")
    if backend is None:
        limitations.append("Persisted backend provenance is unavailable or unverifiable.")

    completed = [trial for trial in trials if trial["trial_state"] == "completed"]
    fresh = [trial for trial in completed if trial["evidence_state"] == "fresh"]
    outcome = [trial for trial in fresh if trial["outcome"] is not None]
    passed = [
        trial
        for trial in outcome
        if trial["outcome"]["functional_pass"] is True
        and trial["outcome"]["voided"] is not True
    ]
    voided = [trial for trial in outcome if trial["outcome"]["voided"] is True]
    failed = [
        trial
        for trial in outcome
        if trial["outcome"]["functional_pass"] is False
        and trial["outcome"]["voided"] is not True
    ]
    reused = [trial for trial in completed if trial["evidence_state"] == "reused"]
    counters = {
        "total": len(trials),
        "completed": len(completed),
        "passed": len(passed),
        "failed": len(failed),
        "voided": len(voided),
        "reused": len(reused),
        "incomplete": sum(trial["trial_state"] != "completed" for trial in trials),
        "unavailable": sum(trial["outcome"] is None for trial in trials),
    }
    counter_semantics = {
        "total": "canonical requested evaluation trial rows",
        "completed": "completed rows, including reused evidence",
        "passed": "fresh completed rows with a usable non-voided passing score",
        "failed": "fresh completed rows with a usable non-voided failing score",
        "voided": "fresh completed rows with a usable voided score",
        "reused": "completed rows explicitly linked to prior evidence",
        "incomplete": "rows not in completed trial state",
        "unavailable": "rows without a usable outcome, including incomplete or missing score evidence",
    }
    model = snapshot_model or persisted.get("model")
    return {
        "schema_version": REPORT_SCHEMA_VERSION,
        "evaluation_id": evaluation_id,
        "status": status,
        "mode": mode,
        "created_at": row["created_at"],
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
        "model": model,
        "backend": backend,
        "provider": backend.get("kind") if backend else None,
        "evaluation_parameters": _parameters(
            source_evaluation_id, snapshot, persisted, generation, backend
        ),
        "generation": generation,
        "task_snapshots": task_snapshots,
        "counters": counters,
        "counter_semantics": counter_semantics,
        "trials": trials,
        "limitations": sorted(set(limitations)),
    }


def build_evaluation_report(conn: sqlite3.Connection, evaluation_id: str) -> dict[str, Any] | None:
    """Build one report from one coherent SQLite read snapshot."""
    owns_snapshot = not conn.in_transaction
    if owns_snapshot:
        conn.execute("BEGIN")
    try:
        return _build_evaluation_report(conn, evaluation_id)
    finally:
        if owns_snapshot:
            conn.rollback()


def _value(value: Any) -> str:
    if value is None:
        return "unavailable"
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _json(value: Any) -> str:
    if value is None:
        return "unavailable"
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _result(outcome: dict[str, Any] | None) -> str:
    if outcome is None:
        return "UNAVAILABLE"
    status = outcome.get("status")
    if outcome.get("voided"):
        return f"VOIDED ({status})" if status else "VOIDED"
    result = "PASS" if outcome.get("functional_pass") else "FAIL"
    return f"{result} ({status})" if status and status != "valid" else result


def render_markdown(report: dict[str, Any]) -> str:
    """Render the supplied JSON projection without clock/randomness/database reads."""
    counters = report["counters"]
    lines = [
        "# AgentForge Evaluation Report", "",
        f"- Schema version: `{_value(report['schema_version'])}`",
        f"- Evaluation: `{_value(report['evaluation_id'])}`",
        f"- Model: `{_value(report['model'])}`",
        f"- Provider: `{_value(report['provider'])}`",
        f"- Status: `{_value(report['status'])}`",
        f"- Mode: `{_value(report['mode'])}`", "",
        "## Evaluation", "",
        f"- Created at: `{_value(report['created_at'])}`",
        f"- Started at: `{_value(report['started_at'])}`",
        f"- Finished at: `{_value(report['finished_at'])}`",
        f"- Backend: `{_json(report['backend'])}`",
        f"- Parameters: `{_json(report['evaluation_parameters'])}`",
        f"- Generation: `{_json(report['generation'])}`", "",
        "## Summary", "",
    ]
    for key in counters:
        lines.append(f"- {key.replace('_', ' ').title()}: {counters[key]}")
    lines.extend(["", "## Counter semantics", ""])
    lines.extend(
        f"- {key.replace('_', ' ').title()}: {value}"
        for key, value in report["counter_semantics"].items()
    )
    lines.extend(["", "## Task snapshots", ""])
    lines.extend(
        f"- `{task.get('task_id')}` @ `{task.get('task_version')}` (`{task.get('task_digest')}`)"
        for task in report["task_snapshots"]
    )
    if not report["task_snapshots"]:
        lines.append("- unavailable")
    lines.extend(["", "## Trials", ""])
    for trial in report["trials"]:
        outcome = trial["outcome"] or {}
        lines.extend([
            f"### `{trial['task_id']}` @ `{trial['task_version']}` — trial {trial['idx']}", "",
            f"- Run ID: `{_value(trial['run_id'])}`",
            f"- Evidence: `{trial['evidence_state']}`",
            f"- Trial state: `{trial['trial_state']}`",
            f"- Result: `{_result(trial['outcome'])}`",
            f"- Outcome status: `{_value(outcome.get('status'))}`",
            f"- Functional pass: `{_value(outcome.get('functional_pass'))}`",
            f"- Voided: `{_value(outcome.get('voided'))}`",
            f"- Score: `{_value(outcome.get('final_score'))}`",
            f"- Artifacts: `{trial['artifact_state']}`",
            f"- Comparability: `{_value(trial['comparability'])}`",
            f"- Backend: `{_value(trial.get('backend_kind'))}`",
            f"- Provenance: `{trial.get('provenance', 'unknown')}`",
        ])
        if trial["source_evaluation_id"] is not None:
            lines.append(f"- Source evaluation: `{trial['source_evaluation_id']}`")
        if trial["source_run_id"] is not None:
            lines.append(f"- Source run ID: `{trial['source_run_id']}`")
        if trial["origin_evaluation_id"] is not None:
            lines.append(f"- Origin evaluation: `{trial['origin_evaluation_id']}`")
        if trial["error_message"]:
            lines.append(f"- Error: `{trial['error_message']}`")
        lines.append("")
    if not report["trials"]:
        lines.append("- unavailable\n")
    lines.extend(["## Limitations", ""])
    lines.extend(f"- {item}" for item in report["limitations"] or ["None recorded."])
    lines.append("")
    return "\n".join(lines)
