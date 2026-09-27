"""The campaign ledger: which evaluation IDs belong to the campaign.

The ledger is the campaign's ownership record. The database is the authority on
what an evaluation DID; the ledger is the authority on which evaluations COUNT.
Completeness, monitoring, analysis and the official leaderboard only ever look at
evaluations referenced by an ACTIVE ledger entry, so an unrelated later
evaluation in the same database (a UI experiment, a retry clone, a dry run) can
never enter the campaign's evidence.

One JSON document, rewritten atomically (temp file + fsync + rename) under an
exclusive advisory lock held by the single launcher. Read-only consumers
(status, validate, analysis) load it without the lock.

Entry states::

    submitting   the entry was written BEFORE POST /jobs; no evaluation id yet
                 (a crash here is reconciled by the evaluation name on restart)
    submitted    evaluation created, not yet terminal
    succeeded    terminal, succeeded, every campaign check passed
    needs_attention  succeeded, but its evidence cannot be trusted as is
                 (infrastructure-voided positions, or a backend that failed
                 a check when it finished): superseded for a re-evaluation
    failed / canceled  the evaluation ended failed / canceled (resumable)
    rejected     the evaluation's evidence failed a campaign check (provenance,
                 version, digest, parameters, model identity, concurrency,
                 a resume outside the tooling): its evidence is EXCLUDED
    superseded   an operator replaced this entry (reason recorded); inactive

Exactly one ACTIVE (non-superseded) entry may exist per cell.

A sequential-local campaign (one model per phase) also records its model
lifecycle here: ``model_status`` (a model classified LOCAL_RESOURCE_LIMIT /
LOCAL_RUNTIME_UNSUPPORTED / NOT_BENCHMARKED, with its evidence), ``smokes``,
``receipts`` (a model's frozen 120-run receipt, required BEFORE its weights may
be removed), ``model_pulls`` and ``model_deletions`` (what was removed, why,
and the evidence status at that moment). Removing model weights never touches
campaign evidence: the database and this ledger are independent of the model
files.
"""

from __future__ import annotations

import contextlib
import datetime as _dt
import fcntl
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Iterator

LEDGER_SCHEMA_VERSION = 1

SUBMITTING = "submitting"
SUBMITTED = "submitted"
SUCCEEDED = "succeeded"
NEEDS_ATTENTION = "needs_attention"
FAILED = "failed"
CANCELED = "canceled"
REJECTED = "rejected"
SUPERSEDED = "superseded"

STATES = (SUBMITTING, SUBMITTED, SUCCEEDED, NEEDS_ATTENTION, FAILED, CANCELED, REJECTED, SUPERSEDED)
# States that halt the launcher until an operator acts (resume / supersede).
HALTING = (NEEDS_ATTENTION, FAILED, CANCELED, REJECTED)
# States an operator may supersede. A SUCCEEDED cell can never be superseded:
# replacing good evidence because of its result would be cherry-picking.
SUPERSEDABLE = (NEEDS_ATTENTION, FAILED, CANCELED, REJECTED)


class LedgerError(RuntimeError):
    """The ledger is missing, locked, corrupt, or belongs to another plan."""


def utc_now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
        dir_fd = os.open(str(path.parent), os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)
        raise


@contextlib.contextmanager
def ledger_lock(path: Path) -> Iterator[None]:
    """Exclusive single-launcher lock beside the ledger file (advisory, same
    host). Usable before the ledger exists, so a refused launch creates nothing."""
    lock_path = Path(path).with_name(Path(path).name + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(lock_path), os.O_RDWR | os.O_CREAT, 0o644)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise LedgerError(
                f"another campaign launcher holds {lock_path}; only one launcher may run"
            ) from None
        try:
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
    finally:
        os.close(fd)


class Ledger:
    def __init__(self, path: Path, data: dict) -> None:
        self.path = Path(path)
        self.data = data

    # ------------------------------------------------------------------ io
    @classmethod
    def new(cls, path: Path, *, campaign_id: str, manifest_sha256: str, manifest_path: str) -> "Ledger":
        return cls(
            path,
            {
                "schema_version": LEDGER_SCHEMA_VERSION,
                "campaign_id": campaign_id,
                "manifest_path": manifest_path,
                "manifest_sha256": manifest_sha256,
                "created_at": utc_now(),
                "launches": [],
                "entries": [],
                "disowned": [],
                "events": [],
            },
        )

    @classmethod
    def load(cls, path: Path, *, campaign_id: str | None = None, manifest_sha256: str | None = None) -> "Ledger":
        try:
            data = json.loads(Path(path).read_text())
        except FileNotFoundError:
            raise LedgerError(f"no campaign ledger at {path}") from None
        except (OSError, ValueError) as exc:
            raise LedgerError(f"campaign ledger {path} is unreadable: {exc}") from exc
        if not isinstance(data, dict) or data.get("schema_version") != LEDGER_SCHEMA_VERSION:
            raise LedgerError(f"campaign ledger {path} has an unsupported schema")
        if campaign_id is not None and data.get("campaign_id") != campaign_id:
            raise LedgerError(
                f"ledger {path} belongs to campaign {data.get('campaign_id')!r}, not {campaign_id!r}"
            )
        if manifest_sha256 is not None and data.get("manifest_sha256") != manifest_sha256:
            raise LedgerError(
                "the campaign manifest changed after the ledger was created "
                f"(ledger {data.get('manifest_sha256')}, manifest {manifest_sha256}); a launched "
                "campaign's plan is frozen - restore the original manifest"
            )
        ledger = cls(path, data)
        ledger._check_invariants()
        return ledger

    @classmethod
    def open_or_create(cls, path: Path, *, campaign_id: str, manifest_sha256: str, manifest_path: str) -> "Ledger":
        if Path(path).exists():
            return cls.load(path, campaign_id=campaign_id, manifest_sha256=manifest_sha256)
        ledger = cls.new(path, campaign_id=campaign_id, manifest_sha256=manifest_sha256, manifest_path=manifest_path)
        ledger.save()
        return ledger

    def save(self) -> None:
        self._check_invariants()
        _atomic_write(self.path, json.dumps(self.data, indent=2, ensure_ascii=False) + "\n")

    def lock(self):
        """Exclusive single-launcher lock (advisory, same host)."""
        return ledger_lock(self.path)

    # ------------------------------------------------------------ queries
    @property
    def entries(self) -> list[dict]:
        return self.data["entries"]

    def entries_for(self, key: str) -> list[dict]:
        return [e for e in self.entries if e["cell"] == key]

    def active_entry(self, key: str) -> dict | None:
        active = [e for e in self.entries_for(key) if e["state"] != SUPERSEDED]
        return active[0] if active else None

    def active_entries(self) -> list[dict]:
        return [e for e in self.entries if e["state"] != SUPERSEDED]

    def evaluation_ids(self, *, active_only: bool = True) -> set[str]:
        pool = self.active_entries() if active_only else self.entries
        return {e["evaluation_id"] for e in pool if e.get("evaluation_id")}

    def entry_by_evaluation(self, evaluation_id: str) -> dict | None:
        for entry in self.entries:
            if entry.get("evaluation_id") == evaluation_id:
                return entry
        return None

    _ENTRY_KEYS = ("cell", "model", "task_id", "phase", "evaluation_name", "state")
    # optional lifecycle records of a sequential-local campaign: (field, container type)
    _LIFECYCLE = (("model_status", dict), ("smokes", list), ("receipts", dict), ("model_pulls", list),
                  ("model_deletions", list))

    def _check_invariants(self) -> None:
        data = self.data
        for key, kind in (("entries", list), ("launches", list), ("events", list)):
            if not isinstance(data.get(key), kind):
                raise LedgerError(f"ledger field {key!r} must be a {kind.__name__}")
        if not isinstance(data.setdefault("disowned", []), list):
            raise LedgerError("ledger field 'disowned' must be a list")
        for name, container in self._LIFECYCLE:
            value = data.get(name)
            if value is None:
                continue
            if not isinstance(value, container):
                raise LedgerError(f"ledger field {name!r} must be a {container.__name__}")
            records = value.values() if isinstance(value, dict) else value
            if not all(isinstance(r, dict) for r in records):
                raise LedgerError(f"ledger field {name!r} holds a malformed record")
        for position, entry in enumerate(data["entries"]):
            if not isinstance(entry, dict):
                raise LedgerError(f"ledger entry #{position} is not an object")
            missing = [k for k in self._ENTRY_KEYS if not isinstance(entry.get(k), str) or not entry.get(k)]
            if missing:
                raise LedgerError(f"ledger entry #{position} lacks {missing}")
            eid = entry.get("evaluation_id")
            if eid is not None and not (isinstance(eid, str) and eid):
                raise LedgerError(f"ledger entry #{position} has a malformed evaluation_id")
            resumes = entry.get("resumes", [])
            if not isinstance(resumes, list) or not all(isinstance(r, dict) for r in resumes):
                raise LedgerError(f"ledger entry #{position} has malformed resume records")
        for position, event in enumerate(data["events"]):
            if not (isinstance(event, dict) and isinstance(event.get("type"), str) and event["type"]):
                raise LedgerError(f"ledger event #{position} is malformed")
        for position, launch in enumerate(data["launches"]):
            if not isinstance(launch, dict):
                raise LedgerError(f"launch record #{position} is not an object")
            if not isinstance(launch.get("started_at"), str) or not isinstance(launch.get("check_code", False), bool):
                raise LedgerError(f"launch record #{position} lacks a started_at or has a non-boolean check_code")
            inventory = launch.get("inventory")
            if inventory is not None:
                models = inventory.get("models") if isinstance(inventory, dict) else None
                if not isinstance(models, dict) or not all(isinstance(v, dict) for v in models.values()):
                    raise LedgerError(f"launch record #{position} has a malformed inventory")
        for position, record in enumerate(data["disowned"]):
            if not (isinstance(record, dict) and isinstance(record.get("evaluation_id"), str)
                    and isinstance(record.get("reason"), str) and record["reason"].strip()):
                raise LedgerError(f"disowned record #{position} is malformed")
        seen: dict[str, int] = {}
        eval_ids: dict[str, str] = {}
        for entry in data["entries"]:
            if entry.get("state") not in STATES:
                raise LedgerError(f"ledger entry for {entry.get('cell')} has unknown state {entry.get('state')!r}")
            if entry["state"] != SUPERSEDED:
                seen[entry["cell"]] = seen.get(entry["cell"], 0) + 1
            eid = entry.get("evaluation_id")
            if eid:
                if eid in eval_ids:
                    raise LedgerError(f"evaluation {eid} is referenced by two ledger entries")
                eval_ids[eid] = entry["cell"]
        doubled = sorted(k for k, n in seen.items() if n > 1)
        if doubled:
            raise LedgerError(f"cells with more than one active ledger entry: {doubled}")
        disowned = [r["evaluation_id"] for r in data["disowned"]]
        if len(disowned) != len(set(disowned)):
            raise LedgerError("an evaluation is disowned twice")
        claimed = sorted(set(disowned) & set(eval_ids))
        if claimed:
            raise LedgerError(f"evaluations both owned and disowned: {claimed}")

    # ----------------------------------------------------------- mutation
    def event(self, kind: str, **detail: Any) -> None:
        self.data["events"].append({"at": utc_now(), "type": kind, **detail})

    def new_entry(self, *, key: str, model: str, task_id: str, phase: str, evaluation_name: str, positions: list[int]) -> dict:
        if self.active_entry(key) is not None:
            raise LedgerError(f"cell {key} already has an active ledger entry")
        entry = {
            "cell": key,
            "model": model,
            "task_id": task_id,
            "phase": phase,
            "evaluation_name": evaluation_name,
            "expected_positions": positions,
            "evaluation_id": None,
            "state": SUBMITTING,
            "job_status": None,
            "created_at": utc_now(),
            "updated_at": utc_now(),
            "finished_at": None,
            "summary": None,
            "problems": [],
            "warnings": [],
            "superseded_reason": None,
        }
        self.entries.append(entry)
        return entry

    def update(self, entry: dict, **fields: Any) -> dict:
        entry.update(fields)
        entry["updated_at"] = utc_now()
        return entry

    # ------------------------------------------------ model lifecycle (sequential)
    def model_status(self) -> dict:
        return self.data.setdefault("model_status", {})

    def classify_model(self, *, phase: str, model: str, status: str, reason: str, evidence: str) -> dict:
        from .manifest import MODEL_CLASSIFICATIONS

        if status not in MODEL_CLASSIFICATIONS:
            raise LedgerError(f"unknown model classification {status!r}; one of {MODEL_CLASSIFICATIONS}")
        if not (reason and reason.strip() and evidence and evidence.strip()):
            raise LedgerError("classifying a model requires a written reason AND supporting evidence")
        if phase in self.model_status():
            raise LedgerError(f"{model} ({phase}) is already classified {self.model_status()[phase]['status']}")
        record = {"phase": phase, "model": model, "status": status, "reason": reason.strip(),
                  "evidence": evidence.strip(), "at": utc_now()}
        self.model_status()[phase] = record
        self.event("model_classified", phase=phase, model=model, status=status, reason=reason.strip())
        return record

    def record(self, field: str, record: dict) -> dict:
        """Append a lifecycle record (smokes, model_pulls, model_deletions)."""
        self.data.setdefault(field, []).append(record)
        self.event(field.rstrip("s"), **{k: v for k, v in record.items()
                                         if isinstance(v, (str, int, float, bool)) and k not in ("at", "type")})
        return record

    def disowned_ids(self) -> set[str]:
        return {r["evaluation_id"] for r in self.data.get("disowned", [])}

    def disown(self, evaluation_id: str, reason: str) -> dict:
        """Record an evaluation carrying this campaign's name as NOT campaign
        evidence (e.g. a UI retry clone). It stays in the database, is excluded
        from every count, and is listed in every receipt."""
        if not reason or not reason.strip():
            raise LedgerError("disowning requires a written reason")
        if self.entry_by_evaluation(evaluation_id) is not None:
            raise LedgerError(f"evaluation {evaluation_id} is owned by a ledger entry; supersede the cell instead")
        if evaluation_id in self.disowned_ids():
            raise LedgerError(f"evaluation {evaluation_id} is already disowned")
        record = {"evaluation_id": evaluation_id, "reason": reason.strip(), "at": utc_now()}
        self.data.setdefault("disowned", []).append(record)
        self.event("disowned", evaluation_id=evaluation_id, reason=reason.strip())
        return record

    def supersede(self, key: str, reason: str, *, refused_by_validator: list[str] | None = None) -> dict:
        """``refused_by_validator``: the acceptance predicate's problems for a
        SUCCEEDED entry it refuses; only then may a succeeded entry be replaced."""
        entry = self.active_entry(key)
        if entry is None:
            raise LedgerError(f"cell {key} has no active ledger entry")
        invalid_success = entry["state"] == SUCCEEDED and bool(refused_by_validator)
        if entry["state"] not in SUPERSEDABLE and not invalid_success:
            raise LedgerError(
                f"cell {key} is {entry['state']!r}; only {SUPERSEDABLE} entries (or a succeeded entry the "
                "validator refuses) may be superseded (an accepted succeeded cell is final: replacing it "
                "because of its result would be cherry-picking)"
            )
        if not reason or not reason.strip():
            raise LedgerError("superseding requires a written reason")
        self.update(entry, state=SUPERSEDED, superseded_reason=reason.strip(), superseded_at=utc_now(),
                    superseded_from=entry["state"],
                    **({"superseded_validator_problems": list(refused_by_validator)} if invalid_success else {}))
        self.event("superseded", cell=key, evaluation_id=entry.get("evaluation_id"), reason=reason.strip())
        return entry
