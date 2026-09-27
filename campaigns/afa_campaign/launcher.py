"""Campaign launcher: preflight, clean-DB initialisation, resumable execution.

Execution model
---------------
* One evaluation per (model, task) cell, created through ``POST /api/v1/jobs`` on
  a running AgentForge app bound to the campaign database. Evaluations run ONE AT
  A TIME: the launcher waits for each to reach a terminal state before submitting
  the next, so the model server never serves two campaign trials concurrently.
* The ledger entry is written BEFORE the POST (state ``submitting``) and gets
  the evaluation id right after it. A crash in between is reconciled on restart
  by the evaluation's persisted name; two evaluations with one name halt the
  campaign as duplicates.
* Restarting is always safe: succeeded cells are skipped, an in-flight
  evaluation is waited for (an app restart recovers it under the SAME id through
  ATLAS startup recovery), and failed / canceled / rejected / needs-attention
  cells HALT the launcher until an operator resumes or supersedes them.
* Completion is decided from campaign-owned evaluations only, never from the
  mere presence of runs for a model and task.

Halting conditions (``CampaignStop``): preflight failure; a task's version or
digest differs from the frozen manifest (STOP THE CAMPAIGN); a roster model's
Ollama digest, or the Ollama server version, changes; an evaluation fails, is
canceled or is unverifiable; an evaluation's evidence fails a campaign check
(provenance / version / digest / parameters: its evidence is excluded);
infrastructure-voided positions; an evaluation of this campaign that the ledger
does not own; another evaluation queued or running on the app, or running
concurrently with a campaign evaluation; a campaign evaluation resumed outside
this tooling.
"""

from __future__ import annotations

import functools
import json
import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import api as api_mod
from . import cohort, ollama, paths
from . import validate as validate_mod
from .ledger import (
    CANCELED, FAILED, HALTING, NEEDS_ATTENTION, REJECTED, SUBMITTED, SUBMITTING, SUCCEEDED,
    Ledger, LedgerError, ledger_lock, utc_now,
)
from .manifest import Cell, Manifest, evidence_sha256, normalize_digest

from afa_api import db as app_db  # noqa: E402
from afa_api import jobs  # noqa: E402

TERMINAL = ("succeeded", "failed", "canceled")
UNVERIFIABLE_PREFIX = "invalid persisted evaluation parameters"


class CampaignStop(RuntimeError):
    """A halting condition. The message says what happened and what to do."""


@dataclass
class Preflight:
    problems: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    facts: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.problems


# --------------------------------------------------------------------------- #
# Checks
# --------------------------------------------------------------------------- #


@functools.lru_cache(maxsize=1)
def git_executable() -> str:
    """A git binary that actually runs here.

    The first ``git`` on PATH is not always usable (for example an Intel-only
    Homebrew build left behind on an Apple-silicon machine fails with "bad CPU
    type"), and a silently failing git would make every code check fail.
    ``AFA_GIT`` overrides the choice.
    """
    for candidate in (os.environ.get("AFA_GIT"), shutil.which("git"), "/usr/bin/git"):
        if not candidate:
            continue
        try:
            probe = subprocess.run([candidate, "--version"], capture_output=True, text=True, timeout=30)
        except OSError:
            continue
        if probe.returncode == 0:
            return candidate
    raise CampaignStop("no working git executable found (set AFA_GIT)")


def _git(*args: str) -> tuple[int, str]:
    proc = subprocess.run([git_executable(), "-C", str(paths.REPO), *args], capture_output=True, text=True)
    return proc.returncode, proc.stdout.strip()


def check_runtime_code(manifest: Manifest) -> tuple[list[str], dict]:
    """The executed runtime (afa_api, runner, kernel, tasks) must be exactly the
    pinned release: identical to the tag's tree and free of local changes."""
    code = manifest.data["code"]
    tag, commit = code["runtime_release_tag"], code["runtime_release_commit"]
    runtime_paths = list(code.get("runtime_paths") or paths.RUNTIME_PATHS)
    problems: list[str] = []
    rc, head = _git("rev-parse", "HEAD")
    facts = {"head": head if rc == 0 else None, "tag": tag, "release_commit": commit}
    rc, tagged = _git("rev-parse", "--verify", "--quiet", f"refs/tags/{tag}^{{commit}}")
    if rc != 0:
        problems.append(f"release tag {tag!r} is not present locally (git fetch --tags)")
    elif tagged != commit:
        problems.append(f"release tag {tag} points at {tagged}, manifest pins {commit}")
    rc, _ = _git("cat-file", "-e", f"{commit}^{{commit}}")
    if rc != 0:
        problems.append(f"pinned release commit {commit} is not present locally")
    else:
        rc, _ = _git("diff", "--quiet", commit, "HEAD", "--", *runtime_paths)
        if rc != 0:
            problems.append(
                f"runtime paths {runtime_paths} differ between HEAD and the pinned release {commit[:12]}"
            )
    rc, dirty = _git("status", "--porcelain", "--untracked-files=all", "--", *runtime_paths)
    if rc == 0 and dirty:
        problems.append(
            "uncommitted or untracked files in runtime paths (they would change task digests "
            f"or executed code):\n      {dirty.replace(chr(10), chr(10) + '      ')}"
        )
    return problems, facts


def same_path(a: str | Path, b: str | Path) -> bool:
    """Same file? (samefile when both exist: macOS volumes are case-insensitive)."""
    try:
        if os.path.exists(a) and os.path.exists(b):
            return os.path.samefile(a, b)
    except OSError:
        pass
    return Path(a).expanduser().resolve() == Path(b).expanduser().resolve()


def reference_digests(ledger: Ledger | None, manifest: Manifest | None = None) -> dict[str, str]:
    """The campaign's model identities. A sequential-local plan PINS each model's
    registry digest in the frozen manifest (models are installed one at a time,
    so no single launch sees them all); otherwise the digests recorded by the
    campaign's FIRST launch."""
    if manifest is not None and manifest.is_sequential:
        return manifest.pinned_digests()
    for launch in (ledger.data["launches"] if ledger else []):
        if launch.get("inventory"):
            return {m: d for m, d in ollama.digests(launch["inventory"]).items() if d}
    return {}


def reference_ollama_version(ledger: Ledger | None) -> str | None:
    """The Ollama SERVER version recorded by the campaign's first launch. The
    server supplies every inference setting the campaign does not send
    (context length, sampler defaults, runner), so it is part of the identity."""
    for launch in (ledger.data["launches"] if ledger else []):
        if launch.get("inventory"):
            return launch["inventory"].get("ollama_version")
    return None


def check_task_pins(manifest: Manifest, task_ids: list[str] | None = None) -> list[str]:
    """Recompute each task's version and digest exactly as an evaluation snapshot
    would. Any difference means the frozen task set changed: STOP."""
    problems = []
    for task_id in task_ids or manifest.task_ids:
        pinned = manifest.task_by_id[task_id]
        try:
            now = jobs.task_snapshot(task_id)
        except Exception as exc:  # noqa: BLE001 - an unreadable task is a pin failure
            problems.append(f"{task_id}: cannot snapshot ({exc})")
            continue
        if now["task_version"] != pinned["task_version"] or now["task_digest"] != pinned["task_digest"]:
            problems.append(
                f"{task_id}: now {now['task_version']} {now['task_digest'][:19]}..., "
                f"frozen {pinned['task_version']} {pinned['task_digest'][:19]}..."
            )
    return problems


def init_db(manifest: Manifest) -> Path:
    """Create the CLEAN campaign database (db_strategy 'clean').

    Uses the supported primitives: the runner store creates the raw schema and
    the app's serialised migration adds the control-plane tables. Refuses the
    evidence database and any existing file (never re-initialises a campaign).
    """
    import afa_runner as afa

    target = app_db.assert_writable_runtime_path(manifest.db_path())
    if target.exists():
        raise CampaignStop(f"campaign database already exists: {target} (never re-initialised)")
    target.parent.mkdir(parents=True, exist_ok=True)
    afa.SqliteRunStore(target).close()
    conn = app_db.connect(target)
    try:
        app_db.migrate(conn)
    finally:
        conn.close()
    ro = cohort.open_readonly(target)
    try:
        runs = ro.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
        evaluations = ro.execute("SELECT COUNT(*) FROM evaluation_jobs").fetchone()[0]
    finally:
        ro.close()
    if runs or evaluations:
        raise CampaignStop(f"new campaign database is not empty ({runs} runs, {evaluations} evaluations)")
    return target


def preflight(
    manifest: Manifest,
    client: api_mod.AgentForgeApi | None,
    *,
    ledger: Ledger | None = None,
    check_code: bool = True,
    require_models: bool = True,
    phase: str | None = None,
) -> Preflight:
    pf = Preflight()
    pf.facts["checked_at"] = utc_now()
    pf.facts["manifest_sha256"] = manifest.sha256

    if check_code:
        problems, facts = check_runtime_code(manifest)
        pf.problems += problems
        pf.facts["code"] = facts
    pf.problems += [f"TASK PIN CHANGED - {p}" for p in check_task_pins(manifest)]

    hist = manifest.data["historical_evidence"]
    actual = evidence_sha256(paths.resolve(hist["path"]))
    pf.facts["historical_evidence_sha256"] = actual
    if actual != hist["sha256"]:
        pf.problems.append(f"historical evidence DB sha256 is {actual}, expected {hist['sha256']}")

    db_path = manifest.db_path()
    pf.facts["campaign_db"] = str(db_path)
    try:
        app_db.assert_writable_runtime_path(db_path)
    except ValueError as exc:
        pf.problems.append(str(exc))
    owned = ledger.evaluation_ids(active_only=False) if ledger else set()
    if not db_path.exists():
        pf.problems.append(f"campaign database {db_path} does not exist (run: init-db)")
    else:
        conn = cohort.open_readonly(db_path)
        try:
            jobless = cohort.jobless_run_count(conn)
            if jobless and manifest.data["runtime"].get("db_strategy") == "clean":
                pf.problems.append(
                    f"campaign database holds {jobless} raw runs created outside any evaluation "
                    "(it was probably seeded from the historical evidence because the app was "
                    "started before init-db); the clean strategy forbids that - recreate it"
                )
            foreign = [e for e in cohort.all_evaluations(conn) if e["id"] not in owned
                       and not (e["name"] or "").startswith(manifest.data["evaluation_name_prefix"] + ":")]
            if foreign:
                pf.warnings.append(
                    f"{len(foreign)} evaluation(s) in the campaign database are not campaign-owned; "
                    "they never count toward the campaign"
                )
        finally:
            conn.close()

    if client is not None:
        try:
            health = client.health()
        except api_mod.ApiError as exc:
            pf.problems.append(f"AgentForge app unreachable at {client.base}: {exc}")
            health = None
        if health is not None:
            pf.facts["api_health"] = health
            bound = health.get("db_path")
            if not bound or not same_path(bound, db_path):
                pf.problems.append(
                    f"the app is bound to {bound!r}, not the campaign database {db_path} "
                    "(start it with AFA_DB_PATH set to the campaign database)"
                )
            if health.get("status") != "ok":
                pf.problems.append(f"app health is {health.get('status')!r}: {health}")
            prefix = manifest.data["evaluation_name_prefix"] + ":"
            try:
                # This campaign's own evaluations (even one whose id the ledger has
                # not recorded yet) are reconciled by name, not treated as foreign.
                busy = [
                    j for j in client.list_jobs()
                    if j.get("status") in ("queued", "running") and j.get("id") not in owned
                    and not str(((j.get("params") or {}).get("name")) or "").startswith(prefix)
                ]
            except api_mod.ApiError as exc:
                pf.problems.append(f"cannot list evaluations: {exc}")
                busy = []
            if busy:
                pf.problems.append(
                    "evaluation(s) not owned by the campaign are queued/running on this app "
                    f"({[j['id'] for j in busy]}); the campaign needs exclusive use of the model server"
                )

    backend = manifest.backend
    if backend["kind"] == "ollama":
        try:
            snap = ollama.inventory(backend["base_url"], manifest.models)
        except ollama.OllamaError as exc:
            pf.problems.append(f"Ollama unreachable at {backend['base_url']}: {exc}")
        else:
            pf.facts["inventory"] = snap
            if not snap.get("ollama_version"):
                pf.problems.append("Ollama did not report its server version (/api/version); the campaign pins it "
                                   "as part of every cell's identity")
            if manifest.is_sequential:
                _sequential_target_checks(manifest, snap, ledger, phase, pf)
            elif require_models and snap["missing"]:
                pf.problems.append(
                    "roster model(s) missing from Ollama (never substituted): "
                    + ", ".join(snap["missing"])
                )
            if ledger is not None:
                first = next((l.get("inventory") for l in ledger.data["launches"] if l.get("inventory")), None)
                if first:
                    if snap.get("ollama_version") != first.get("ollama_version"):
                        pf.problems.append(
                            f"Ollama server version is {snap.get('ollama_version')!r}, the campaign's first launch "
                            f"ran {first.get('ollama_version')!r}; one cohort never mixes inference engines")
                    for model, digest in ({} if manifest.is_sequential else ollama.digests(snap)).items():
                        # a sequential plan's reference is the PIN (checked for the target
                        # in _sequential_target_checks), never another phase's first launch
                        was = ollama.digests(first).get(model)
                        if was and digest and was != digest:
                            pf.problems.append(
                                f"{model}: Ollama digest changed since the first launch "
                                f"({was[:12]} -> {digest[:12]}); the campaign's model identity moved"
                            )
    return pf


def _sequential_target_checks(manifest: Manifest, snap: dict, ledger: Ledger | None, phase: str | None,
                              pf: Preflight) -> None:
    """One model at a time: only the phase's target must be installed, with
    EXACTLY its pinned registry digest (never a substitute)."""
    if phase is None:
        pf.problems.append(f"a sequential campaign is checked and launched one model at a time: name the phase "
                           f"({', '.join(manifest.phases)})")
        return
    try:
        entry = manifest.phase_entry(phase)
    except KeyError:
        pf.problems.append(f"unknown phase {phase!r}; this plan's phases are {manifest.phases}")
        return
    from .lifecycle import live_smoke_apps, phase_finished, pinned_ollama_version  # lifecycle imports this module

    model = entry["model"]
    pf.facts["target"] = {"phase": phase, "model": model, "logical_name": entry["logical_name"]}
    status = (ledger.data.get("model_status") or {}).get(phase) if ledger else None
    if status:
        pf.problems.append(f"{model} ({phase}) is classified {status['status']}: it is not benchmarked")
    pinned_version = pinned_ollama_version(manifest)
    if pinned_version and snap.get("ollama_version") != pinned_version:
        pf.problems.append(f"Ollama server version is {snap.get('ollama_version')!r}, the frozen plan pins "
                           f"{pinned_version!r}; one cohort never mixes inference engines")
    present = (snap["models"].get(model) or {}).get("present")
    pinned = manifest.pinned_digests()[model]
    if not present:
        pf.problems.append(f"target {model} ({phase}) is not installed (pull-model --phase {phase}); nothing "
                           "is ever substituted for it")
    else:
        digest = normalize_digest(ollama.digests(snap).get(model))
        if digest != pinned:
            pf.problems.append(f"STOP - {model} is installed with digest {digest}, the frozen plan pins {pinned}: "
                               "ambiguous model identity, never benchmarked as the target")
    others = [m for m in manifest.models if m != model and (snap["models"].get(m) or {}).get("present")]
    if others:
        pf.warnings.append(f"other campaign targets are installed too ({', '.join(others)}); only {model} runs now")
    for other in others:
        observed = normalize_digest(ollama.digests(snap).get(other))
        if observed != manifest.pinned_digests()[other]:
            pf.warnings.append(f"{other} is installed with a NON-PINNED digest {observed}: it can never be "
                               "benchmarked as its target (remove it, then pull the pinned one)")
    if ledger is not None:
        # one model at a time: another model's batch must be finished (frozen
        # receipt) or classified before this one starts
        unfinished = sorted({e["phase"] for e in ledger.active_entries() if e["phase"] != phase}
                            - {p for p in manifest.phases if phase_finished(manifest, ledger, p)})
        if unfinished:
            pf.problems.append(f"one model at a time: phase(s) {unfinished} have campaign evaluations but no frozen "
                               "receipt and no classification; finish (validate + model-receipt) or classify them "
                               "first")
    smokes = [s for s in (ledger.data.get("smokes") or [] if ledger else [])
              if s.get("phase") == phase and s.get("operational_ok") and normalize_digest(s.get("digest")) == pinned]
    if not smokes:
        pf.problems.append(f"no passing smoke of {model} with its pinned digest is recorded: run "
                           f"smoke --phase {phase} first (4 tasks x 1 repetition in a scratch database)")
    alive = live_smoke_apps(manifest)
    if alive:
        pf.problems.append(f"a smoke app is still running (process groups {alive}); it would share the model "
                           "server with the campaign - stop it first")


# --------------------------------------------------------------------------- #
# Launch
# --------------------------------------------------------------------------- #


class Launcher:
    def __init__(
        self,
        manifest: Manifest,
        client: api_mod.AgentForgeApi,
        *,
        log: Callable[[str], None] = print,
        poll_s: float = 5.0,
        stuck_after_s: float = 900.0,
        unreachable_limit_s: float = 1800.0,
        warmup: bool = True,
        identity_poll_s: float = 30.0,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.manifest = manifest
        self.client = client
        self.log = log
        self.poll_s = poll_s
        self.stuck_after_s = stuck_after_s
        self.unreachable_limit_s = unreachable_limit_s
        self.warmup = warmup
        self.identity_poll_s = identity_poll_s
        self.sleep = sleep
        self.clock = clock
        self.ledger: Ledger | None = None
        self._launch: dict | None = None
        self._reference: dict[str, str] = {}
        self._reference_version: str | None = None

    # ---------------------------------------------------------------- utils
    def _load_ledger(self) -> Ledger:
        return Ledger.load(
            self.manifest.ledger_path(),
            campaign_id=self.manifest.campaign_id,
            manifest_sha256=self.manifest.sha256,
        )

    def _save(self) -> None:
        assert self.ledger is not None
        self.ledger.save()

    def _ro(self):
        return cohort.open_readonly(self.manifest.db_path())

    def _halt(self, message: str, **detail) -> None:
        assert self.ledger is not None
        self.ledger.event("halt", message=message, **detail)
        if self._launch is not None:
            self._launch["ended_at"] = utc_now()
            self._launch["outcome"] = "halted"
        self._save()
        raise CampaignStop(message)

    # --------------------------------------------------------------- phases
    def plan(self, phase: str) -> list[Cell]:
        cells = self.manifest.cells(phase)
        if not cells:
            raise CampaignStop(f"phase {phase!r} has no cells in this manifest")
        return cells

    def run(self, phase: str, *, max_evaluations: int | None = None, check_code: bool = True) -> dict:
        ledger_path = self.manifest.ledger_path()
        with ledger_lock(ledger_path):
            # The ledger (which freezes the manifest hash) is created only after a
            # passing preflight: a refused launch leaves nothing behind.
            existing = self._load_ledger() if ledger_path.exists() else None
            if self.manifest.is_sequential and phase not in self.manifest.phases:
                raise CampaignStop(f"a sequential campaign launches one model's phase at a time "
                                   f"({', '.join(self.manifest.phases)}), not {phase!r}")
            pf = preflight(self.manifest, self.client, ledger=existing, check_code=check_code,
                           phase=phase if self.manifest.is_sequential else None)
            if not pf.ok:
                if existing is not None:
                    existing.event("preflight_failed", problems=pf.problems)
                    existing.save()
                raise CampaignStop("preflight failed:\n  - " + "\n  - ".join(pf.problems))
            self.ledger = existing or Ledger.new(
                ledger_path, campaign_id=self.manifest.campaign_id, manifest_sha256=self.manifest.sha256,
                manifest_path=paths.display(self.manifest.path) if self.manifest.path else "",
            )
            for warning in pf.warnings:
                self.log(f"warning: {warning}")
            for earlier in self.ledger.data["launches"]:
                # We hold the exclusive lock, so a launch still marked running was
                # killed (crash, SIGKILL, reboot) before it could record its end.
                if earlier.get("outcome") == "running":
                    earlier["outcome"] = "interrupted"
                    self.ledger.event("launch_interrupted", started_at=earlier.get("started_at"))
            self._launch = {
                "started_at": utc_now(),
                "phase": phase,
                "max_evaluations": max_evaluations,
                "tooling_head": (pf.facts.get("code") or {}).get("head"),
                "runtime_release_tag": self.manifest.data["code"]["runtime_release_tag"],
                "runtime_release_commit": self.manifest.data["code"]["runtime_release_commit"],
                "api_url": self.client.base,
                "api_db_path": (pf.facts.get("api_health") or {}).get("db_path"),
                "historical_evidence_sha256_start": pf.facts.get("historical_evidence_sha256"),
                "inventory": pf.facts.get("inventory"),
                "check_code": bool(check_code and (pf.facts.get("code") or {}).get("head")),
                "warmup": self.warmup,
                "outcome": "running",
                **({"model": self.manifest.phase_entry(phase)["model"]} if self.manifest.is_sequential else {}),
            }
            self.ledger.data["launches"].append(self._launch)
            self.ledger.event("launch", phase=phase, max_evaluations=max_evaluations)
            self._save()
            self._reference = reference_digests(self.ledger, self.manifest)
            self._reference_version = reference_ollama_version(self.ledger)
            self._check_untracked_campaign_evaluations()
            counts = {"drained": 0, "skipped": 0, "succeeded": 0}
            # Finish EVERY in-flight campaign evaluation first - of any phase (a
            # resume, or a launcher killed mid-wait) - BEFORE submitting anything:
            # one evaluation at a time, and no phase can block another.
            for cell in self.manifest.cells():
                entry = self.ledger.active_entry(cell.key)
                if entry is not None and entry["state"] == SUBMITTING:
                    adopted = self._adopt_if_created(cell, entry)
                    if adopted is None:
                        # The POST never created it (crash before the request, or a
                        # refused one): nothing is in flight; the cell starts over.
                        self.ledger.entries.remove(entry)
                        self.ledger.event("submission_abandoned", cell=cell.key)
                        self._save()
                        entry = None
                    else:
                        entry = adopted
                if entry is not None and entry["state"] in (FAILED, CANCELED):
                    self._reconcile_external_resume(cell, entry)
                if entry is not None and entry["state"] == SUBMITTED:
                    self._settle_resumes(entry)
                    if cell.phase != phase:
                        self.log(f"finishing in-flight {cell.key} (phase {cell.phase}) before phase {phase}")
                    self._finalize(cell, entry, self._wait(entry))
                    counts["drained"] += 1

            submitted = 0
            paused = False
            for cell in self.plan(phase):
                entry = self.ledger.active_entry(cell.key)
                if entry is not None and entry["state"] == SUCCEEDED:
                    counts["skipped"] += 1
                    continue
                if entry is not None and entry["state"] in HALTING:
                    self._halt(self._halting_message(entry), cell=cell.key)
                if entry is None or entry["state"] == SUBMITTING:
                    adopted = self._adopt_if_created(cell, entry)
                    if adopted is None:
                        if max_evaluations is not None and submitted >= max_evaluations:
                            self.log(f"pausing: reached --max-evaluations {max_evaluations}")
                            paused = True
                            break
                        entry = self._submit(cell, entry)
                        submitted += 1
                    else:
                        entry = adopted
                job = self._wait(entry)
                self._finalize(cell, entry, job)
                counts["succeeded"] += 1
            end_sha = evidence_sha256(paths.resolve(self.manifest.data["historical_evidence"]["path"]))
            self._launch["historical_evidence_sha256_end"] = end_sha
            self._launch["ended_at"] = utc_now()
            self._launch["outcome"] = "paused" if paused else "phase-complete"
            self._launch["submitted"] = submitted
            if end_sha != self.manifest.data["historical_evidence"]["sha256"]:
                self._halt("historical evidence DB hash changed during the launch - investigate immediately")
            self.ledger.event("launch_end", phase=phase, submitted=submitted, **counts)
            self._save()
            return {"submitted": submitted, "paused": paused, **counts}

    # ------------------------------------------------------------ internals
    def _check_untracked_campaign_evaluations(self) -> None:
        """An evaluation carrying this campaign's name that the ledger does not
        own is a duplicate or an orphan (UI retry clone, lost ledger, two
        launchers): never adopt it silently."""
        assert self.ledger is not None
        known = self.ledger.evaluation_ids(active_only=False) | self.ledger.disowned_ids()
        submitting_names = {
            e["evaluation_name"] for e in self.ledger.active_entries() if e["state"] == SUBMITTING
        }
        conn = self._ro()
        try:
            named = cohort.evaluations_named(conn, self.manifest.data["evaluation_name_prefix"])
        finally:
            conn.close()
        untracked = [e for e in named if e["id"] not in known]
        by_name: dict[str, list[dict]] = {}
        for evaluation in untracked:
            by_name.setdefault(evaluation["name"], []).append(evaluation)
        bad = [
            e for name, group in by_name.items() for e in group
            if name not in submitting_names or len(group) > 1
        ]
        if bad:
            self._halt(
                "evaluation(s) named for this campaign exist that the ledger does not own: "
                + ", ".join(f"{e['id']} ({e['name']}, {e['status']})" for e in bad)
                + ". They are duplicates or orphans (a UI retry clone, a lost ledger, a second "
                "launcher). They never count; investigate, then record each with "
                "'disown --evaluation <id> --reason ...' (runbook: duplicates).",
                untracked=[e["id"] for e in bad],
            )

    def _adopt_if_created(self, cell: Cell, entry: dict | None) -> dict | None:
        """Recover from a crash between writing 'submitting' and recording the id."""
        if entry is None:
            return None
        assert self.ledger is not None
        conn = self._ro()
        try:
            named = [
                e for e in cohort.evaluations_named(conn, self.manifest.data["evaluation_name_prefix"])
                if e["name"] == entry["evaluation_name"]
                and e["id"] not in self.ledger.evaluation_ids(active_only=False)
                and e["id"] not in self.ledger.disowned_ids()
            ]
        finally:
            conn.close()
        if len(named) > 1:
            self._halt(f"{cell.key}: {len(named)} evaluations carry the campaign name; duplicates")
        if not named:
            return None
        self.ledger.update(entry, evaluation_id=named[0]["id"], state=SUBMITTED, job_status=named[0]["status"])
        self.ledger.event("adopted", cell=cell.key, evaluation_id=named[0]["id"])
        self._save()
        self.log(f"{cell.key}: adopted evaluation {named[0]['id']} created before an interruption")
        return entry

    def _observe_identity(self, model: str, *, attempts: int = 1) -> tuple[str | None, str | None, str | None]:
        """(digest, server version, error) without halting; digest None + error
        None = model absent. A failed read is retried ``attempts`` times."""
        error = None
        for attempt in range(max(1, attempts)):
            if attempt:
                self.sleep(10.0)
            try:
                now = ollama.inventory(self.manifest.backend["base_url"], [model])
            except ollama.OllamaError as exc:
                error = str(exc)
                continue
            if not now["models"][model]["present"]:
                return None, now.get("ollama_version"), None
            return self._digest(ollama.digests(now).get(model)), now.get("ollama_version"), None
        return None, None, error

    def _digest(self, value: str | None) -> str | None:
        """Sequential plans compare normalized (bare-hex) digests with their pins."""
        return normalize_digest(value) if self.manifest.is_sequential else value

    def _current_identity(self, model: str) -> tuple[str | None, str | None]:
        """Present-and-unchanged check of one roster model and of the server
        version; returns (digest, version)."""
        if self.manifest.backend["kind"] != "ollama":
            return None, None
        try:
            now = ollama.inventory(self.manifest.backend["base_url"], [model])
        except ollama.OllamaError as exc:
            self._halt(f"Ollama unreachable while checking {model}: {exc}")
        if not now["models"][model]["present"]:
            self._halt(f"{model} disappeared from Ollama")
        digest = self._digest(ollama.digests(now).get(model))
        version = now.get("ollama_version")
        reference = self._reference.get(model)
        if reference and digest != reference:
            self._halt(f"{model}: Ollama digest {digest} differs from the campaign's first-launch digest "
                       f"{reference}; the model identity moved - never mix weights in one cohort")
        if not version or version != self._reference_version:
            self._halt(f"Ollama server version is {version!r}, the campaign's first launch ran "
                       f"{self._reference_version!r}; never mix inference engines in one cohort")
        return digest, version

    def _prepare_model(self, model: str) -> tuple[str | None, str | None, bool]:
        """Before EVERY submission: identity check, then load the model so a cold
        load is never charged to a trial's wall-clock budget (Ollama unloads idle
        models after its keep-alive, e.g. during a halt). Returns (digest,
        server version, warmed up)."""
        digest, version = self._current_identity(model)
        warmed = False
        if self.manifest.backend["kind"] == "ollama" and self.warmup:
            try:
                ollama.warm_up(self.manifest.backend["base_url"], model)
            except ollama.OllamaError as exc:
                self._halt(f"could not load {model} into Ollama: {exc}")
            warmed = True
        return digest, version, warmed

    def _check_app_state(self) -> None:
        """Re-checked before EVERY submission (a campaign runs for hours): the app
        is still bound to the campaign DB, nothing else uses the model server, and
        no untracked evaluation carries this campaign's name."""
        assert self.ledger is not None
        try:
            health = self.client.health()
            jobs_now = self.client.list_jobs()
        except api_mod.ApiError as exc:
            self._halt(f"app unreachable before a submission: {exc}")
        bound = health.get("db_path")
        if not bound or not same_path(bound, self.manifest.db_path()):
            self._halt(f"the app is now bound to {bound!r}, not the campaign database")
        if health.get("status") != "ok":
            self._halt(f"app health is {health.get('status')!r}: {health}")
        # This phase's own in-flight evaluations were drained before the loop, and
        # each cell is finalized before the next is submitted, so ANY queued or
        # running evaluation now (foreign, or another phase's) would run
        # concurrently with the next submission.
        busy = [j.get("id") for j in jobs_now if j.get("status") in ("queued", "running")]
        conn = self._ro()
        try:
            busy += [eid for eid in cohort.active_evaluations(conn) if eid not in busy]
        finally:
            conn.close()
        hist = self.manifest.data["historical_evidence"]
        if evidence_sha256(paths.resolve(hist["path"])) != hist["sha256"]:
            self._halt("historical evidence DB hash changed - investigate immediately")
        if busy:
            self._halt(f"evaluation(s) are queued/running on the app: {busy}; the campaign needs "
                       "exclusive use of the model server (one evaluation at a time)")
        self._check_untracked_campaign_evaluations()

    def _reconcile_external_resume(self, cell: Cell, entry: dict) -> None:
        """A failed/canceled entry whose evaluation the DATABASE shows queued,
        running or succeeded was resumed outside this tooling (a manual API
        call): no code check, identity check, busy check or warm-up guarded that
        resume. Wait for it (one evaluation at a time), then reject it durably:
        the remedy is a fresh re-evaluation (supersede), whatever its result."""
        assert self.ledger is not None
        conn = self._ro()
        try:
            detected = external_resume(conn, entry)
        finally:
            conn.close()
        if detected is None:
            return
        was = entry["state"]
        self.ledger.event("external_resume_detected", cell=cell.key, evaluation_id=entry["evaluation_id"],
                          ledger_state=was, detail=detected)
        self._save()
        self.log(f"{cell.key}: evaluation {entry['evaluation_id']} was resumed outside the campaign tooling "
                 f"({detected}); waiting for it to finish")
        job = self._wait(entry)
        self.ledger.update(entry, state=REJECTED, job_status=job.get("status"), finished_at=utc_now(), problems=[
            f"evaluation was resumed outside the campaign tooling ({detected}): no code, identity or busy "
            "check and no warm-up guarded that resume"])
        self._halt(self._halting_message(entry), cell=cell.key)

    def _settle_resumes(self, entry: dict) -> None:
        """A resume whose command died ('requested') or whose answer was lost
        ('unknown') is settled from the app's own 'job_resumed' events: each is
        matched to an event logged from its request time on (up to 5 minutes
        later), after the resumes known to have run have claimed theirs. Matched:
        'executed'; unmatched: 'not_executed' (no evidence, flags irrelevant).
        Settled ONCE, before the launch waits on the evaluation, and never
        re-opened: a later event can never flip a settled record (that could
        credit a resume made outside the tooling to the tooling). A lost request
        the app executes only after that (a stalled app) therefore counts as a
        resume outside the tooling: the cell is rejected and must be superseded."""
        import datetime as dt

        assert self.ledger is not None
        records = [r for r in entry.get("resumes") or [] if isinstance(r, dict)]
        ambiguous = [r for r in records if r.get("outcome") in validate_mod.UNSETTLED_RESUMES]
        if not ambiguous:
            return
        conn = self._ro()
        try:
            times = cohort.resume_event_times(conn, entry["evaluation_id"])
        finally:
            conn.close()

        def parse(value: str, fmt: str):
            try:
                return dt.datetime.strptime(value, fmt)
            except (TypeError, ValueError):
                return None

        events = [parse(t, "%Y-%m-%d %H:%M:%S") for t in times]
        free = [i for i, t in enumerate(events) if t is not None]

        def claim(record: dict, window_s: float | None) -> bool:
            at = parse(record.get("at"), "%Y-%m-%dT%H:%M:%SZ")
            for i in free:
                if at is None or (events[i] >= at - dt.timedelta(seconds=1) and (
                        window_s is None or events[i] <= at + dt.timedelta(seconds=window_s))):
                    free.remove(i)
                    return True
            return False

        for record in records:
            if record.get("outcome") in ("accepted", "executed"):
                claim(record, None)
        for record in ambiguous:
            record["settled_from"] = record.get("outcome")
            record["outcome"] = "executed" if claim(record, 300.0) else "not_executed"
        self.ledger.event("resume_outcome_settled", cell=entry["cell"], evaluation_id=entry["evaluation_id"],
                          outcomes=[r.get("outcome") for r in records], resume_events=len(times))
        self._save()

    def _submit(self, cell: Cell, entry: dict | None) -> dict:
        assert self.ledger is not None
        pins = check_task_pins(self.manifest, [cell.task_id])
        if pins:
            self._halt("STOP THE CAMPAIGN - a task changed after the campaign was frozen: " + "; ".join(pins))
        self._check_app_state()
        digest, version, warmed = self._prepare_model(cell.model)
        if entry is None:
            entry = self.ledger.new_entry(
                key=cell.key, model=cell.model, task_id=cell.task_id, phase=cell.phase,
                evaluation_name=self.manifest.evaluation_name(cell),
                positions=list(range(self.manifest.repetitions)),
            )
        assert self._launch is not None
        task = self.manifest.task_by_id[cell.task_id]
        self.ledger.update(entry, model_digest_at_submit=digest, ollama_version_at_submit=version,
                           warmed_up_at_submit=warmed, code_check_at_submit=self._launch["check_code"],
                           submitted_by_launch=self._launch["started_at"],
                           campaign_id=self.manifest.campaign_id,
                           logical_name=(self.manifest.roster_entry(cell.model)["logical_name"]
                                         if self.manifest.is_sequential else cell.model),
                           task_version=task["task_version"], task_digest=task["task_digest"],
                           backend_kind=self.manifest.backend["kind"], generation=self.manifest.generation,
                           expected_runs=self.manifest.repetitions)
        self._save()  # written BEFORE the POST: a crash is reconciled by name
        body = self.manifest.job_body(cell)
        try:
            job = self.client.create_job(body)
        except api_mod.ApiUnreachable as exc:
            self._halt(f"{cell.key}: outcome of POST /jobs unknown ({exc}); rerun launch to reconcile")
        except api_mod.ApiError as exc:
            if exc.status is not None and 400 <= exc.status < 500:
                self.ledger.entries.remove(entry)
                self.ledger.event("submit_refused", cell=cell.key, status=exc.status, body=exc.body)
                self._halt(f"{cell.key}: the app refused the evaluation: {exc}")
            self._halt(f"{cell.key}: outcome of POST /jobs unknown ({exc}); rerun launch to reconcile")
        if job.get("mode") != "fresh" or job.get("backend_kind") != self.manifest.backend["kind"]:
            self.ledger.update(entry, evaluation_id=job.get("id"), state=REJECTED,
                               problems=[f"created with mode {job.get('mode')!r}, backend {job.get('backend_kind')!r}"])
            self._halt(f"{cell.key}: the app created a non-fresh or wrong-backend evaluation {job.get('id')}")
        self.ledger.update(entry, evaluation_id=job["id"], state=SUBMITTED, job_status=job.get("status"))
        self.ledger.event("submitted", cell=cell.key, evaluation_id=job["id"])
        self._save()
        self.log(f"{cell.key}: submitted evaluation {job['id']} ({self.manifest.repetitions} positions)")
        return entry

    def _watch(self, entry: dict, status: str | None) -> None:
        """While an evaluation runs: (1) keep re-reading its model's digest and
        the server version - a model re-tagged and restored between submission
        and acceptance would otherwise be invisible; (2) make sure no other
        evaluation is RUNNING at the same time (its trials would share the model
        server). Either taints the evaluation durably (it is rejected when it
        finishes); a failed Ollama read is only counted."""
        assert self.ledger is not None
        if status == "running" and not entry.get("concurrency_violation"):
            conn = self._ro()
            try:
                others = [e for e in cohort.running_evaluations(conn) if e != entry["evaluation_id"]]
            finally:
                conn.close()
            if others:
                self.ledger.update(entry, concurrency_violation={"evaluations": others, "at": utc_now()})
                self._save()
                self.log(f"CONCURRENCY VIOLATION: evaluation(s) {others} run alongside "
                         f"{entry['evaluation_id']}; its evidence will be rejected")
        if self.manifest.backend["kind"] != "ollama" or entry.get("identity_violation"):
            return
        digest, version, error = self._observe_identity(entry["model"])
        if error is not None:
            entry["identity_checks_failed"] = int(entry.get("identity_checks_failed") or 0) + 1
            return
        expected = entry.get("model_digest_at_submit") or self._reference.get(entry["model"])
        expected_version = entry.get("ollama_version_at_submit") or self._reference_version
        if (expected and digest != expected) or version != expected_version:
            self.ledger.update(entry, identity_violation={
                "observed": digest, "expected": expected, "observed_ollama_version": version,
                "expected_ollama_version": expected_version, "at": utc_now()})
            self._save()
            self.log(f"IDENTITY VIOLATION: {entry['model']} digest {digest} / Ollama {version} != "
                     f"{expected} / {expected_version} while {entry['evaluation_id']} runs; its evidence "
                     "will be rejected")

    def _wait(self, entry: dict) -> dict:
        evaluation_id = entry["evaluation_id"]
        queued_since = self.clock()
        unreachable_since: float | None = None
        warned_stuck = False
        last_completed = None
        last_identity = self.clock()
        while True:
            try:
                job = self.client.get_job(evaluation_id)
            except api_mod.ApiUnreachable as exc:
                unreachable_since = unreachable_since or self.clock()
                if self.clock() - unreachable_since > self.unreachable_limit_s:
                    self._halt(f"app unreachable for {self.unreachable_limit_s:.0f}s while waiting on "
                               f"{evaluation_id}: {exc}")
                self.sleep(min(60.0, self.poll_s * 4))
                continue
            except api_mod.ApiError as exc:
                if exc.status == 404:
                    conn = self._ro()
                    try:
                        present = conn.execute("SELECT 1 FROM evaluation_jobs WHERE id=?",
                                               (evaluation_id,)).fetchone() is not None
                    finally:
                        conn.close()
                    if not present:
                        # durable and supersedable: the evidence is gone for good
                        self.ledger.update(entry, state=REJECTED, problems=[
                            f"evaluation {evaluation_id} is missing from the campaign database"])
                        self._halt(self._halting_message(entry), cell=entry["cell"])
                self._halt(f"cannot read evaluation {evaluation_id}: {exc}")
            unreachable_since = None
            status = job.get("status")
            completed = (job.get("counters") or {}).get("completed_runs")
            if completed != last_completed:
                last_completed = completed
                self.log(f"  {entry['cell']}: {status} {completed}/{(job.get('counters') or {}).get('total_runs')}")
            if self.clock() - last_identity >= self.identity_poll_s:
                last_identity = self.clock()
                self._watch(entry, status)
            if status in TERMINAL:
                return job
            if status == "queued" and not warned_stuck and self.clock() - queued_since > self.stuck_after_s:
                warned_stuck = True
                self.log(f"warning: {evaluation_id} has been queued for {self.stuck_after_s:.0f}s - "
                         "is the app's worker running?")
            if status == "running":
                queued_since = self.clock()
            self.sleep(self.poll_s)

    def _save_reports(self, evaluation_id: str) -> None:
        folder = self.manifest.runtime_dir() / "evaluation-reports"
        folder.mkdir(parents=True, exist_ok=True)
        try:
            report = self.client.report(evaluation_id)
        except api_mod.ApiError as exc:
            self.log(f"warning: could not save report for {evaluation_id}: {exc}")
            return
        (folder / f"{evaluation_id}.json").write_text(json.dumps(report, indent=2) + "\n")

    def _finalize(self, cell: Cell, entry: dict, job: dict) -> None:
        assert self.ledger is not None
        status = job.get("status")
        message = job.get("error_message") or ""
        assert self._launch is not None
        self.ledger.update(entry, job_status=status, finished_at=utc_now(),
                           code_check_at_finalize=self._launch["check_code"],
                           finalized_by_launch=self._launch["started_at"])
        if status in ("failed", "canceled"):
            drift = check_task_pins(self.manifest, [cell.task_id])
            if drift:
                self.ledger.update(entry, state=REJECTED, problems=[message, *drift])
                self._halt("STOP THE CAMPAIGN - a task changed after the campaign was frozen "
                           f"(evaluation {entry['evaluation_id']} failed on it): " + "; ".join(drift),
                           cell=cell.key)
            if message.startswith(UNVERIFIABLE_PREFIX) or job.get("params_status") == "unverifiable":
                self.ledger.update(entry, state=REJECTED, problems=[message or "unverifiable parameters"])
                self._halt(
                    f"{cell.key}: evaluation {entry['evaluation_id']} is corrupt/unverifiable "
                    f"({message}); STOP and investigate (it is never resumed)",
                    cell=cell.key,
                )
            tainted = [f"{k.replace('_', ' ')}: {entry[k]}" for k in ("identity_violation", "concurrency_violation")
                       if entry.get(k)]
            conn = self._ro()
            try:
                tainted += validate_mod.resume_problems(conn, entry)
            finally:
                conn.close()
            # a start that can never be official is not worth resuming
            tainted += validate_mod.rehearsal_problems(self.manifest, entry)
            if tainted:
                # never advise a resume: this evaluation's evidence can no longer count
                self.ledger.update(entry, state=REJECTED, problems=[message, *tainted])
                self._halt(self._halting_message(entry), cell=cell.key)
            conn = self._ro()
            try:
                snapshot = cohort.halt_snapshot(conn, entry["evaluation_id"])
            finally:
                conn.close()
            self.ledger.update(entry, state=FAILED if status == "failed" else CANCELED, problems=[message],
                               halt_snapshot=snapshot)
            self._halt(self._halting_message(entry), cell=cell.key)
        conn = self._ro()
        try:
            check = cohort.check_cell_evaluation(conn, self.manifest, cell, entry["evaluation_id"])
            overlapping = cohort.overlapping_evaluations(conn, entry["evaluation_id"])
        finally:
            conn.close()
        self._save_reports(entry["evaluation_id"])
        summary = {k: v for k, v in check.as_dict().items() if k in (
            "n_runs", "valid", "passed", "voided", "timeouts", "agent_errors", "request_timeout_hits",
            "run_ids", "classes")}
        concurrency = []
        if overlapping:
            concurrency.append(f"trials of evaluation(s) {overlapping} ran at the same time as this evaluation's")
        if entry.get("concurrency_violation"):
            concurrency.append(f"another evaluation ran alongside it: {entry['concurrency_violation']}")
        if check.problems or concurrency:
            self.ledger.update(entry, state=REJECTED, problems=[*check.problems, *concurrency], summary=summary)
            self._halt(
                f"{cell.key}: evaluation {entry['evaluation_id']} failed campaign checks; its evidence "
                "is EXCLUDED (supersede the cell for a fresh re-evaluation):\n    - "
                + "\n    - ".join([*check.problems, *concurrency]),
                cell=cell.key,
            )
        if check.voided:
            self.ledger.update(entry, state=NEEDS_ATTENTION, warnings=check.warnings, summary=summary)
            self._halt(self._halting_message(entry), cell=cell.key)
        warnings: list[str] = []
        if self.manifest.backend["kind"] == "ollama":
            # Every halt below is DURABLE: the entry leaves 'submitted', so a later
            # launch can never re-finalize (and silently accept) the evaluation
            # under changed conditions. The remedy is always a fresh re-evaluation.
            if check.request_timeout_hits:
                try:
                    ollama.probe(self.manifest.backend["base_url"], cell.model)
                except ollama.OllamaError as exc:
                    self.ledger.update(entry, state=NEEDS_ATTENTION, summary=summary, warnings=[
                        f"{check.request_timeout_hits} trial(s) ran the full request timeout and the backend "
                        f"then failed a generation probe ({exc}): those TIMEOUTs may be infrastructure"])
                    self._halt(self._halting_message(entry), cell=cell.key)
                warnings.append(
                    f"{check.request_timeout_hits} trial(s) ran the full {self.manifest.generation['request_timeout_s']} s "
                    "request timeout (scored TIMEOUT by the runtime); the model answered a generation probe "
                    "afterwards, so they are treated as model behaviour")
            digest, version, error = self._observe_identity(cell.model, attempts=3)
            if error is not None:
                self.ledger.update(entry, state=NEEDS_ATTENTION, summary=summary, warnings=[
                    f"model identity could not be verified when the evaluation finished ({error})"])
                self._halt(self._halting_message(entry), cell=cell.key)
            reference = self._reference.get(cell.model)
            submitted_with = entry.get("model_digest_at_submit")
            problems = []
            if digest is None:
                problems.append(f"{cell.model} was absent from Ollama when the evaluation finished")
            elif (submitted_with and digest != submitted_with) or (reference and digest != reference):
                problems.append(f"model digest changed around the evaluation (submitted with {submitted_with}, "
                                f"now {digest}, campaign reference {reference})")
            if version != self._reference_version or version != entry.get("ollama_version_at_submit", version):
                problems.append(f"Ollama server version changed around the evaluation (submitted under "
                                f"{entry.get('ollama_version_at_submit')!r}, now {version!r}, campaign reference "
                                f"{self._reference_version!r})")
            if entry.get("identity_violation"):
                problems.append(f"model identity changed while the evaluation ran: {entry['identity_violation']}")
            if problems:
                self.ledger.update(entry, state=REJECTED, summary=summary, model_digest_at_finalize=digest,
                                   ollama_version_at_finalize=version, problems=problems)
                self._halt(f"{cell.key}: model identity not proven for evaluation {entry['evaluation_id']}; its "
                           "evidence is EXCLUDED (supersede the cell for a fresh re-evaluation):\n    - "
                           + "\n    - ".join(problems), cell=cell.key)
            self.ledger.update(entry, model_digest_at_finalize=digest, ollama_version_at_finalize=version)
        self.ledger.update(entry, state=SUCCEEDED, summary=summary, problems=[], warnings=warnings)
        # The launcher never marks succeeded what the validator would refuse (a
        # rehearsal flag, a resume outside the tooling, a later overlap): such a
        # cell lands in a supersedable state instead of a dead one.
        conn = self._ro()
        try:
            verdict = validate_mod.assess_cell(conn, self.manifest, cell, entry, self._reference,
                                               self._reference_version)
        finally:
            conn.close()
        if not verdict["accepted"]:
            self.ledger.update(entry, state=REJECTED, problems=verdict["problems"])
            self._halt(f"{cell.key}: evaluation {entry['evaluation_id']} is not official campaign evidence; it is "
                       "EXCLUDED (supersede the cell for a fresh re-evaluation):\n    - "
                       + "\n    - ".join(verdict["problems"]), cell=cell.key)
        self.ledger.event("cell_succeeded", cell=cell.key, evaluation_id=entry["evaluation_id"],
                          passed=check.passed, valid=check.valid)
        self._save()
        self.log(f"{cell.key}: succeeded - {check.passed}/{check.valid} passed "
                 f"({check.timeouts} timeouts, {check.voided} voided)")

    @staticmethod
    def _halting_message(entry: dict) -> str:
        state, key, eid = entry["state"], entry["cell"], entry.get("evaluation_id")
        advice = {
            FAILED: f"resume it under the same id (resume --cell '{key}') or supersede it with a reason",
            CANCELED: f"resume it under the same id (resume --cell '{key}') or supersede it with a reason",
            REJECTED: f"its evidence is excluded; investigate, then supersede it with a reason "
                      f"(supersede --cell '{key}' --reason ...)",
            NEEDS_ATTENTION: "it has infrastructure trouble (voided positions, or full-length request "
                             "timeouts with an unresponsive backend): fix the backend, then supersede the "
                             f"cell with a reason (supersede --cell '{key}' --reason ...) so it is "
                             "re-evaluated fresh; a campaign cell must have all positions valid",
        }.get(state, "see the runbook")
        problems = "; ".join(entry.get("problems") or entry.get("warnings") or [])
        return f"HALT: cell {key} (evaluation {eid}) is {state}{': ' + problems if problems else ''} - {advice}"


# --------------------------------------------------------------------------- #
# Operator actions
# --------------------------------------------------------------------------- #


def external_resume(conn, entry: dict) -> str | None:
    """Evidence that a failed/canceled campaign evaluation was resumed outside
    the tooling: the database shows it active or succeeded, or it no longer
    matches the snapshot taken when the campaign halted on it."""
    row = conn.execute("SELECT status FROM evaluation_jobs WHERE id=?", (entry.get("evaluation_id"),)).fetchone()
    if row is None:
        return None
    if row["status"] in ("queued", "running", "succeeded"):
        return f"the ledger says {entry['state']}, the database {row['status']}"
    recorded = entry.get("halt_snapshot")
    if recorded:
        now = cohort.halt_snapshot(conn, entry["evaluation_id"])
        if now != recorded:
            return f"the evaluation changed after the campaign halted on it ({recorded} -> {now})"
    return None


def resume_cell(manifest: Manifest, client: api_mod.AgentForgeApi, key: str, *, check_code: bool = True) -> dict:
    """Same-id ATLAS resume of a failed / canceled campaign evaluation.

    Only when nothing else is queued/running (one evaluation at a time), with the
    model's identity and the server version re-checked against the campaign's
    first launch and the model loaded first (the resumed trials start
    immediately). The entry is marked in flight BEFORE the POST, so a lost
    response is reconciled by the next launch instead of stranding the cell."""
    path = manifest.ledger_path()
    with ledger_lock(path):
        ledger = Ledger.load(path, campaign_id=manifest.campaign_id, manifest_sha256=manifest.sha256)
        entry = ledger.active_entry(key)
        if entry is None or entry["state"] not in (FAILED, CANCELED):
            raise LedgerError(
                f"cell {key} is {entry['state'] if entry else 'not started'}; only failed or canceled "
                "campaign evaluations are resumed (unverifiable / rejected ones are superseded)"
            )
        classified = (ledger.data.get("model_status") or {}).get(entry.get("phase"))
        if classified:
            raise CampaignStop(f"cell {key}: its model ({entry.get('phase')}) is classified {classified['status']}; "
                               "it is not benchmarked, so it is never resumed")
        tainted = [k for k in ("identity_violation", "concurrency_violation") if entry.get(k)]
        if tainted:
            raise CampaignStop(
                f"cell {key}: evaluation {entry['evaluation_id']} recorded a {tainted[0].replace('_', ' ')} "
                f"({entry[tainted[0]]}); its evidence can never count - supersede the cell instead "
                f"(supersede --cell '{key}' --reason ...)")
        unofficial = validate_mod.rehearsal_problems(manifest, entry)
        if unofficial:
            raise CampaignStop(f"cell {key}: {'; '.join(unofficial)} - resuming it can never make it official; "
                               f"supersede the cell instead (supersede --cell '{key}' --reason ...)")
        conn = cohort.open_readonly(manifest.db_path())
        try:
            detected = external_resume(conn, entry)
            row = conn.execute("SELECT status FROM evaluation_jobs WHERE id=?", (entry["evaluation_id"],)).fetchone()
        finally:
            conn.close()
        if detected is not None:
            ledger.update(entry, state=REJECTED, job_status=row["status"] if row else None, problems=[
                f"evaluation was resumed outside the campaign tooling ({detected}): no code, identity or busy "
                "check and no warm-up guarded that resume"])
            ledger.event("external_resume_detected", cell=key, evaluation_id=entry["evaluation_id"], detail=detected)
            ledger.save()
            raise CampaignStop(f"cell {key}: evaluation {entry['evaluation_id']} was resumed outside the campaign "
                               f"tooling ({detected}); it is rejected - supersede the cell "
                               f"(supersede --cell '{key}' --reason ...)")
        in_flight = [e["cell"] for e in ledger.active_entries() if e["state"] in (SUBMITTED, SUBMITTING)]
        if in_flight:
            raise CampaignStop(f"campaign evaluation(s) {in_flight} are still in flight; run launch to finish "
                               "them before resuming another (one evaluation at a time)")
        if check_code:
            code_problems, _ = check_runtime_code(manifest)
            if code_problems:
                raise CampaignStop("runtime code check failed: " + "; ".join(code_problems))
        drift = check_task_pins(manifest, [entry["task_id"]])
        if drift:
            raise CampaignStop("STOP THE CAMPAIGN - a task changed after the campaign was frozen: "
                               + "; ".join(drift))
        try:
            busy = [j.get("id") for j in client.list_jobs() if j.get("status") in ("queued", "running")]
        except api_mod.ApiError as exc:
            raise CampaignStop(f"cannot list evaluations: {exc}") from None
        conn = cohort.open_readonly(manifest.db_path())
        try:
            busy += [eid for eid in cohort.active_evaluations(conn) if eid not in busy]
        finally:
            conn.close()
        if busy:
            raise CampaignStop(f"evaluation(s) {busy} are queued/running; resume only on an idle app")
        warmed = False
        if manifest.backend["kind"] == "ollama":
            base = manifest.backend["base_url"]
            try:
                now = ollama.inventory(base, [entry["model"]])
                reference = reference_digests(ledger, manifest).get(entry["model"])
                reference_version = reference_ollama_version(ledger)
                digest = ollama.digests(now).get(entry["model"])
                if not now["models"][entry["model"]]["present"]:
                    raise CampaignStop(f"{entry['model']} is missing from Ollama")
                if reference and digest != reference:
                    raise CampaignStop(f"{entry['model']}: Ollama digest {digest} differs from the campaign's "
                                       f"first-launch digest {reference}")
                if not now.get("ollama_version") or now.get("ollama_version") != reference_version:
                    raise CampaignStop(f"Ollama server version is {now.get('ollama_version')!r}, the campaign's "
                                       f"first launch ran {reference_version!r}")
                ollama.warm_up(base, entry["model"])
                warmed = True
            except ollama.OllamaError as exc:
                raise CampaignStop(f"Ollama not ready for {entry['model']}: {exc}") from None
            if entry.get("model_digest_at_submit") and digest != entry["model_digest_at_submit"]:
                raise CampaignStop(f"{entry['model']}: digest differs from the one this evaluation started with")
        previous, previous_problems = entry["state"], list(entry.get("problems") or [])
        record = {"at": utc_now(), "check_code": bool(check_code), "warmed_up": warmed,
                  "from_state": previous, "outcome": "requested"}
        entry.setdefault("resumes", []).append(record)
        ledger.update(entry, state=SUBMITTED, problems=[])
        ledger.event("resume_requested", cell=key, evaluation_id=entry["evaluation_id"], check_code=check_code)
        ledger.save()  # BEFORE the POST: a lost response is reconciled by the next launch
        try:
            job = client.resume(entry["evaluation_id"])
        except api_mod.ApiNotSent as exc:
            # the connection was refused: nothing reached the app, nothing was resumed
            record["outcome"] = "not_sent"
            ledger.update(entry, state=previous, problems=previous_problems)
            ledger.event("resume_not_sent", cell=key, evaluation_id=entry["evaluation_id"])
            ledger.save()
            raise CampaignStop(f"the app refused the connection ({exc}); nothing was resumed - start the app "
                               "and run resume again") from None
        except api_mod.ApiError as exc:
            if isinstance(exc, api_mod.ApiUnreachable) or exc.status is None or not 400 <= exc.status < 500:
                record["outcome"] = "unknown"
                ledger.save()
                raise CampaignStop(
                    f"the outcome of resuming {entry['evaluation_id']} is unknown ({exc}); run launch: it waits "
                    "for the evaluation if the app resumed it, and halts on it again if not") from None
            record["outcome"] = "refused"
            ledger.update(entry, state=previous, problems=previous_problems)
            ledger.event("resume_refused", cell=key, evaluation_id=entry["evaluation_id"], status=exc.status)
            ledger.save()
            raise CampaignStop(f"the app refused to resume {entry['evaluation_id']}: {exc}") from None
        if job.get("id") != entry["evaluation_id"]:
            record["outcome"] = "refused"
            ledger.update(entry, state=previous, problems=previous_problems)
            ledger.event("resume_refused", cell=key, evaluation_id=entry["evaluation_id"], returned=job.get("id"))
            ledger.save()
            raise CampaignStop(f"resume returned a different evaluation id {job.get('id')}")
        record["outcome"] = "accepted"
        ledger.update(entry, job_status=job.get("status"))
        ledger.event("resumed", cell=key, evaluation_id=entry["evaluation_id"], check_code=check_code)
        ledger.save()
        return entry


def supersede_cell(manifest: Manifest, key: str, reason: str) -> dict:
    """Replace a halted cell's evaluation (reason required). A SUCCEEDED cell is
    superseded only when the shared acceptance predicate refuses it (e.g. an
    entry written by older tooling): that refusal never depends on the result,
    so replacing it is not cherry-picking."""
    path = manifest.ledger_path()
    with ledger_lock(path):
        ledger = Ledger.load(path, campaign_id=manifest.campaign_id, manifest_sha256=manifest.sha256)
        entry = ledger.active_entry(key)
        refused_by_validator = None
        if entry is not None and entry["state"] == SUCCEEDED and manifest.db_path().exists():
            cell = next((c for c in manifest.cells() if c.key == key), None)
            if cell is not None:
                conn = cohort.open_readonly(manifest.db_path())
                try:
                    verdict = validate_mod.assess_cell(conn, manifest, cell, entry,
                                                       reference_digests(ledger, manifest),
                                                       reference_ollama_version(ledger))
                finally:
                    conn.close()
                if not verdict["accepted"]:
                    refused_by_validator = verdict["problems"]
        entry = ledger.supersede(key, reason, refused_by_validator=refused_by_validator)
        ledger.save()
        return entry


def disown_evaluation(manifest: Manifest, evaluation_id: str, reason: str) -> dict:
    """Record an evaluation in the campaign DB as NOT campaign evidence (e.g. a UI
    retry clone carrying the campaign name). It must be terminal; it stays in the
    database, never counts, and is listed in every receipt."""
    path = manifest.ledger_path()
    with ledger_lock(path):
        ledger = Ledger.load(path, campaign_id=manifest.campaign_id, manifest_sha256=manifest.sha256)
        conn = cohort.open_readonly(manifest.db_path())
        try:
            row = conn.execute("SELECT status FROM evaluation_jobs WHERE id=?", (evaluation_id,)).fetchone()
        finally:
            conn.close()
        if row is None:
            raise LedgerError(f"evaluation {evaluation_id} is not in the campaign database")
        if row["status"] in ("queued", "running"):
            raise LedgerError(f"evaluation {evaluation_id} is {row['status']}; cancel it before disowning it")
        record = ledger.disown(evaluation_id, reason)
        ledger.save()
        return record
