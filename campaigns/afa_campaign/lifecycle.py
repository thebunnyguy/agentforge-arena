"""Model lifecycle of a sequential-local campaign (one model at a time).

Local storage cannot hold every benchmark model at once, so each roster model
goes through: install (or reuse) -> smoke -> full batch -> validation -> frozen
receipt -> (optionally) removal of its weights -> next model. This module owns
every step that touches MODEL FILES; none of it ever touches campaign evidence:

* ``storage_inventory``  disk space, Ollama models, other local model weights
  (MLX / GGUF caches), written as a JSON inventory (home paths shown as ``~``).
* ``pull_model``         pull ONLY the phase's target, after checking space and
  that no other unfinished target is installed; its digest must equal the pin.
* ``remove_model``       remove Ollama model weights, recorded in the ledger
  BEFORE the removal (model, size, digest, reason, evidence status). A roster
  model is removed only after its receipt is frozen and re-validates, or after
  it was classified; never while any evaluation is active.
* ``classify_model``     LOCAL_RESOURCE_LIMIT / LOCAL_RUNTIME_UNSUPPORTED /
  NOT_BENCHMARKED with written evidence: the model leaves the expected cohort.
* ``model_receipt``      the frozen per-model receipt (24 cells, 120 accepted
  runs, identities, metrics), recorded in the ledger with its sha256.
* ``run_smoke``          a 4-task x 1-repetition smoke through the real ATLAS
  lifecycle in a SCRATCH database (separate campaign id, app and ledger):
  never campaign evidence.

Model weights != benchmark evidence: the campaign database and the ledger are
independent of the model files, and every result stays inspectable (and
re-validates) after its model is removed.
"""

from __future__ import annotations

import datetime as _dt
import json
import os
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from . import api as api_mod
from . import cohort, ollama, paths
from . import validate as validate_mod
from .launcher import CampaignStop, Launcher, init_db, reference_digests, reference_ollama_version
from .ledger import SUBMITTED, SUBMITTING, Ledger, LedgerError, ledger_lock, utc_now
from .manifest import Manifest, derive_subset, dump, evidence_sha256, file_sha256, normalize_digest

GIB = 1024 ** 3
PULL_MARGIN_BYTES = 4 * GIB  # free space kept beyond the download itself


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #


def _home(path: str | Path) -> str:
    text = str(path)
    home = str(Path.home())
    return "~" + text[len(home):] if text.startswith(home) else text


def ollama_models_dir() -> Path:
    return Path(os.environ.get("OLLAMA_MODELS") or Path.home() / ".ollama" / "models")


def _dir_bytes(path: Path) -> int:
    """Bytes stored under ``path`` (files counted once; symlinks not followed)."""
    total = 0
    for root, _dirs, files in os.walk(path, followlinks=False):
        for name in files:
            try:
                st = os.lstat(os.path.join(root, name))
            except OSError:
                continue
            if not os.path.islink(os.path.join(root, name)):
                total += st.st_size
    return total


def disk_free(path: Path | None = None) -> dict:
    usage = shutil.disk_usage(path or ollama_models_dir())
    return {"total_bytes": usage.total, "used_bytes": usage.used, "free_bytes": usage.free}


def _ollama_call(base_url: str, method: str, path: str, body=None, timeout: float = 60.0):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(base_url.rstrip("/") + path, data=data, method=method,
                                 headers={"content-type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        raise ollama.OllamaError(f"{method} {path} -> HTTP {exc.code}: {exc.read()[:300]!r}") from None
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        raise ollama.OllamaError(f"{method} {path}: {exc}") from None
    return json.loads(raw or b"null")


def ollama_models(base_url: str) -> list[dict]:
    """Every model Ollama manages: name, digest, size, modified time, details."""
    tags = (_ollama_call(base_url, "GET", "/api/tags") or {}).get("models", [])
    out = []
    for tag in tags:
        details = tag.get("details") or {}
        out.append({"name": tag.get("name"), "digest": tag.get("digest"), "size_bytes": tag.get("size"),
                    "modified_at": tag.get("modified_at"), "format": details.get("format"),
                    "family": details.get("family"), "parameter_size": details.get("parameter_size"),
                    "quantization": details.get("quantization_level")})
    return out


def _weight_kind(path: Path) -> str:
    names = [p.name.lower() for p in path.rglob("*")][:5000]
    if any(n.endswith(".gguf") for n in names):
        return "gguf"
    if "mlx" in path.name.lower() or any("mlx" in n for n in names):
        return "mlx"
    if any(n.endswith(".safetensors") for n in names):
        return "safetensors"
    return "other"


def other_model_weights() -> list[dict]:
    """Model weights outside Ollama that are recognisable as such: Hugging Face
    hub model caches and LM Studio models. Reported, never removed here."""
    found = []
    hub = Path.home() / ".cache" / "huggingface" / "hub"
    if hub.is_dir():
        for entry in sorted(hub.glob("models--*")):
            found.append({"runtime": "huggingface-cache", "path": _home(entry),
                          "model": entry.name[len("models--"):].replace("--", "/"),
                          "kind": _weight_kind(entry), "bytes": _dir_bytes(entry)})
    lmstudio = Path.home() / ".lmstudio" / "models"
    if lmstudio.is_dir():
        for publisher in sorted(p for p in lmstudio.iterdir() if p.is_dir()):
            for model in sorted(p for p in publisher.iterdir() if p.is_dir()):
                found.append({"runtime": "lm-studio", "path": _home(model), "model": f"{publisher.name}/{model.name}",
                              "kind": _weight_kind(model), "bytes": _dir_bytes(model)})
    return found


def storage_log(manifest: Manifest, record: dict) -> Path:
    """Append one record to the campaign's storage audit log (JSON lines, fsynced).
    Every pull and removal is logged here BEFORE it happens, also before the
    ledger exists (the ledger, created by the first smoke or launch, freezes the
    plan)."""
    target = manifest.runtime_subdir("inventories") / "storage-log.jsonl"
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(target, "a") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    return target


def _existing_ledger(manifest: Manifest) -> Ledger | None:
    if not manifest.ledger_path().exists():
        return None
    return Ledger.load(manifest.ledger_path(), campaign_id=manifest.campaign_id, manifest_sha256=manifest.sha256)


def _ledger(manifest: Manifest) -> Ledger:
    return Ledger.open_or_create(
        manifest.ledger_path(), campaign_id=manifest.campaign_id, manifest_sha256=manifest.sha256,
        manifest_path=paths.display(manifest.path) if manifest.path else "")


def _active_evaluations(manifest: Manifest, ledger: Ledger, client: api_mod.AgentForgeApi | None) -> list[str]:
    busy = [f"ledger:{e['cell']}" for e in ledger.active_entries() if e["state"] in (SUBMITTED, SUBMITTING)]
    if manifest.db_path().exists():
        conn = cohort.open_readonly(manifest.db_path())
        try:
            busy += cohort.active_evaluations(conn)
        finally:
            conn.close()
    if client is not None:
        try:
            busy += [j.get("id") for j in client.list_jobs() if j.get("status") in ("queued", "running")]
        except api_mod.ApiError:
            pass  # the app is not running: nothing can be executing through it
    return sorted(set(busy))


def _db_busy(manifest: Manifest, client: api_mod.AgentForgeApi | None) -> list[str]:
    busy: list[str] = []
    if manifest.db_path().exists():
        conn = cohort.open_readonly(manifest.db_path())
        try:
            busy += cohort.active_evaluations(conn)
        finally:
            conn.close()
    if client is not None:
        try:
            busy += [j.get("id") for j in client.list_jobs() if j.get("status") in ("queued", "running")]
        except api_mod.ApiError:
            pass
    return sorted(set(busy))


def pinned_ollama_version(manifest: Manifest) -> str | None:
    return (manifest.data.get("execution") or {}).get("ollama_server_version")


def _require_campaign_plan(manifest: Manifest, what: str) -> None:
    """Model files are only ever managed under the campaign's OWN sequential plan
    (never the historical plan, never a derived smoke/rehearsal plan, whose rosters
    do not list every campaign target)."""
    if not manifest.is_sequential or manifest.data.get("derived_from"):
        raise CampaignStop(f"{what} applies only to a sequential-local campaign's own plan (pass --manifest "
                           "campaigns/phase0-modern-local-v1/manifest.json); this plan is "
                           f"{'derived' if manifest.data.get('derived_from') else manifest.kind}")


def _check_server_version(manifest: Manifest, what: str) -> str | None:
    pinned = pinned_ollama_version(manifest)
    try:
        version = (_ollama_call(manifest.backend["base_url"], "GET", "/api/version") or {}).get("version")
    except ollama.OllamaError as exc:
        raise CampaignStop(f"Ollama is not reachable ({exc}); {what} needs it") from None
    if pinned and version != pinned:
        raise CampaignStop(f"Ollama server version is {version!r}, the frozen plan pins {pinned!r}: {what} refused "
                           "(one cohort never mixes inference engines; a different server needs a new campaign id)")
    return version


def live_smoke_apps(manifest: Manifest) -> list[int]:
    """Process groups of smoke apps still alive (pidfiles written by run_smoke)."""
    alive = []
    folder = manifest.runtime_subdir("smoke_dir") if manifest.is_sequential else None
    for pidfile in (sorted(folder.glob("*/app.pgid")) if folder and folder.exists() else []):
        try:
            pgid = int(pidfile.read_text().strip())
            os.killpg(pgid, 0)
        except (ValueError, OSError):
            continue
        alive.append(pgid)
    return alive


def phase_finished(manifest: Manifest, ledger: Ledger, phase: str) -> str | None:
    """Why a phase's model weights are no longer needed: a frozen receipt that
    still validates (and names exactly the active evaluations), or a
    classification. None = still needed."""
    status = (ledger.data.get("model_status") or {}).get(phase)
    if status:
        return f"classified {status['status']}"
    record = (ledger.data.get("receipts") or {}).get(phase)
    if not record:
        return None
    path = paths.resolve(record["path"])
    if not path.exists() or file_sha256(path) != record["sha256"]:
        return None
    try:
        frozen = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    active = [(ledger.active_entry(c.key) or {}).get("evaluation_id") for c in manifest.cells(phase)]
    if frozen.get("evaluation_ids") != active:
        return None
    receipt = validate_mod.validate_campaign(manifest, phase=phase)
    if not receipt["complete"]:
        return None
    return (f"receipt {record['path']} (sha256 {record['sha256'][:12]}...) frozen with "
            f"{record['accepted_runs']} accepted runs; re-validated complete")


# --------------------------------------------------------------------------- #
# inventory
# --------------------------------------------------------------------------- #


def storage_inventory(manifest: Manifest, label: str) -> tuple[dict, Path]:
    import re

    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", label or "") or ".." in label:
        raise CampaignStop(f"inventory label {label!r} must be a plain name (letters, digits, '.', '_', '-')")
    target = manifest.runtime_subdir("inventories") / f"{label}.json"
    if target.exists():
        raise CampaignStop(f"inventory {paths.display(target)} already exists; inventories are never overwritten")
    base = manifest.backend["base_url"]
    models_dir = ollama_models_dir()
    try:
        version = (_ollama_call(base, "GET", "/api/version") or {}).get("version")
        models = ollama_models(base)
        reachable = True
    except ollama.OllamaError as exc:
        version, models, reachable = None, [], str(exc)
    roster = {e["model"]: e for e in manifest.data.get("roster") or []}
    for model in models:
        entry = roster.get(model["name"])
        model["campaign_target"] = entry["phase"] if entry else None
        model["mlx"] = model.get("format") == "safetensors" or str(model["name"]).endswith("-mlx")
    others = other_model_weights()
    reclaimable_ollama = sum(m["size_bytes"] or 0 for m in models if not m["campaign_target"])
    reclaimable_mlx = sum(w["bytes"] for w in others if w["kind"] == "mlx")
    inventory = {
        "label": label,
        "captured_at": utc_now(),
        "campaign_id": manifest.campaign_id,
        "disk": {"volume_of": _home(models_dir), **disk_free(models_dir)},
        "ollama": {"reachable": reachable, "version": version, "models_dir": _home(models_dir),
                   "models_dir_bytes": _dir_bytes(models_dir) if models_dir.exists() else 0,
                   "models": models,
                   "total_model_bytes": sum(m["size_bytes"] or 0 for m in models)},
        "other_model_weights": others,
        "reclaimable_estimate_bytes": {
            "ollama_non_target_models": reclaimable_ollama,
            "mlx_weights_outside_ollama": reclaimable_mlx,
            "note": "authorized removals: Ollama models and MLX weights; other weights only if clearly model "
                    "data and necessary; never anything else",
        },
        "roster": [{"phase": e["phase"], "model": e["model"],
                    "installed": any(m["name"] == e["model"] for m in models),
                    "download_bytes": e["expected_identity"]["download_bytes"]}
                   for e in manifest.data.get("roster") or []],
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(inventory, indent=2) + "\n")
    return inventory, target


# --------------------------------------------------------------------------- #
# pull / remove / classify
# --------------------------------------------------------------------------- #


def pull_model(manifest: Manifest, phase: str, *, client: api_mod.AgentForgeApi | None = None,
               log=print, margin_bytes: int = PULL_MARGIN_BYTES, pull=None) -> dict:
    """Install ONLY the phase's target (or reuse it). Never pulls a second
    unfinished target; the pulled digest must equal the frozen pin."""
    _require_campaign_plan(manifest, "pull-model")
    entry = manifest.phase_entry(phase)
    model, base = entry["model"], manifest.backend["base_url"]
    pinned = normalize_digest(entry["expected_identity"]["digest"])
    _check_server_version(manifest, "pull-model")
    with ledger_lock(manifest.ledger_path()):
        ledger = _ledger(manifest)
        if phase in (ledger.data.get("model_status") or {}):
            raise CampaignStop(f"{model} ({phase}) is classified; it is not installed for the campaign")
        installed = {m["name"]: m for m in ollama_models(base)}
        if model in installed:
            digest = normalize_digest(installed[model]["digest"])
            if digest != pinned:
                raise CampaignStop(f"STOP - {model} is installed with digest {digest}, the frozen plan pins "
                                   f"{pinned}: ambiguous identity (never benchmarked, never overwritten blindly)")
            record = ledger.record("model_pulls", {"phase": phase, "model": model, "outcome": "reused",
                                                   "digest": digest, "bytes": installed[model]["size_bytes"],
                                                   "at": utc_now()})
            ledger.save()
            log(f"{model} is already installed with the pinned digest: reused, not downloaded")
            return record
        # an unfinished target = another roster model installed WITH its pinned digest
        # whose batch is not finished (non-pinned weights can never become evidence)
        unfinished = [e["model"] for e in manifest.data["roster"]
                      if e["phase"] != phase and e["model"] in installed
                      and normalize_digest(installed[e["model"]]["digest"]) == manifest.pinned_digests()[e["model"]]
                      and not phase_finished(manifest, ledger, e["phase"])]
        if unfinished:
            raise CampaignStop(f"one target at a time: {', '.join(unfinished)} is installed and its batch is not "
                               "finished (no frozen receipt, no classification)")
        busy = _active_evaluations(manifest, ledger, client)
        if busy:
            raise CampaignStop(f"evaluations are active ({busy}); never pull while a benchmark runs")
        need = entry["expected_identity"]["download_bytes"] + margin_bytes
        if not ollama_models_dir().exists():
            raise CampaignStop(f"Ollama models directory {_home(ollama_models_dir())} does not exist (set OLLAMA_MODELS "
                               "to the server's models directory)")
        free_before = disk_free()["free_bytes"]
        if free_before < need:
            raise CampaignStop(
                f"{model} needs {need / GIB:.1f} GiB free (download {entry['expected_identity']['download_bytes'] / GIB:.1f} "
                f"GiB + {margin_bytes / GIB:.0f} GiB margin); only {free_before / GIB:.1f} GiB is free. Remove authorized "
                "model weights first (remove-model), then pull again")
        started = utc_now()
        storage_log(manifest, {"action": "pull-model", "phase": phase, "model": model, "pinned_digest": pinned,
                               "download_bytes": entry["expected_identity"]["download_bytes"],
                               "free_bytes_before": free_before, "at": started})
        ledger.event("model_pull_started", phase=phase, model=model, free_bytes=free_before)
        ledger.save()
        log(f"pulling {model} ({entry['expected_identity']['download_bytes'] / 1e9:.2f} GB) ...")
        try:
            (pull or _pull_stream)(base, model, log)
        except (CampaignStop, ollama.OllamaError, urllib.error.URLError, OSError, ValueError) as exc:
            failed = {"phase": phase, "model": model, "outcome": "failed", "error": str(exc)[:500],
                      "started_at": started, "finished_at": utc_now(), "free_bytes_after": disk_free()["free_bytes"]}
            ledger.record("model_pulls", failed)
            ledger.save()
            storage_log(manifest, {"action": "pull-model-result", **failed})
            raise CampaignStop(f"pull of {model} failed: {exc}") from None
        after = {m["name"]: m for m in ollama_models(base)}
        got = after.get(model)
        digest = normalize_digest(got["digest"]) if got else None
        record = {"phase": phase, "model": model, "outcome": "pulled" if digest == pinned else "IDENTITY MISMATCH",
                  "digest": digest, "pinned_digest": pinned, "bytes": got["size_bytes"] if got else None,
                  "started_at": started, "finished_at": utc_now(), "free_bytes_before": free_before,
                  "free_bytes_after": disk_free()["free_bytes"],
                  "ollama_version": (_ollama_call(base, "GET", "/api/version") or {}).get("version")}
        ledger.record("model_pulls", record)
        ledger.save()
        storage_log(manifest, {"action": "pull-model-result", **record})
        if digest != pinned:
            raise CampaignStop(f"STOP - pulled {model} has digest {digest}, the frozen plan pins {pinned}: the tag "
                               "moved upstream; ambiguous identity, not benchmarked")
        return record


def _pull_stream(base_url: str, model: str, log) -> None:
    req = urllib.request.Request(base_url.rstrip("/") + "/api/pull", method="POST",
                                 data=json.dumps({"model": model, "stream": True}).encode(),
                                 headers={"content-type": "application/json"})
    last = -10.0
    with urllib.request.urlopen(req, timeout=3600) as resp:
        for raw in resp:
            line = json.loads(raw or b"{}")
            if line.get("error"):
                raise CampaignStop(f"pull of {model} failed: {line['error']}")
            total, done = line.get("total"), line.get("completed")
            if total and done is not None:
                pct = 100.0 * done / total
                if pct - last >= 10 or pct >= 100:
                    last = pct
                    log(f"  {line.get('status', '')[:30]} {pct:5.1f}% of {total / 1e9:.2f} GB")
            elif line.get("status") == "success":
                log("  pull complete")


def _unload(base_url: str, model: str) -> None:
    _ollama_call(base_url, "POST", "/api/generate", {"model": model, "prompt": "", "keep_alive": 0,
                                                    "stream": False}, timeout=120)


def remove_model(manifest: Manifest, model: str, reason: str, *, client: api_mod.AgentForgeApi | None = None,
                 log=print, delete=None) -> dict:
    """Remove one Ollama model's weights, recorded BEFORE the removal. A roster
    model only after its evidence is frozen (receipt re-validates) or it was
    classified; never the active target, never while anything runs."""
    if not (reason and reason.strip()):
        raise LedgerError("removing a model requires a written reason")
    _require_campaign_plan(manifest, "remove-model")
    base = manifest.backend["base_url"]
    with ledger_lock(manifest.ledger_path()):
        ledger = _existing_ledger(manifest)  # never created by a removal
        installed = {m["name"]: m for m in ollama_models(base)}
        if model not in installed:
            raise CampaignStop(f"{model} is not installed in Ollama; nothing to remove")
        roster = {e["model"]: e for e in manifest.data.get("roster") or []}
        if model in roster and normalize_digest(installed[model]["digest"]) != manifest.pinned_digests()[model]:
            # weights that are NOT the pinned identity can never be campaign evidence
            evidence_status = (f"campaign target {roster[model]['phase']} installed with NON-PINNED weights "
                               f"{normalize_digest(installed[model]['digest'])} (pin "
                               f"{manifest.pinned_digests()[model]}): never campaign evidence")
        elif model in roster:
            finished = phase_finished(manifest, ledger, roster[model]["phase"]) if ledger else None
            if not finished:
                raise CampaignStop(f"{model} is campaign target {roster[model]['phase']} and its evidence is not "
                                   "frozen yet (validate, then model-receipt): its weights are still needed")
            evidence_status = finished
        else:
            evidence_status = "not a campaign model (no campaign evidence depends on it)"
        busy = _active_evaluations(manifest, ledger, client) if ledger else _db_busy(manifest, client)
        if busy:
            raise CampaignStop(f"evaluations are active ({busy}); never remove a model while a benchmark runs")
        alive = live_smoke_apps(manifest)
        if alive:
            raise CampaignStop(f"a smoke app is still running (process groups {alive}); never remove a model then")
        loaded = [m.get("name") for m in (_ollama_call(base, "GET", "/api/ps") or {}).get("models", [])]
        if model in loaded:
            _unload(base, model)
            if model in [m.get("name") for m in (_ollama_call(base, "GET", "/api/ps") or {}).get("models", [])]:
                raise CampaignStop(f"{model} is still loaded in Ollama; try again when it is idle")
        db = manifest.db_path()
        before = {"db_sha256": file_sha256(db) if db.exists() else None}
        free_before = disk_free()["free_bytes"]
        info = installed[model]
        record = {"model": model, "runtime": "ollama", "digest": info["digest"], "size_bytes": info["size_bytes"],
                  "format": info.get("format"), "reason": reason.strip(), "evidence_status": evidence_status,
                  "campaign_target": roster.get(model, {}).get("phase"), "free_bytes_before": free_before,
                  "requested_at": utc_now(), "outcome": "requested"}
        storage_log(manifest, {"action": "remove-model", **record})
        if ledger is not None:
            ledger.record("model_deletions", record)
            ledger.save()  # recorded BEFORE the weights are removed
        (delete or (lambda name: _ollama_call(base, "DELETE", "/api/delete", {"model": name, "name": name})))(model)
        remaining = {m["name"] for m in ollama_models(base)}
        record["outcome"] = "removed" if model not in remaining else "STILL PRESENT"
        record["free_bytes_after"] = disk_free()["free_bytes"]
        record["reclaimed_bytes"] = record["free_bytes_after"] - free_before
        record["completed_at"] = utc_now()
        if db.exists() and before["db_sha256"] and file_sha256(db) != before["db_sha256"]:
            record["note"] = "the campaign database changed during the removal (the app wrote to it)"
        storage_log(manifest, {"action": "remove-model-result", **record})
        if ledger is not None:
            ledger.save()
        log(f"removed {model}: {record['outcome']}, reclaimed {record['reclaimed_bytes'] / GIB:.1f} GiB "
            f"({evidence_status})")
        return record


def classify_model(manifest: Manifest, phase: str, status: str, reason: str, evidence: str, *,
                   after_results: bool = False) -> dict:
    _require_campaign_plan(manifest, "classify-model")
    entry = manifest.phase_entry(phase)
    with ledger_lock(manifest.ledger_path()):
        ledger = _ledger(manifest)
        in_flight = [e["cell"] for e in ledger.active_entries()
                     if e["phase"] == phase and e["state"] in (SUBMITTED, SUBMITTING)]
        if in_flight:
            raise CampaignStop(f"{entry['model']} has evaluations in flight ({in_flight}); finish or halt them first")
        receipt = validate_mod.validate_campaign(manifest, phase=phase)
        if receipt["complete"]:
            raise CampaignStop(f"{entry['model']} ({phase}) completed its batch: it is ranked, not classified")
        accepted = receipt["present"]["cells_complete"]
        if accepted and not after_results:
            raise CampaignStop(f"{entry['model']} ({phase}) already has {accepted} accepted cell(s): classifying it now "
                               "excludes evidence after results were visible. Pass --after-results to do it anyway; "
                               "it is disclosed in the leaderboard")
        record = ledger.classify_model(phase=phase, model=entry["model"], status=status, reason=reason,
                                       evidence=evidence)
        record["accepted_cells_at_classification"] = accepted
        record["accepted_runs_at_classification"] = receipt["present"]["runs"]
        ledger.save()
        return record


# --------------------------------------------------------------------------- #
# model receipt
# --------------------------------------------------------------------------- #


def _slug(model: str) -> str:
    return model.replace(":", "-").replace("/", "-")


def model_receipt(manifest: Manifest, phase: str, *, reissue: bool = False) -> tuple[dict, Path]:
    """The frozen per-model receipt; refused unless the phase validates complete.
    A frozen receipt is never overwritten silently: ``reissue`` keeps the
    previous version beside the new one."""
    import afa_runner as afa
    from afa_kernel.confidence import wilson_interval

    from .analysis import _scratch_store

    entry = manifest.phase_entry(phase)
    model = entry["model"]
    receipt = validate_mod.validate_campaign(manifest, phase=phase)
    if not receipt["complete"]:
        raise CampaignStop(f"{model} ({phase}) does not validate complete; no receipt: "
                           + "; ".join(receipt["problems"][:5] or [f"missing {receipt['missing']['cells']}"]))
    with ledger_lock(manifest.ledger_path()):
        ledger = Ledger.load(manifest.ledger_path(), campaign_id=manifest.campaign_id,
                             manifest_sha256=manifest.sha256)
        conn = cohort.open_readonly(manifest.db_path())
        cells, records = [], []
        try:
            for cell in manifest.cells(phase):
                active = ledger.active_entry(cell.key)
                check = cohort.check_cell_evaluation(conn, manifest, cell, active["evaluation_id"])
                cells.append({
                    "cell": cell.key, "task_id": cell.task_id,
                    "task_version": manifest.task_by_id[cell.task_id]["task_version"],
                    "task_digest": manifest.task_by_id[cell.task_id]["task_digest"],
                    "evaluation_id": active["evaluation_id"], "run_ids": check.run_ids,
                    "passed": check.passed, "valid": check.valid, "voided": check.voided,
                    "timeouts": check.timeouts, "agent_errors": check.agent_errors,
                    "request_timeout_hits": check.request_timeout_hits,
                    "final_scores": [check.positions[i]["final_score"] for i in sorted(check.positions)],
                    "submitted_at": active.get("created_at"), "finished_at": active.get("finished_at"),
                    "model_digest_at_submit": active.get("model_digest_at_submit"),
                    "model_digest_at_finalize": active.get("model_digest_at_finalize"),
                    "ollama_version": active.get("ollama_version_at_finalize"),
                })
                records += cohort.load_cell_records(manifest.db_path(), check)
        finally:
            conn.close()
        passes = sum(c["passed"] for c in cells)
        valid = sum(c["valid"] for c in cells)
        low, high = wilson_interval(passes, valid)
        scores = [s for c in cells for s in c["final_scores"] if s is not None]
        store = _scratch_store(records)
        try:
            board = [e for e in afa.leaderboard(store) if e.agent == model]
            kernel = board[0] if board else None
        finally:
            store.close()
        launches = [l for l in ledger.data["launches"] if l.get("model") == model]
        inventory = next(((l.get("inventory") or {}).get("models", {}).get(model) for l in launches
                          if (l.get("inventory") or {}).get("models", {}).get(model, {}).get("present")), None)
        digests = sorted({c["model_digest_at_submit"] for c in cells} | {c["model_digest_at_finalize"] for c in cells})
        result = {
            "receipt_kind": "model",
            "campaign_id": manifest.campaign_id,
            "manifest_sha256": manifest.sha256,
            "phase": phase,
            "model": model,
            "logical_name": entry["logical_name"],
            "optional": entry["optional"],
            "expected_identity": entry["expected_identity"],
            "observed_identity": {
                "digests": digests,
                "digest_matches_pin": digests == [normalize_digest(entry["expected_identity"]["digest"])],
                "ollama_versions": sorted({c["ollama_version"] for c in cells}),
                "reference_ollama_version": reference_ollama_version(ledger),
                "ollama_details": (inventory or {}).get("details"),
                "ollama_size_bytes": (inventory or {}).get("size"),
            },
            "agentforge_release": {"tag": manifest.data["code"]["runtime_release_tag"],
                                   "commit": manifest.data["code"]["runtime_release_commit"]},
            "tooling_heads": sorted({l.get("tooling_head") for l in launches if l.get("tooling_head")}),
            "generation": manifest.generation,
            "tasks": len(cells),
            "expected_runs": receipt["expected"]["runs"],
            "accepted_runs": receipt["present"]["runs"],
            "evaluation_ids": [c["evaluation_id"] for c in cells],
            "totals": {"passed": passes, "valid": valid, "voided": sum(c["voided"] for c in cells),
                       "timeouts": sum(c["timeouts"] for c in cells),
                       "agent_errors": sum(c["agent_errors"] for c in cells),
                       "request_timeout_hits": sum(c["request_timeout_hits"] for c in cells)},
            "aggregate": {"pass_rate": passes / valid if valid else None, "wilson_low": low, "wilson_high": high,
                          "mean_final_score": sum(scores) / len(scores) if scores else None,
                          "kernel_leaderboard_entry": None if kernel is None else {
                              "n": kernel.n, "pass_rate": kernel.pass_rate, "wilson_low": kernel.wilson_low,
                              "wilson_high": kernel.wilson_high}},
            "started_at": min(c["submitted_at"] for c in cells if c["submitted_at"]),
            "finished_at": max(c["finished_at"] for c in cells if c["finished_at"]),
            "smoke": [s for s in ledger.data.get("smokes", []) if s.get("phase") == phase],
            "validation": {"complete": True, "problems": receipt["problems"], "warnings": receipt["warnings"],
                           "evidence_classes": receipt["evidence_classes"],
                           "historical_evidence_sha256": receipt["historical_evidence_sha256"]},
            "cells": cells,
            "generated_at": utc_now(),
        }
        folder = manifest.runtime_subdir("receipts")
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / f"{phase}-{_slug(model)}.json"
        if target.exists():
            if not reissue:
                raise CampaignStop(f"{paths.display(target)} is already frozen; pass --reissue to issue a new version "
                                   "(the previous one is kept)")
            stamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            for suffix in (".json", ".md"):
                old = target.with_suffix(suffix)
                if old.exists():
                    old.rename(old.with_name(f"{old.stem}.superseded-{stamp}{suffix}"))
            result["supersedes"] = (ledger.data.get("receipts") or {}).get(phase)
        target.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
        (folder / f"{phase}-{_slug(model)}.md").write_text(render_model_receipt(result))
        ledger.data.setdefault("receipts", {})[phase] = {
            "path": paths.display(target), "sha256": file_sha256(target), "at": utc_now(), "model": model,
            "accepted_runs": result["accepted_runs"], "digest": digests[0] if len(digests) == 1 else digests}
        ledger.event("model_receipt", phase=phase, model=model, accepted_runs=result["accepted_runs"])
        ledger.save()
        return result, target


def render_model_receipt(r: dict) -> str:
    agg, tot, ident = r["aggregate"], r["totals"], r["observed_identity"]
    rate = "-" if agg["pass_rate"] is None else f"{agg['pass_rate']:.3f}"
    lines = [
        f"# Model receipt - {r['logical_name']} (`{r['model']}`), {r['campaign_id']} phase {r['phase']}", "",
        f"- Accepted runs: **{r['accepted_runs']} / {r['expected_runs']}** ({r['tasks']} tasks x "
        f"{r['generation'] and r['expected_runs'] // max(1, r['tasks'])} repetitions), validation complete.",
        f"- Passes: {tot['passed']} / {tot['valid']} (pass rate {rate}, Wilson 95% "
        f"[{agg['wilson_low']:.3f}, {agg['wilson_high']:.3f}]); timeouts {tot['timeouts']}; agent errors "
        f"{tot['agent_errors']}; voided {tot['voided']}.",
        f"- Model digest {', '.join(ident['digests'])} (matches the frozen pin: {ident['digest_matches_pin']}); "
        f"Ollama {', '.join(v for v in ident['ollama_versions'] if v)}; quantization "
        f"{r['expected_identity'].get('quantization')}, {r['expected_identity'].get('parameter_size')} parameters.",
        f"- AgentForge release `{r['agentforge_release']['tag']}` ({r['agentforge_release']['commit']}); "
        f"manifest {r['manifest_sha256']}.",
        f"- Generation: temperature {r['generation']['temperature']}, base seed {r['generation']['base_seed']}, "
        f"request timeout {r['generation']['request_timeout_s']} s.",
        f"- Window: {r['started_at']} -> {r['finished_at']}.", "",
        "| task (version) | evaluation | passed/valid | timeouts |", "|---|---|---|---|",
    ]
    lines += [f"| {c['task_id']} ({c['task_version']}) | `{c['evaluation_id']}` | {c['passed']}/{c['valid']} | "
              f"{c['timeouts']} |" for c in r["cells"]]
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- #
# smoke
# --------------------------------------------------------------------------- #


def _memory_snapshot() -> dict:
    out = {}
    for name, cmd in (("swap", ["sysctl", "-n", "vm.swapusage"]), ("pressure", ["memory_pressure", "-Q"])):
        try:
            out[name] = subprocess.run(cmd, capture_output=True, text=True, timeout=20).stdout.strip()[:300]
        except (OSError, subprocess.SubprocessError) as exc:
            out[name] = f"unavailable: {exc}"
    return out


def _stop(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        process.wait(timeout=30)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=30)


def run_smoke(manifest: Manifest, phase: str, *, port: int = 8792, log=print, tasks: list[str] | None = None,
              start_app=None) -> dict:
    """4 tasks x 1 repetition of the phase's model through the real ATLAS
    lifecycle, in a SCRATCH database with its own campaign id, app and ledger.
    Recorded in the main ledger (also when it fails); never campaign evidence."""
    _require_campaign_plan(manifest, "smoke")
    entry = manifest.phase_entry(phase)
    model = entry["model"]
    smoke_tasks = tasks or list(manifest.data["execution"]["smoke"]["tasks"])
    stamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    folder = manifest.runtime_subdir("smoke_dir") / f"{phase}-{stamp}"
    smoke_id = f"{manifest.campaign_id}-smoke-{phase}-{stamp.lower()}"
    # derive (and validate) the scratch plan BEFORE touching the main ledger
    data = derive_subset(manifest.data, campaign_id=smoke_id, models=[model], task_ids=smoke_tasks,
                         repetitions=int(manifest.data["execution"]["smoke"]["repetitions"]),
                         campaign_db=paths.display(folder / "smoke.sqlite"), runtime_dir=paths.display(folder),
                         api_url=f"http://127.0.0.1:{port}",
                         purpose=f"operational smoke of {model} (NOT campaign evidence)")
    version = _check_server_version(manifest, "smoke")
    if live_smoke_apps(manifest):
        raise CampaignStop(f"a smoke app is still running ({live_smoke_apps(manifest)}); stop it first")
    with ledger_lock(manifest.ledger_path()):
        ledger = _ledger(manifest)
        busy = _active_evaluations(manifest, ledger, None)
        if busy:
            raise CampaignStop(f"campaign evaluations are active ({busy}); a smoke never runs beside them")
        dump(data, folder / "smoke.manifest.json")
        smoke = Manifest.load(folder / "smoke.manifest.json")
        init_db(smoke)
        record = {"phase": phase, "model": model, "smoke_campaign_id": smoke_id, "scratch": paths.display(folder),
                  "tasks": smoke_tasks, "started_at": utc_now(), "ollama_version": version,
                  "operational_ok": False, "outcome": "started", "failure": None,
                  "memory_before": _memory_snapshot(),
                  "note": "operational check only: a low score is not a smoke failure; never campaign evidence"}
        app = None
        previous = {sig: signal.getsignal(sig) for sig in (signal.SIGTERM, signal.SIGHUP)}

        def _interrupted(signum, _frame):
            raise KeyboardInterrupt(f"smoke interrupted by signal {signum}")

        try:
            for sig in previous:
                signal.signal(sig, _interrupted)
            app = (start_app or _start_app)(smoke.db_path(), port, folder / "app.log")
            (folder / "app.pgid").write_text(str(app.pid))
            _wait_healthy(f"http://127.0.0.1:{port}", 240)
            try:
                Launcher(smoke, api_mod.AgentForgeApi(smoke.api_url), log=log, poll_s=2.0).run(phase)
                record["outcome"] = "ok"
            except CampaignStop as exc:
                record["outcome"], record["failure"] = "halted", str(exc)[:2000]
            try:
                ps = (_ollama_call(manifest.backend["base_url"], "GET", "/api/ps") or {}).get("models", [])
                record["ollama_ps"] = [{k: m.get(k) for k in ("name", "size", "size_vram", "digest")} for m in ps]
            except ollama.OllamaError as exc:
                record["ollama_ps"] = f"unavailable: {exc}"
        except BaseException as exc:  # noqa: BLE001 - recorded, then re-raised
            record["outcome"], record["failure"] = "error", f"{type(exc).__name__}: {exc}"[:2000]
            raise
        finally:
            if app is not None:
                _stop(app)
                (folder / "app.pgid").unlink(missing_ok=True)
            for sig, handler in previous.items():
                signal.signal(sig, handler)
            _finish_smoke_record(record, smoke, phase)
            ledger.record("smokes", record)
            ledger.save()
        return record


def _finish_smoke_record(record: dict, smoke: Manifest, phase: str) -> None:
    receipt = validate_mod.validate_campaign(smoke, phase=phase)
    smoke_ledger = Ledger.load(smoke.ledger_path()) if smoke.ledger_path().exists() else None
    cells = []
    for cell in smoke.cells(phase):
        active = (smoke_ledger.active_entry(cell.key) if smoke_ledger else None) or {}
        cells.append({"cell": cell.key, "state": active.get("state", "not_started"),
                      "evaluation_id": active.get("evaluation_id"), "summary": active.get("summary"),
                      "problems": active.get("problems")})
    digests = {normalize_digest(e.get("model_digest_at_finalize") or e.get("model_digest_at_submit"))
               for e in (smoke_ledger.active_entries() if smoke_ledger else [])} - {None}
    record.update({
        "finished_at": utc_now(), "cells": cells,
        "digest": next(iter(digests)) if len(digests) == 1 else (sorted(digests) or None),
        "passed": sum((c["summary"] or {}).get("passed", 0) for c in cells),
        "valid": sum((c["summary"] or {}).get("valid", 0) for c in cells),
        "evidence_classes": receipt["evidence_classes"], "smoke_problems": receipt["problems"][:20],
        "memory_after": _memory_snapshot(),
        "operational_ok": record["outcome"] == "ok" and receipt["complete"],
    })


def _start_app(db_path: Path, port: int, log_path: Path) -> subprocess.Popen:
    env = {**os.environ, "AFA_DB_PATH": str(db_path), "AFA_PORT": str(port), "AFA_NO_BROWSER": "1"}
    handle = open(log_path, "ab")
    return subprocess.Popen([sys.executable, "afa_app.py"], cwd=str(paths.REPO), env=env, stdout=handle,
                            stderr=subprocess.STDOUT, start_new_session=True)


def _wait_healthy(base: str, limit_s: float) -> None:
    client = api_mod.AgentForgeApi(base)
    deadline = time.monotonic() + limit_s
    while time.monotonic() < deadline:
        try:
            if client.health().get("status") == "ok":
                return
        except api_mod.ApiError:
            pass
        time.sleep(1.0)
    raise CampaignStop(f"the smoke app at {base} did not become healthy within {limit_s:.0f}s")
