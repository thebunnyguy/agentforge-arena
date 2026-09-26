"""Independent adversarial tests for the campaign LAUNCHER and its operator CLI.

The launcher is driven end-to-end against the REAL app (``create_app()`` under a
FastAPI ``TestClient``) bound to a clean, freshly initialised campaign database:
POST /api/v1/jobs -> evaluation snapshot -> trials -> worker thread -> raw runs.
The agent factory is a reference-overlay test double that DECLARES the
``ollama`` backend, so every run is provenance-real. Ollama itself is faked
(``afa_campaign.ollama.inventory`` / ``warm_up`` / ``probe``); nothing touches the
network. Every launcher wait is bounded by a wall-clock deadline so a hang fails
fast.

The runtime-code check (``launcher.check_runtime_code``) shells out to git on the
real checkout; an autouse fixture replaces it with a PASSING stand-in so every
launch and resume here takes the official path (``check_code=True``, recorded in
the ledger and required by the validator). Tests of the failing path override it.

Tests that assert behaviour the product does not (yet) have are marked
``xfail(strict=True, reason="PRODUCT BUG: ...")``: they fail until the product is
fixed, and then XPASS, which fails the suite so the marker is removed.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from contextlib import closing, contextmanager
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from afa_campaign import api as api_mod
from afa_campaign import cli, cohort, launcher, ollama, paths
from afa_campaign import status as status_mod
from afa_campaign import validate as validate_mod
from afa_campaign.api import ApiError, ApiNotSent, ApiUnreachable
from afa_campaign.launcher import CampaignStop, Launcher, resume_cell, supersede_cell
from afa_campaign.ledger import (
    FAILED, REJECTED, SUBMITTED, SUBMITTING, SUCCEEDED, SUPERSEDED, Ledger, LedgerError,
)
from afa_campaign.manifest import CAMPAIGN_ID, Manifest, derive_subset, dump, expected_counts

from afa_api import db as app_db
from afa_api import jobs, worker
from afa_api.main import create_app
from afa_api.schemas import JobCreate

HISTORICAL_SHA256 = "42b6dad85ee662d6d5d7f75ffbda5a3b95d50837837f81c875730a8987838ced"
TASK = "two-sum-indices"
MODEL = "qwen2.5-coder:3b"


# --------------------------------------------------------------------------- #
# test doubles
# --------------------------------------------------------------------------- #


def declared_factory(backend_kind: str | None = "ollama"):
    def factory(model, task, params):
        return worker.mock_agent_factory(model, task, params)

    if backend_kind is not None:
        factory.backend_kind = backend_kind  # type: ignore[attr-defined]
    return factory


def failing_factory(model, task, params):
    raise RuntimeError("simulated backend failure")


failing_factory.backend_kind = "ollama"  # type: ignore[attr-defined]


class ConcurrencyProbe:
    """Declared-ollama factory whose agents record how many DISTINCT evaluations
    are executing a trial at the same moment."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.active: dict[str, int] = {}
        self.max_active = 0
        self.trials: list[str] = []

        def factory(model, task, params):
            agent = worker.mock_agent_factory(model, task, params)
            inner, name, probe = agent.act, params.name, self

            def act(workspace, task_, sandbox):
                with probe._lock:
                    probe.active[name] = probe.active.get(name, 0) + 1
                    probe.max_active = max(probe.max_active, sum(1 for n in probe.active.values() if n))
                    probe.trials.append(name)
                try:
                    return inner(workspace, task_, sandbox)
                finally:
                    with probe._lock:
                        probe.active[name] -= 1

            agent.act = act
            return agent

        factory.backend_kind = "ollama"  # type: ignore[attr-defined]
        self.factory = factory


class ApiAdapter:
    """The AgentForgeApi interface over a TestClient (HTTP semantics kept:
    status >= 400 raises ApiError with status and body)."""

    base = "http://testserver/api/v1"

    def __init__(self, client: TestClient) -> None:
        self.client = client
        self.posts: list[dict] = []
        self.violations: list[list[str]] = []
        self.fail_before_post: ApiError | None = None
        self.lose_next_response = False

    def _json(self, method: str, path: str, response):
        try:
            body = response.json()
        except ValueError:
            body = None
        if response.status_code >= 400:
            raise ApiError(f"{method} {path} -> HTTP {response.status_code}: {body}",
                           status=response.status_code, body=body)
        return body

    def health(self) -> dict:
        return self._json("GET", "/healthz", self.client.get("/api/v1/healthz"))

    def create_job(self, body: dict) -> dict:
        # the sequential guarantee, checked at the only moment it can be broken
        busy = [j["id"] for j in self.list_jobs() if j["status"] in ("queued", "running")]
        if busy:
            self.violations.append(busy)
        if self.fail_before_post is not None:
            exc, self.fail_before_post = self.fail_before_post, None
            raise exc
        self.posts.append(body)
        created = self._json("POST", "/jobs", self.client.post("/api/v1/jobs", json=body))
        if self.lose_next_response:
            self.lose_next_response = False
            raise ApiUnreachable("POST /jobs: connection reset by peer (simulated)")
        return created

    def get_job(self, evaluation_id: str) -> dict:
        return self._json("GET", f"/jobs/{evaluation_id}", self.client.get(f"/api/v1/jobs/{evaluation_id}"))

    def list_jobs(self) -> list[dict]:
        return self._json("GET", "/jobs", self.client.get("/api/v1/jobs"))["jobs"]

    def report(self, evaluation_id: str) -> dict:
        return self._json("GET", "/report", self.client.get(f"/api/v1/jobs/{evaluation_id}/report.json"))

    def resume(self, evaluation_id: str) -> dict:
        return self._json("POST", "/resume", self.client.post(f"/api/v1/jobs/{evaluation_id}/resume"))


class FakeOllama:
    """Offline stand-in for ``afa_campaign.ollama`` (inventory / warm_up / probe).

    Inventory call order in a launch: 1 = preflight, then per cell one call before
    the submission (``_prepare_model``) and one before the cell is accepted
    (``_finalize``); the identity watch while an evaluation runs adds one call per
    poll, which ``make_launcher`` disables (``identity_poll_s=inf``) unless a test
    drives it with a fake clock. ``from_call`` schedules overrides by call number
    (``{"digests": ..., "missing": ..., "unreachable": bool, "version": str}``);
    ``version`` is the Ollama SERVER version every inventory reports (round 4:
    part of the campaign's identity)."""

    def __init__(self, models: list[str]) -> None:
        self.digests = {m: "sha256:" + "abcdef"[i % 6] * 64 for i, m in enumerate(models)}
        self.missing: set[str] = set()
        self.unreachable = False
        self.version = "0.0-fake"
        self.calls = 0
        self.after_first: dict | None = None  # {"digests": {...}, "missing": {...}} from call 2 on
        self.from_call: dict[int, dict] = {}  # {n: {"digests": ..., "missing": ..., "unreachable": ...}}
        self.warmed: list[str] = []
        self.warm_error: str | None = None
        self.probe_error: str | None = None
        self.probes = 0
        self.probed: list[str | None] = []  # the model each probe asked to generate (None: server only)

    def inventory(self, base_url: str, models: list[str]) -> dict:
        self.calls += 1
        unreachable = self.unreachable
        for start in sorted(self.from_call):
            if self.calls >= start and "unreachable" in self.from_call[start]:
                unreachable = self.from_call[start]["unreachable"]
        if unreachable:
            raise ollama.OllamaError("GET /api/version: connection refused (simulated)")
        digests, missing, version = dict(self.digests), set(self.missing), self.version
        if self.after_first is not None and self.calls > 1:
            digests.update(self.after_first.get("digests", {}))
            missing |= set(self.after_first.get("missing", ()))
            version = self.after_first.get("version", version)
        for start in sorted(self.from_call):
            if self.calls >= start:
                digests.update(self.from_call[start].get("digests", {}))
                missing |= set(self.from_call[start].get("missing", ()))
                version = self.from_call[start].get("version", version)
        out = {
            m: ({"present": False} if m in missing else
                {"present": True, "name": m, "model": m, "digest": digests[m], "size": 1,
                 "modified_at": "2026-09-01T00:00:00Z", "details": {"family": "fake"}})
            for m in models
        }
        return {"captured_at": "2026-09-26T00:00:00Z", "source": "fake", "base_url": base_url,
                "ollama_version": version, "models": out,
                "missing": [m for m in models if m in missing], "unrequested_local_models": []}

    def warm_up(self, base_url: str, model: str, **_: object) -> None:
        if self.warm_error:
            raise ollama.OllamaError(self.warm_error)
        self.warmed.append(model)

    def probe(self, base_url: str, model: str | None = None, **_: object) -> None:
        self.probes += 1
        self.probed.append(model)
        if self.probe_error:
            raise ollama.OllamaError(self.probe_error)

    def install(self, monkeypatch) -> "FakeOllama":
        monkeypatch.setattr(ollama, "inventory", self.inventory)
        monkeypatch.setattr(ollama, "warm_up", self.warm_up)
        monkeypatch.setattr(ollama, "probe", self.probe)
        return self


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def base() -> Manifest:
    return Manifest.load()


@pytest.fixture(autouse=True)
def code_check(monkeypatch) -> list[str]:
    """A PASSING runtime-code check (the real one shells out to git on this
    checkout). ``head`` must be truthy: the launch record's ``check_code`` is
    ``check_code and head``. Returns the campaign id of every check made."""
    calls: list[str] = []

    def passing(manifest: Manifest) -> tuple[list[str], dict]:
        calls.append(manifest.campaign_id)
        code = manifest.data["code"]
        return [], {"head": "c0de" * 10, "tag": code["runtime_release_tag"],
                    "release_commit": code["runtime_release_commit"]}

    monkeypatch.setattr(launcher, "check_runtime_code", passing)
    return calls


def make_campaign(base: Manifest, tmp_path: Path, models: list[str], tasks: list[str], reps: int,
                  *, campaign_id: str = "t-launch", init: bool = True, name: str = "c") -> Manifest:
    data = derive_subset(base.data, campaign_id=campaign_id, models=models, task_ids=tasks,
                         repetitions=reps, campaign_db=str(tmp_path / f"{name}.sqlite"),
                         runtime_dir=str(tmp_path / f"{name}-rt"), purpose="test")
    manifest = Manifest(data)
    if init:
        launcher.init_db(manifest)
    return manifest


@contextmanager
def running_app(db_path: Path, factory):
    app = create_app()
    app.state.db_path = db_path
    app.state.agent_factory = factory
    with TestClient(app) as client:
        yield app, ApiAdapter(client)


def deadline_sleep(limit_s: float = 90.0):
    end = time.monotonic() + limit_s

    def _sleep(_seconds: float) -> None:
        if time.monotonic() > end:
            raise AssertionError("the launcher waited past the test deadline")
        time.sleep(0.01)

    return _sleep


def make_launcher(manifest: Manifest, api: ApiAdapter, logs: list[str] | None = None, **options) -> Launcher:
    """A fast launcher. The identity watch is off (``identity_poll_s=inf``) so the
    FakeOllama call numbering never depends on wall-clock time; the tests of the
    watch pass ``identity_poll_s``/``clock``/``sleep`` explicitly."""
    options = {"poll_s": 0.01, "sleep": deadline_sleep(), "warmup": True, "identity_poll_s": float("inf"),
               **options}
    return Launcher(manifest, api, log=(logs.append if logs is not None else (lambda _m: None)), **options)


def run(manifest: Manifest, api: ApiAdapter, *, check_code: bool = True, **kw) -> dict:
    return make_launcher(manifest, api, kw.pop("logs", None)).run("A", check_code=check_code, **kw)


def load_ledger(manifest: Manifest) -> Ledger:
    return Ledger.load(manifest.ledger_path(), campaign_id=manifest.campaign_id,
                       manifest_sha256=manifest.sha256)


def evaluation_ids(manifest: Manifest) -> set[str]:
    with closing(cohort.open_readonly(manifest.db_path())) as conn:
        return {r["id"] for r in conn.execute("SELECT id FROM evaluation_jobs")}


def submitting_entry(manifest: Manifest, fake: "FakeOllama | None" = None) -> dict:
    """A ledger entry written BEFORE the POST, as the launcher does. With ``fake``
    it also carries what the current launcher records before the POST (digest,
    server version, warm-up, code check); without it, it is what an older
    launcher left behind."""
    cell = manifest.cells()[0]
    ledger = Ledger.open_or_create(manifest.ledger_path(), campaign_id=manifest.campaign_id,
                                   manifest_sha256=manifest.sha256, manifest_path="")
    entry = ledger.new_entry(key=cell.key, model=cell.model, task_id=cell.task_id, phase=cell.phase,
                             evaluation_name=manifest.evaluation_name(cell),
                             positions=list(range(manifest.repetitions)))
    if fake is not None:
        ledger.update(entry, model_digest_at_submit=fake.digests[cell.model], ollama_version_at_submit=fake.version,
                      warmed_up_at_submit=True, code_check_at_submit=True,
                      submitted_by_launch="2026-09-26T00:00:00Z")
    ledger.save()
    return entry


def create_directly(manifest: Manifest, body: dict) -> str:
    """An evaluation written into the campaign DB without being dispatched."""
    with closing(app_db.connect(manifest.db_path())) as conn:
        return jobs.create_job(conn, JobCreate(**body)).id


def events(manifest: Manifest) -> list[dict]:
    return load_ledger(manifest).data["events"]


# =========================================================================== #
# end to end
# =========================================================================== #


def test_campaign_runs_end_to_end_sequentially_pauses_and_resumes(base, tmp_path, monkeypatch):
    models = ["qwen2.5-coder:3b", "gemma2:2b", "llama3.2:latest"]
    m = make_campaign(base, tmp_path, models, [TASK], 2)
    cells = m.cells()
    assert [c.model for c in cells] == ["qwen2.5-coder:3b", "llama3.2:latest", "gemma2:2b"]
    fake = FakeOllama(m.models).install(monkeypatch)
    probe = ConcurrencyProbe()
    logs: list[str] = []
    with running_app(m.db_path(), probe.factory) as (_app, api):
        first = run(m, api, max_evaluations=1, logs=logs)
        assert first == {"submitted": 1, "paused": True, "drained": 0, "skipped": 0, "succeeded": 1}
        ledger = load_ledger(m)
        first_id = ledger.active_entry(cells[0].key)["evaluation_id"]
        assert ledger.active_entry(cells[0].key)["state"] == SUCCEEDED
        assert ledger.active_entry(cells[1].key) is None and ledger.active_entry(cells[2].key) is None
        assert evaluation_ids(m) == {first_id}

        second = run(m, api, max_evaluations=1, logs=logs)
        assert second == {"submitted": 1, "paused": True, "drained": 0, "skipped": 1, "succeeded": 1}
        third = run(m, api, logs=logs)
        assert third == {"submitted": 1, "paused": False, "drained": 0, "skipped": 2, "succeeded": 1}
        again = run(m, api, logs=logs)  # a finished phase is a no-op
        assert again == {"submitted": 0, "paused": False, "drained": 0, "skipped": 3, "succeeded": 0}

    ledger = load_ledger(m)
    ids = [ledger.active_entry(c.key)["evaluation_id"] for c in cells]
    assert ids[0] == first_id and len(set(ids)) == 3
    assert all(ledger.active_entry(c.key)["state"] == SUCCEEDED for c in cells)
    assert len(ledger.entries) == 3
    # never re-created: exactly one evaluation per cell, one POST per cell
    assert evaluation_ids(m) == set(ids)
    assert api.posts == [m.job_body(c) for c in cells]
    # sequential: nothing queued/running at any submission, no overlapping trials
    assert api.violations == []
    assert probe.max_active == 1
    with closing(cohort.open_readonly(m.db_path())) as conn:
        rows = conn.execute(
            "SELECT id, params_json, started_at, finished_at FROM evaluation_jobs ORDER BY created_at, rowid"
        ).fetchall()
        assert [r["id"] for r in rows] == ids
        for earlier, later in zip(rows, rows[1:]):
            assert later["started_at"] >= earlier["finished_at"]
        runs = conn.execute("SELECT id, job_id, backend_kind, agent, task_id, idx FROM runs").fetchall()
        assert len(runs) == 6
        assert {r["backend_kind"] for r in runs} == {"ollama"}
        assert {r["job_id"] for r in runs} == set(ids)
        for cell, evaluation_id in zip(cells, ids):
            owned = [r for r in runs if r["job_id"] == evaluation_id]
            assert sorted((r["agent"], r["task_id"], r["idx"]) for r in owned) == [
                (cell.model, cell.task_id, 0), (cell.model, cell.task_id, 1)]
            result = cohort.check_cell_evaluation(conn, m, cell, evaluation_id)
            assert result.ok, result.as_dict()
            assert ledger.active_entry(cell.key)["summary"]["run_ids"] == result.run_ids
    # the model is warmed before EVERY submission (contract change 4)
    assert fake.warmed == [c.model for c in cells]
    # launches are recorded with their outcome and the evidence hash at both ends
    launches = ledger.data["launches"]
    assert [l["outcome"] for l in launches] == ["paused", "paused", "phase-complete", "phase-complete"]
    for launch in launches:
        assert launch["historical_evidence_sha256_start"] == HISTORICAL_SHA256
        assert launch["historical_evidence_sha256_end"] == HISTORICAL_SHA256
        assert launch["inventory"]["models"][cells[0].model]["digest"] == fake.digests[cells[0].model]
        # round 3: every launch records its (passing) runtime-code check and warm-up policy
        assert launch["check_code"] is True and launch["warmup"] is True
    kinds = [e["type"] for e in ledger.data["events"]]
    assert kinds.count("submitted") == 3 and kinds.count("cell_succeeded") == 3
    assert "halt" not in kinds
    for evaluation_id in ids:
        assert (m.runtime_dir() / "evaluation-reports" / f"{evaluation_id}.json").exists()
    assert any("pausing" in line for line in logs)
    # the campaign is complete by the validator's and the monitor's standards
    receipt = validate_mod.validate_campaign(m)
    assert receipt["complete"] is True, receipt["problems"]
    st = status_mod.campaign_status(m)
    assert st["cells"]["complete"] == 3 and st["totals"]["remaining_runs"] == 0
    assert st["evaluations_running"] == [] and st["evaluations_halted"] == []


# =========================================================================== #
# crash recovery and duplicates
# =========================================================================== #


def test_crash_between_submitting_and_recording_the_id_is_adopted(base, tmp_path, monkeypatch):
    m = make_campaign(base, tmp_path, [MODEL], [TASK], 1)
    cell = m.cells()[0]
    fake = FakeOllama(m.models).install(monkeypatch)
    with running_app(m.db_path(), declared_factory()) as (_app, api):
        submitting_entry(m, fake)  # what the current launcher writes before its POST
        created = api.create_job(m.job_body(cell))  # the POST the crashed launcher made
        api.posts.clear()
        result = run(m, api)
    assert api.posts == []  # adopted by name, never POSTed again
    assert evaluation_ids(m) == {created["id"]}
    entry = load_ledger(m).active_entry(cell.key)
    assert entry["evaluation_id"] == created["id"] and entry["state"] == SUCCEEDED
    assert any(e["type"] == "adopted" and e["evaluation_id"] == created["id"] for e in events(m))
    assert result["submitted"] == 0 and result["paused"] is False
    # Was a PRODUCT BUG (the drain finalized the adopted evaluation without
    # counting it); fixed in 138c75f by the 'drained' counter. The submission loop
    # still sees the (now succeeded) cell and reports it as skipped as well.
    assert result == {"submitted": 0, "paused": False, "drained": 1, "skipped": 1, "succeeded": 0}
    launch_end = [e for e in events(m) if e["type"] == "launch_end"][-1]
    assert launch_end["drained"] == 1 and launch_end["submitted"] == 0


def test_lost_post_response_is_reconciled_by_name_not_duplicated(base, tmp_path, monkeypatch):
    m = make_campaign(base, tmp_path, [MODEL], [TASK], 1)
    cell = m.cells()[0]
    FakeOllama(m.models).install(monkeypatch)
    with running_app(m.db_path(), declared_factory()) as (_app, api):
        api.lose_next_response = True
        with pytest.raises(CampaignStop, match="outcome of POST /jobs unknown"):
            run(m, api)
        entry = load_ledger(m).active_entry(cell.key)
        assert entry["state"] == SUBMITTING and entry["evaluation_id"] is None
        (orphan,) = evaluation_ids(m)
        result = run(m, api)
    assert result["submitted"] == 0
    assert len(api.posts) == 1
    assert evaluation_ids(m) == {orphan}
    entry = load_ledger(m).active_entry(cell.key)
    assert entry["evaluation_id"] == orphan and entry["state"] == SUCCEEDED
    # the reconciled (adopted and drained) evaluation is counted as drained (see
    # test_crash_between_submitting_...)
    assert result == {"submitted": 0, "paused": False, "drained": 1, "skipped": 1, "succeeded": 0}


def test_refused_and_failed_posts(base, tmp_path, monkeypatch):
    m = make_campaign(base, tmp_path, [MODEL], [TASK], 1)
    cell = m.cells()[0]
    FakeOllama(m.models).install(monkeypatch)
    with running_app(m.db_path(), declared_factory()) as (_app, api):
        # 4xx: the app refused; nothing was created, the entry is withdrawn
        api.fail_before_post = ApiError("HTTP 422", status=422, body={"error": "bad"})
        with pytest.raises(CampaignStop, match="refused"):
            run(m, api)
        assert load_ledger(m).entries == [] and evaluation_ids(m) == set()
        assert any(e["type"] == "submit_refused" for e in events(m))
        # 5xx: outcome unknown; the entry stays 'submitting' for reconciliation
        api.fail_before_post = ApiError("HTTP 503", status=503, body=None)
        with pytest.raises(CampaignStop, match="outcome of POST /jobs unknown"):
            run(m, api)
        entry = load_ledger(m).active_entry(cell.key)
        assert entry["state"] == SUBMITTING and entry["evaluation_id"] is None
        # round 4: written BEFORE the POST - the identity, warm-up and code check the
        # submission was made under, and by which launch
        launch = load_ledger(m).data["launches"][-1]
        assert (entry["model_digest_at_submit"], entry["ollama_version_at_submit"]) == (
            launch["inventory"]["models"][MODEL]["digest"], launch["inventory"]["ollama_version"])
        assert entry["warmed_up_at_submit"] is True and entry["code_check_at_submit"] is True
        assert entry["submitted_by_launch"] == launch["started_at"]
        assert "code_check_at_finalize" not in entry
        assert evaluation_ids(m) == set()
        # round 4: nothing was created, so the next launch's drain DROPS the entry
        # (submission_abandoned) and the cell starts over: submitted exactly once
        result = run(m, api)
    assert result == {"submitted": 1, "paused": False, "drained": 0, "skipped": 0, "succeeded": 1}
    (only,) = evaluation_ids(m)
    assert load_ledger(m).active_entry(cell.key)["evaluation_id"] == only
    assert len(load_ledger(m).entries) == 1
    assert [e["cell"] for e in events(m) if e["type"] == "submission_abandoned"] == [cell.key]


def test_two_evaluations_with_the_campaign_name_halt_as_duplicates(base, tmp_path, monkeypatch):
    m = make_campaign(base, tmp_path, [MODEL], [TASK], 1)
    cell = m.cells()[0]
    FakeOllama(m.models).install(monkeypatch)
    submitting_entry(m)
    twins = {create_directly(m, m.job_body(cell)), create_directly(m, m.job_body(cell))}
    with running_app(m.db_path(), declared_factory()) as (_app, api):
        with pytest.raises(CampaignStop, match="duplicate"):
            run(m, api)
    assert api.posts == []
    assert evaluation_ids(m) == twins
    entry = load_ledger(m).active_entry(cell.key)
    assert entry["state"] == SUBMITTING and entry["evaluation_id"] is None  # neither was adopted
    halt = events(m)[-1]
    assert halt["type"] == "halt" and set(halt["untracked"]) == twins


def test_campaign_named_evaluation_the_ledger_does_not_own_halts(base, tmp_path, monkeypatch):
    m = make_campaign(base, tmp_path, [MODEL, "gemma2:2b"], [TASK], 1)
    FakeOllama(m.models).install(monkeypatch)
    # an evaluation for the SECOND cell appears (a UI clone, a lost ledger, a second launcher)
    orphan = create_directly(m, m.job_body(m.cells()[1]))
    with running_app(m.db_path(), declared_factory()) as (_app, api):
        with pytest.raises(CampaignStop, match="the ledger does not own"):
            run(m, api)
    assert api.posts == [] and evaluation_ids(m) == {orphan}
    assert load_ledger(m).entries == []


# =========================================================================== #
# halts on evaluation outcomes; operator actions
# =========================================================================== #


def test_failed_evaluation_halts_and_resumes_under_the_same_id(base, tmp_path, monkeypatch):
    m = make_campaign(base, tmp_path, [MODEL], [TASK], 1)
    cell = m.cells()[0]
    FakeOllama(m.models).install(monkeypatch)
    with running_app(m.db_path(), failing_factory) as (app, api):
        with pytest.raises(CampaignStop, match="resume it under the same id"):
            run(m, api)
        entry = load_ledger(m).active_entry(cell.key)
        evaluation_id = entry["evaluation_id"]
        assert entry["state"] == FAILED and entry["job_status"] == "failed"
        assert "simulated backend failure" in " ".join(entry["problems"])
        # without an operator action the launcher halts again and creates nothing
        with pytest.raises(CampaignStop, match="is failed"):
            run(m, api)
        assert evaluation_ids(m) == {evaluation_id} and len(api.posts) == 1

        app.state.agent_factory = declared_factory()  # the backend is fixed
        resumed = resume_cell(m, api, cell.key)
        assert resumed["evaluation_id"] == evaluation_id and resumed["state"] == SUBMITTED
        resumed_result = run(m, api)
        assert resumed_result["submitted"] == 0 and resumed_result["paused"] is False
        entry = load_ledger(m).active_entry(cell.key)
        assert entry["state"] == SUCCEEDED and entry["evaluation_id"] == evaluation_id
        assert evaluation_ids(m) == {evaluation_id} and len(api.posts) == 1
        with closing(cohort.open_readonly(m.db_path())) as conn:
            assert cohort.check_cell_evaluation(conn, m, cell, evaluation_id).ok
            assert {r["job_id"] for r in conn.execute("SELECT job_id FROM runs")} == {evaluation_id}
        assert any(e["type"] == "resumed" for e in events(m))
        # a succeeded cell is final: neither resumable nor supersedable
        with pytest.raises(LedgerError):
            resume_cell(m, api, cell.key)
        with pytest.raises(LedgerError):
            supersede_cell(m, cell.key, "I prefer another result")
        # a UI "retry" clone of the finished campaign evaluation halts the next launch
        with closing(app_db.connect(m.db_path())) as conn:
            clone = jobs.retry_job(conn, evaluation_id)
        with pytest.raises(CampaignStop, match="the ledger does not own"):
            run(m, api)
        assert clone.id in str(events(m)[-1])
    assert validate_mod.validate_campaign(m)["complete"] is False  # the clone is 'extra'
    # the launch that finished the resumed evaluation drained it (was a PRODUCT
    # BUG - not counted at all - fixed in 138c75f)
    assert resumed_result == {"submitted": 0, "paused": False, "drained": 1, "skipped": 1, "succeeded": 0}
    resumed = [e for e in events(m) if e["type"] == "resumed"]
    assert len(resumed) == 1 and resumed[0]["check_code"] is True  # the resume ran the code check


def test_evidence_failing_campaign_checks_is_rejected_then_superseded(base, tmp_path, monkeypatch):
    m = make_campaign(base, tmp_path, [MODEL], [TASK], 1)
    cell = m.cells()[0]
    FakeOllama(m.models).install(monkeypatch)
    # an app whose factory does not attest its backend: runs carry no backend_kind
    with running_app(m.db_path(), declared_factory(None)) as (app, api):
        with pytest.raises(CampaignStop, match="EXCLUDED"):
            run(m, api)
        entry = load_ledger(m).active_entry(cell.key)
        rejected_id = entry["evaluation_id"]
        assert entry["state"] == REJECTED
        assert any("runs.backend_kind is None" in p for p in entry["problems"])
        with pytest.raises(LedgerError):
            resume_cell(m, api, cell.key)  # rejected evidence is never resumed
        with pytest.raises(LedgerError, match="reason"):
            supersede_cell(m, cell.key, "  ")
        supersede_cell(m, cell.key, "worker factory did not attest the backend; fixed")
        app.state.agent_factory = declared_factory()
        result = run(m, api)
    assert result == {"submitted": 1, "paused": False, "drained": 0, "skipped": 0, "succeeded": 1}
    ledger = load_ledger(m)
    states = [(e["state"], e["evaluation_id"]) for e in ledger.entries_for(cell.key)]
    assert states[0] == (SUPERSEDED, rejected_id) and states[1][0] == SUCCEEDED
    assert states[1][1] != rejected_id
    receipt = validate_mod.validate_campaign(m)
    assert receipt["complete"] is True, receipt["problems"]
    assert receipt["cells"][0]["superseded_evaluations"] == [rejected_id]


def infra_voiding_factory(void_idx: int):
    """Declared-ollama agent whose trial at position ``void_idx`` fails on
    infrastructure (the model server 'went away'): the run is VOIDED."""
    from afa_runner.agents import AgentOutcome

    def factory(model, task, params):
        agent = worker.mock_agent_factory(model, task, params)
        inner, state = agent.act, {"seed": None}
        agent.set_run_seed = lambda seed: state.update(seed=seed)

        def act(workspace, task_, sandbox):
            if state["seed"] == params.base_seed + void_idx:
                return AgentOutcome(transcript="transport error (simulated)", infra_failed=True)
            return inner(workspace, task_, sandbox)

        agent.act = act
        return agent

    factory.backend_kind = "ollama"  # type: ignore[attr-defined]
    return factory


def test_voided_positions_halt_as_needs_attention_until_superseded_and_re_evaluated(base, tmp_path, monkeypatch):
    # contract change 1: accept-voided is gone. A cell needs ALL positions valid;
    # an infra-voided cell is superseded and re-evaluated fresh, never accepted short.
    from afa_campaign import launcher as launcher_mod
    from afa_campaign.ledger import NEEDS_ATTENTION

    assert not hasattr(launcher_mod, "accept_voided")
    m = make_campaign(base, tmp_path, [MODEL], [TASK], 2)
    cell = m.cells()[0]
    fake = FakeOllama(m.models).install(monkeypatch)
    with running_app(m.db_path(), infra_voiding_factory(1)) as (app, api):
        with pytest.raises(CampaignStop, match="supersede") as stop:
            run(m, api)
        assert "needs_attention" in str(stop.value) and "all positions valid" in str(stop.value)
        entry = load_ledger(m).active_entry(cell.key)
        voided_id = entry["evaluation_id"]
        assert entry["state"] == NEEDS_ATTENTION and entry["job_status"] == "succeeded"
        assert entry["summary"]["voided"] == 1 and entry["summary"]["valid"] == 1
        with pytest.raises(CampaignStop, match="needs_attention"):
            run(m, api)  # halts again until the operator decides; creates nothing
        assert evaluation_ids(m) == {voided_id} and len(api.posts) == 1
        with pytest.raises(LedgerError):
            resume_cell(m, api, cell.key)  # not failed/canceled: never resumed
        # the validator never counts the voided evaluation
        receipt = validate_mod.validate_campaign(m)
        assert receipt["complete"] is False and receipt["missing"]["cells"] == [cell.key]
        assert receipt["present"]["runs"] == 0 and receipt["missing"]["positions"] == 2
        with pytest.raises(LedgerError, match="reason"):
            supersede_cell(m, cell.key, "   ")
        supersede_cell(m, cell.key, "Ollama restarted mid-trial; position 1 voided")
        app.state.agent_factory = declared_factory()  # the backend is fixed
        result = run(m, api)
    assert result == {"submitted": 1, "paused": False, "drained": 0, "skipped": 0, "succeeded": 1}
    ledger = load_ledger(m)
    states = [(e["state"], e["evaluation_id"]) for e in ledger.entries_for(cell.key)]
    assert states[0] == (SUPERSEDED, voided_id) and states[1][0] == SUCCEEDED
    fresh_id = states[1][1]
    assert fresh_id != voided_id and evaluation_ids(m) == {voided_id, fresh_id}
    assert len(api.posts) == 2 and api.posts[1] == m.job_body(cell)  # a FRESH evaluation, same body
    assert fake.warmed == [MODEL, MODEL]
    receipt = validate_mod.validate_campaign(m)
    assert receipt["complete"] is True, receipt["problems"]
    assert receipt["voided_positions"] == 0 and receipt["present"]["runs"] == 2
    assert receipt["present"]["valid_runs"] == 2
    assert receipt["cells"][0]["superseded_evaluations"] == [voided_id]
    st = status_mod.campaign_status(m)
    assert st["totals"]["voided"] == 0 and st["totals"]["completed_runs"] == 2
    assert st["cells"]["complete"] == 1 and st["superseded_entries"] == 1


def test_resume_answered_with_another_evaluation_id_is_refused(base, tmp_path, monkeypatch):
    # round 3: resume also asks the campaign DATABASE whether anything is queued/running.
    # Round 4: the ledger must carry the first launch's inventory (the server version
    # is re-checked against it), and the refusal is recorded on the entry and reverted.
    m = make_campaign(base, tmp_path, [MODEL], [TASK], 1)
    fake = FakeOllama(m.models).install(monkeypatch)  # resume re-checks identity and warms the model
    key = seed_failed_cell(m, fake)

    class RetargetingApp:
        base = "stub"

        def list_jobs(self):  # contract change 3: resume only on an idle app
            return [{"id": "e-original", "status": "failed"}]

        def resume(self, evaluation_id):
            assert evaluation_id == "e-original"
            # the entry was marked in flight BEFORE the request (round 4)
            assert load_ledger(m).active_entry(key)["state"] == SUBMITTED
            return {"id": "e-somebody-else", "status": "queued"}

    with pytest.raises(CampaignStop, match="different evaluation id"):
        resume_cell(m, RetargetingApp(), key)
    after = load_ledger(m).active_entry(key)
    assert (after["state"], after["evaluation_id"]) == (FAILED, "e-original")
    assert [(r["outcome"], r["from_state"], r["check_code"], r["warmed_up"]) for r in after["resumes"]] == [
        ("refused", FAILED, True, True)]
    refused = [e for e in events(m) if e["type"] == "resume_refused"]
    assert len(refused) == 1 and refused[0]["returned"] == "e-somebody-else"
    assert not any(e["type"] == "resumed" for e in events(m))


# =========================================================================== #
# halting preconditions (no evaluation may be created)
# =========================================================================== #


def test_task_digest_drift_at_submission_stops_the_campaign(base, tmp_path, monkeypatch):
    m = make_campaign(base, tmp_path, [MODEL], [TASK], 1)
    fake = FakeOllama(m.models).install(monkeypatch)
    frozen = launcher.check_task_pins

    def drift_after_preflight(manifest, task_ids=None):
        if task_ids is None:  # the preflight still sees the frozen pack
            return frozen(manifest)
        return [f"{t}: now 1.0.9 sha256:{'e' * 12}..., frozen {manifest.task_by_id[t]['task_version']}"
                for t in task_ids]

    monkeypatch.setattr(launcher, "check_task_pins", drift_after_preflight)
    with running_app(m.db_path(), declared_factory()) as (_app, api):
        with pytest.raises(CampaignStop, match="STOP THE CAMPAIGN"):
            run(m, api)
    assert api.posts == [] and evaluation_ids(m) == set()
    assert load_ledger(m).entries == []
    assert fake.warmed == []  # halted before even loading the model
    assert events(m)[-1]["type"] == "halt" and "STOP THE CAMPAIGN" in events(m)[-1]["message"]


def test_task_digest_drift_before_launch_fails_preflight(base, tmp_path, monkeypatch):
    m = make_campaign(base, tmp_path, [MODEL], [TASK], 1)
    FakeOllama(m.models).install(monkeypatch)
    real = jobs.task_snapshot
    monkeypatch.setattr(jobs, "task_snapshot",
                        lambda task_id: {**real(task_id), "task_digest": "sha256:" + "f" * 64})
    with running_app(m.db_path(), declared_factory()) as (_app, api):
        with pytest.raises(CampaignStop, match="TASK PIN CHANGED"):
            run(m, api)
        # contract change 7: a refused FIRST launch leaves no ledger behind
        assert api.posts == [] and evaluation_ids(m) == set()
        assert not m.ledger_path().exists()
        # once a ledger exists, a refused launch is recorded in it (and creates nothing)
        monkeypatch.setattr(jobs, "task_snapshot", real)
        assert run(m, api, max_evaluations=0)["submitted"] == 0
        monkeypatch.setattr(jobs, "task_snapshot",
                            lambda task_id: {**real(task_id), "task_digest": "sha256:" + "f" * 64})
        with pytest.raises(CampaignStop, match="TASK PIN CHANGED"):
            run(m, api)
    assert api.posts == [] and evaluation_ids(m) == set()
    assert load_ledger(m).entries == []
    assert events(m)[-1]["type"] == "preflight_failed"
    assert len(load_ledger(m).data["launches"]) == 1  # the refused launch is not a launch


def test_foreign_queued_evaluation_fails_preflight(base, tmp_path, monkeypatch):
    m = make_campaign(base, tmp_path, [MODEL], [TASK], 1)
    FakeOllama(m.models).install(monkeypatch)
    foreign = create_directly(m, {"model": MODEL, "tasks": [TASK], "repeats": 1})  # a UI mock run
    with running_app(m.db_path(), declared_factory()) as (_app, api):
        with pytest.raises(CampaignStop, match="not owned by the campaign are queued/running"):
            run(m, api)
        assert api.posts == [] and evaluation_ids(m) == {foreign}
        # once it is no longer queued/running it is only a warning
        with closing(app_db.connect(m.db_path())) as conn:
            assert jobs.request_cancel(conn, foreign).status == "canceled"
        pf = launcher.preflight(m, api, check_code=False)
    assert pf.ok, pf.problems
    assert any("not campaign-owned" in w for w in pf.warnings)


def test_app_bound_to_another_database_fails_preflight(base, tmp_path, monkeypatch):
    m = make_campaign(base, tmp_path, [MODEL], [TASK], 1)
    other = make_campaign(base, tmp_path, [MODEL], [TASK], 1, name="other")
    FakeOllama(m.models).install(monkeypatch)
    with running_app(other.db_path(), declared_factory()) as (_app, api):
        pf = launcher.preflight(m, api, check_code=False)
        assert not pf.ok and any("bound to" in p for p in pf.problems)
        with pytest.raises(CampaignStop, match="bound to"):
            run(m, api)
    assert api.posts == [] and evaluation_ids(m) == set() and evaluation_ids(other) == set()


def test_database_seeded_with_historical_runs_fails_preflight(base, tmp_path, monkeypatch):
    m = make_campaign(base, tmp_path, [MODEL], [TASK], 1, init=False)
    FakeOllama(m.models).install(monkeypatch)
    # the app was started BEFORE init-db: it seeds its absent DB from the evidence DB
    with running_app(m.db_path(), declared_factory()) as (_app, api):
        with closing(cohort.open_readonly(m.db_path())) as conn:
            assert cohort.jobless_run_count(conn) == 720
        pf = launcher.preflight(m, api, check_code=False)
        assert [p for p in pf.problems if "outside any evaluation" in p]
        assert len(pf.problems) == 1, pf.problems
        with pytest.raises(CampaignStop, match="clean strategy forbids"):
            run(m, api)
        with pytest.raises(CampaignStop, match="already exists"):
            launcher.init_db(m)
    assert api.posts == [] and evaluation_ids(m) == set()


def test_ollama_digest_change_between_launches_halts(base, tmp_path, monkeypatch):
    m = make_campaign(base, tmp_path, [MODEL], [TASK], 1)
    fake = FakeOllama(m.models).install(monkeypatch)
    with running_app(m.db_path(), declared_factory()) as (_app, api):
        first = run(m, api, max_evaluations=0)  # records the launch (and its inventory), submits nothing
        assert first == {"submitted": 0, "paused": True, "drained": 0, "skipped": 0, "succeeded": 0}
        assert load_ledger(m).data["launches"][0]["inventory"]["models"][MODEL]["digest"] == fake.digests[MODEL]
        fake.digests[MODEL] = "sha256:" + "9" * 64  # the tag now serves different weights
        with pytest.raises(CampaignStop, match="Ollama digest changed since the first launch"):
            run(m, api)
    assert api.posts == [] and evaluation_ids(m) == set()


def test_ollama_digest_change_during_a_launch_halts(base, tmp_path, monkeypatch):
    m = make_campaign(base, tmp_path, [MODEL], [TASK], 1)
    fake = FakeOllama(m.models).install(monkeypatch)
    fake.after_first = {"digests": {MODEL: "sha256:" + "8" * 64}}
    with running_app(m.db_path(), declared_factory()) as (_app, api):
        # contract change 2: checked against the FIRST launch's digest before the submission
        with pytest.raises(CampaignStop, match="differs from the campaign's first-launch digest"):
            run(m, api)
    assert api.posts == [] and evaluation_ids(m) == set() and load_ledger(m).entries == []
    assert fake.warmed == []


def test_model_disappearing_during_a_launch_halts(base, tmp_path, monkeypatch):
    m = make_campaign(base, tmp_path, [MODEL], [TASK], 1)
    fake = FakeOllama(m.models).install(monkeypatch)
    fake.after_first = {"missing": {MODEL}}
    with running_app(m.db_path(), declared_factory()) as (_app, api):
        with pytest.raises(CampaignStop, match="disappeared"):
            run(m, api)
    assert api.posts == [] and evaluation_ids(m) == set()


def test_missing_roster_model_or_unreachable_ollama_fails_preflight(base, tmp_path, monkeypatch):
    m = make_campaign(base, tmp_path, [MODEL, "gemma2:2b"], [TASK], 1)
    fake = FakeOllama(m.models).install(monkeypatch)
    fake.missing = {"gemma2:2b"}
    with running_app(m.db_path(), declared_factory()) as (_app, api):
        with pytest.raises(CampaignStop, match="roster model\\(s\\) missing from Ollama.*gemma2:2b"):
            run(m, api)
        fake.missing = set()
        fake.unreachable = True
        with pytest.raises(CampaignStop, match="Ollama unreachable"):
            run(m, api)
    assert api.posts == [] and evaluation_ids(m) == set()


def test_edited_manifest_after_launch_is_refused(base, tmp_path, monkeypatch):
    m = make_campaign(base, tmp_path, [MODEL], [TASK], 1)
    FakeOllama(m.models).install(monkeypatch)
    edited = dict(m.data, generation={**m.data["generation"], "temperature": 0.2})
    with running_app(m.db_path(), declared_factory()) as (_app, api):
        run(m, api, max_evaluations=0)
        with pytest.raises(LedgerError, match="manifest changed"):
            run(Manifest(edited), api)
    assert api.posts == [] and evaluation_ids(m) == set()


def test_only_one_launcher_at_a_time(base, tmp_path, monkeypatch):
    m = make_campaign(base, tmp_path, [MODEL], [TASK], 1)
    FakeOllama(m.models).install(monkeypatch)
    with running_app(m.db_path(), declared_factory()) as (_app, api):
        run(m, api, max_evaluations=0)
        holder = load_ledger(m)
        with holder.lock():
            with pytest.raises(LedgerError, match="only one launcher"):
                run(m, api)
    assert api.posts == []


# =========================================================================== #
# CLI launch guard
# =========================================================================== #


def test_cli_launch_requires_confirming_the_exact_campaign_id(base, tmp_path, monkeypatch, capsys):
    m = make_campaign(base, tmp_path, [MODEL], [TASK], 1)
    manifest_file = tmp_path / "manifest.json"
    dump(m.data, manifest_file)
    constructed: list[str] = []

    class NoClient:  # proves no API client (no network) is ever built
        def __init__(self, url, **_):
            constructed.append(url)
            raise AssertionError("the launch guard must not contact the app")

    monkeypatch.setattr(api_mod, "AgentForgeApi", NoClient)
    for extra in ([], ["--confirm", ""], ["--confirm", CAMPAIGN_ID], ["--confirm", m.campaign_id.upper()]):
        rc = cli.main(["--manifest", str(manifest_file), "launch", "--phase", "A", *extra])
        assert rc == 2, extra
    out = capsys.readouterr().out
    assert f"--confirm {m.campaign_id}" in out
    assert constructed == []
    assert not m.ledger_path().exists() and not m.runtime_dir().exists()
    assert evaluation_ids(m) == set()


# =========================================================================== #
# Contract of e2c86dc (review round 1): model identity, one evaluation at a
# time, strict completeness, disown, request-timeout probe, drift at finalize
# =========================================================================== #


def two_phase_campaign(base: Manifest, tmp_path: Path) -> Manifest:
    """(MODEL, TASK) in phase A and (gemma2:2b, TASK) in phase B."""
    data = derive_subset(base.data, campaign_id="t-phases", models=[MODEL, "gemma2:2b"], task_ids=[TASK],
                         repetitions=1, campaign_db=str(tmp_path / "p.sqlite"),
                         runtime_dir=str(tmp_path / "p-rt"), purpose="test")
    for cell in data["cells"]:
        if cell["model"] == "gemma2:2b":
            cell["phase"] = "B"
    data["expected"] = expected_counts(data)
    manifest = Manifest(data)
    launcher.init_db(manifest)
    assert [(c.key, c.phase) for c in manifest.cells()] == [(f"{MODEL}|{TASK}", "A"), (f"gemma2:2b|{TASK}", "B")]
    return manifest


def run_phase(manifest: Manifest, api: ApiAdapter, phase: str, *, check_code: bool = True, **kw) -> dict:
    return make_launcher(manifest, api, kw.pop("logs", None)).run(phase, check_code=check_code, **kw)


def seed_failed_cell(manifest: Manifest, fake: FakeOllama, *, evaluation_id: str = "e-original",
                     at_submit: str | None = None) -> str:
    """A ledger whose first launch recorded ``fake``'s inventory and whose only
    cell is FAILED (what a halted launch leaves). Returns the cell key."""
    cell = manifest.cells()[0]
    submitting_entry(manifest, fake)  # with what the current launcher records before its POST
    ledger = load_ledger(manifest)
    ledger.data["launches"].append({"started_at": "2026-09-26T00:00:00Z", "phase": "A", "outcome": "halted",
                                    "inventory": fake.inventory("http://x", manifest.models)})
    ledger.update(ledger.active_entry(cell.key), evaluation_id=evaluation_id, state=FAILED,
                  model_digest_at_submit=at_submit or fake.digests[cell.model])
    ledger.save()
    return cell.key


class StubApp:
    """The resume-relevant AgentForgeApi surface, with a call log."""

    base = "stub"

    def __init__(self, jobs_now=None, *, list_error: ApiError | None = None,
                 resume_error: ApiError | None = None, log: list | None = None) -> None:
        self.jobs_now = jobs_now or []
        self.list_error = list_error
        self.resume_error = resume_error
        self.calls: list = log if log is not None else []

    def list_jobs(self):
        self.calls.append("list_jobs")
        if self.list_error:
            raise self.list_error
        return self.jobs_now

    def resume(self, evaluation_id):
        self.calls.append(("resume", evaluation_id))
        if self.resume_error:
            raise self.resume_error
        return {"id": evaluation_id, "status": "queued"}


def test_model_is_warmed_before_every_submission_and_its_digest_recorded(base, tmp_path, monkeypatch):
    # contract changes 2 and 4: warm before EVERY submission (not only on a model
    # switch); digest recorded at submission and at finalisation
    m = make_campaign(base, tmp_path, [MODEL], [TASK, "grid-paths"], 1)
    fake = FakeOllama(m.models).install(monkeypatch)
    with running_app(m.db_path(), declared_factory()) as (_app, api):
        assert run(m, api) == {"submitted": 2, "paused": False, "drained": 0, "skipped": 0, "succeeded": 2}
    assert fake.warmed == [MODEL, MODEL]
    ledger = load_ledger(m)
    assert launcher.reference_digests(ledger) == {MODEL: fake.digests[MODEL]}
    launch = ledger.data["launches"][0]
    assert launcher.reference_ollama_version(ledger) == fake.version == launch["inventory"]["ollama_version"]
    for cell in m.cells():
        entry = ledger.active_entry(cell.key)
        assert entry["model_digest_at_submit"] == entry["model_digest_at_finalize"] == fake.digests[MODEL]
        # round 4: what the launcher records before the POST and at finalisation
        assert entry["ollama_version_at_submit"] == entry["ollama_version_at_finalize"] == fake.version
        assert entry["warmed_up_at_submit"] is True
        assert entry["code_check_at_submit"] is True and entry["code_check_at_finalize"] is True
        assert entry["submitted_by_launch"] == entry["finalized_by_launch"] == launch["started_at"]
    receipt = validate_mod.validate_campaign(m)
    assert receipt["complete"] is True, receipt["problems"]
    assert receipt["warnings"] == []
    assert receipt["model_identity"] == {"reference_digests": {MODEL: fake.digests[MODEL]},
                                         "reference_ollama_version": fake.version, "required": True}


def test_a_failed_warm_up_halts_before_the_submission(base, tmp_path, monkeypatch):
    m = make_campaign(base, tmp_path, [MODEL], [TASK], 1)
    fake = FakeOllama(m.models).install(monkeypatch)
    fake.warm_error = "POST /api/generate -> HTTP 500 (simulated)"
    with running_app(m.db_path(), declared_factory()) as (_app, api):
        with pytest.raises(CampaignStop, match="could not load"):
            run(m, api)
    assert api.posts == [] and evaluation_ids(m) == set()
    assert load_ledger(m).entries == []


def test_digest_change_between_two_cells_of_one_model_halts_before_the_second_submission(
        base, tmp_path, monkeypatch):
    m = make_campaign(base, tmp_path, [MODEL], [TASK, "grid-paths"], 1)
    first, second = m.cells()
    fake = FakeOllama(m.models).install(monkeypatch)
    reference = fake.digests[MODEL]
    moved = "sha256:" + "7" * 64
    # inventory calls: 1 preflight, 2 before cell 1, 3 accepting cell 1, 4 before cell 2
    fake.from_call = {4: {"digests": {MODEL: moved}}}
    with running_app(m.db_path(), declared_factory()) as (_app, api):
        with pytest.raises(CampaignStop, match="differs from the campaign's first-launch digest"):
            run(m, api)
        assert len(api.posts) == 1 and api.posts[0] == m.job_body(first)
        ledger = load_ledger(m)
        done = ledger.active_entry(first.key)
        assert done["state"] == SUCCEEDED
        assert done["model_digest_at_submit"] == done["model_digest_at_finalize"] == reference
        assert ledger.active_entry(second.key) is None  # nothing written for the second cell
        assert fake.warmed == [MODEL]  # halted before loading the moved model
        assert ledger.data["launches"][-1]["outcome"] == "halted"
        assert ledger.data["events"][-1]["type"] == "halt"
        # the next launch is refused by its preflight while the identity is moved
        with pytest.raises(CampaignStop, match="digest changed since the first launch"):
            run(m, api)
        assert len(api.posts) == 1
        # the original weights are restored: the campaign continues and completes
        fake.from_call = {}
        result = run(m, api)
    assert result["submitted"] == 1
    assert validate_mod.validate_campaign(m)["complete"] is True


def digest_flipping_factory(fake: FakeOllama, model: str, new_digest: str):
    """Declared-ollama agents; the FIRST trial re-tags the model in the fake
    Ollama (an 'ollama pull' while the evaluation runs)."""
    state = {"flipped": False}

    def factory(model_, task, params):
        agent = worker.mock_agent_factory(model_, task, params)
        inner = agent.act

        def act(workspace, task_, sandbox):
            if not state["flipped"]:
                state["flipped"] = True
                fake.digests[model] = new_digest
            return inner(workspace, task_, sandbox)

        agent.act = act
        return agent

    factory.backend_kind = "ollama"  # type: ignore[attr-defined]
    return factory


def test_digest_change_during_an_evaluation_rejects_the_cell_and_excludes_its_evidence(
        base, tmp_path, monkeypatch):
    m = make_campaign(base, tmp_path, [MODEL], [TASK], 1)
    cell = m.cells()[0]
    fake = FakeOllama(m.models).install(monkeypatch)
    reference = fake.digests[MODEL]
    moved = "sha256:" + "6" * 64
    with running_app(m.db_path(), digest_flipping_factory(fake, MODEL, moved)) as (app, api):
        with pytest.raises(CampaignStop):
            run(m, api)
        entry = load_ledger(m).active_entry(cell.key)
        evaluation_id = entry["evaluation_id"]
        assert entry["model_digest_at_submit"] == reference
        # Was a PRODUCT BUG (fixed in 138c75f): _finalize halted on the digest
        # change WITHOUT touching the entry, which stayed 'submitted'; restoring the
        # tag and relaunching then drained and ACCEPTED evidence generated while the
        # weights had changed. The halt is now durable: the entry is REJECTED.
        assert entry["state"] == REJECTED, entry["state"]
        assert entry["model_digest_at_finalize"] == moved
        assert any("digest" in p for p in entry["problems"])
        # the rejected evidence never counts, and is never accepted later
        receipt = validate_mod.validate_campaign(m)
        assert receipt["complete"] is False and receipt["missing"]["cells"] == [cell.key]
        fake.digests[MODEL] = reference  # the original weights are restored
        calls_before = fake.calls
        with pytest.raises(CampaignStop, match="rejected"):
            run(m, api)
        # durable: the relaunch never re-reads the identity for (never re-finalizes)
        # the rejected evaluation - only its own preflight inventory is taken
        assert fake.calls == calls_before + 1
        assert load_ledger(m).active_entry(cell.key)["state"] == REJECTED
        assert len(api.posts) == 1
        supersede_cell(m, cell.key, "model re-tagged during the evaluation; re-run on the reference weights")
        result = run(m, api)
    assert result["submitted"] == 1
    fresh = load_ledger(m).active_entry(cell.key)
    assert fresh["state"] == SUCCEEDED and fresh["evaluation_id"] != evaluation_id
    receipt = validate_mod.validate_campaign(m)
    assert receipt["complete"] is True, receipt["problems"]
    assert receipt["cells"][0]["superseded_evaluations"] == [evaluation_id]


def test_resume_requires_an_idle_app_and_the_reference_model(base, tmp_path, monkeypatch):
    # contract change 3: resume only on an idle app, with task pins and the model
    # digest re-checked, the model warmed first; ApiError becomes CampaignStop.
    # Round 3: the campaign database is asked too, so it must exist (init).
    m = make_campaign(base, tmp_path, [MODEL], [TASK], 1)
    fake = FakeOllama(m.models).install(monkeypatch)
    reference = fake.digests[MODEL]
    key = seed_failed_cell(m, fake)

    def unchanged() -> None:
        entry = load_ledger(m).active_entry(key)
        assert (entry["state"], entry["evaluation_id"]) == (FAILED, "e-original")
        assert not any(e["type"] == "resumed" for e in events(m))

    refusals = [
        (StubApp([{"id": "someone-else", "status": "running"}]), "queued/running"),
        (StubApp([{"id": "e-queued", "status": "queued"}]), "idle app"),
        (StubApp(list_error=ApiUnreachable("GET /jobs: connection refused")), "cannot list evaluations"),
        (StubApp(resume_error=ApiError("HTTP 409", status=409, body={"error": "busy"})), "refused to resume"),
    ]
    for stub, match in refusals:
        with pytest.raises(CampaignStop, match=match):
            resume_cell(m, stub, key)
        unchanged()
    for stub, _ in refusals[:3]:
        assert not any(isinstance(c, tuple) for c in stub.calls)  # POST /resume never sent
    assert fake.warmed == [MODEL]  # only the case that got as far as POST /resume loaded the model
    fake.warmed.clear()

    stub = StubApp()
    fake.digests[MODEL] = "sha256:" + "5" * 64
    with pytest.raises(CampaignStop, match="first-launch digest"):
        resume_cell(m, stub, key)
    fake.digests[MODEL] = reference
    fake.missing = {MODEL}
    with pytest.raises(CampaignStop, match="missing from Ollama"):
        resume_cell(m, stub, key)
    fake.missing = set()
    fake.warm_error = "model load failed (simulated)"
    with pytest.raises(CampaignStop, match="Ollama not ready"):
        resume_cell(m, stub, key)
    fake.warm_error = None
    fake.unreachable = True
    with pytest.raises(CampaignStop, match="Ollama not ready"):
        resume_cell(m, stub, key)
    fake.unreachable = False
    real = jobs.task_snapshot
    monkeypatch.setattr(jobs, "task_snapshot", lambda t: {**real(t), "task_digest": "sha256:" + "f" * 64})
    with pytest.raises(CampaignStop, match="STOP THE CAMPAIGN"):
        resume_cell(m, stub, key)
    monkeypatch.setattr(jobs, "task_snapshot", real)
    assert not any(isinstance(c, tuple) for c in stub.calls)  # POST /resume never sent
    assert fake.warmed == []
    unchanged()

    # all clear: the model is loaded BEFORE the resume is sent
    order: list = []
    monkeypatch.setattr(ollama, "warm_up", lambda base_url, model, **_: order.append(("warm", model)))
    resumed = resume_cell(m, StubApp(log=order), key)
    assert resumed["state"] == SUBMITTED and resumed["evaluation_id"] == "e-original"
    assert order == ["list_jobs", ("warm", MODEL), ("resume", "e-original")]


def test_cli_resume_refusal_is_a_message_and_exit_3(base, tmp_path, monkeypatch, capsys):
    # the database must exist: without it the refusal would come from a missing
    # file (FileNotFoundError -> 'refused:'), not from the busy app under test
    m = make_campaign(base, tmp_path, [MODEL], [TASK], 1)
    fake = FakeOllama(m.models).install(monkeypatch)
    key = seed_failed_cell(m, fake)
    manifest_file = tmp_path / "manifest.json"
    dump(m.data, manifest_file)
    busy = StubApp([{"id": "x", "status": "running"}])
    monkeypatch.setattr(api_mod, "AgentForgeApi", lambda url, **_: busy)
    assert cli.main(["--manifest", str(manifest_file), "resume", "--cell", key]) == 3
    err = capsys.readouterr().err
    assert "refused:" in err and "resume only on an idle app" in err and "'x'" in err
    assert not any(isinstance(c, tuple) for c in busy.calls)  # POST /resume never sent
    assert load_ledger(m).active_entry(key)["state"] == FAILED


def test_a_phase_b_launch_drains_a_resumed_phase_a_cell_before_submitting(base, tmp_path, monkeypatch):
    # round 3 (was: "evaluation(s) of another phase are in flight" halted the
    # phase-B launch until a phase-A launch finished it): EVERY in-flight campaign
    # evaluation, of ANY phase, is finished (and accepted or rejected) first; only
    # then does the phase submit - still one evaluation at a time.
    m = two_phase_campaign(base, tmp_path)
    cell_a, cell_b = m.cells()
    FakeOllama(m.models).install(monkeypatch)
    probe = ConcurrencyProbe()
    logs: list[str] = []
    with running_app(m.db_path(), failing_factory) as (app, api):
        with pytest.raises(CampaignStop, match="is failed"):
            run_phase(m, api, "A")
        failed_id = load_ledger(m).active_entry(cell_a.key)["evaluation_id"]
        app.state.agent_factory = probe.factory
        resume_cell(m, api, cell_a.key)
        assert load_ledger(m).active_entry(cell_a.key)["state"] == SUBMITTED
        result = run_phase(m, api, "B", logs=logs)
    assert result == {"submitted": 1, "paused": False, "drained": 1, "skipped": 0, "succeeded": 1}
    assert any(f"finishing in-flight {cell_a.key} (phase A) before phase B" in line for line in logs)
    ledger = load_ledger(m)
    assert ledger.active_entry(cell_a.key)["state"] == SUCCEEDED
    assert ledger.active_entry(cell_a.key)["evaluation_id"] == failed_id  # the SAME (resumed) evaluation
    assert ledger.active_entry(cell_b.key)["state"] == SUCCEEDED
    assert api.violations == [] and probe.max_active == 1
    assert [p["name"] for p in api.posts] == [m.evaluation_name(cell_a), m.evaluation_name(cell_b)]
    with closing(cohort.open_readonly(m.db_path())) as conn:
        a_row, b_row = (conn.execute("SELECT started_at, finished_at FROM evaluation_jobs WHERE id=?",
                                     (ledger.active_entry(c.key)["evaluation_id"],)).fetchone()
                        for c in (cell_a, cell_b))
    assert b_row["started_at"] >= a_row["finished_at"]  # B never overlapped the drained A
    assert validate_mod.validate_campaign(m)["complete"] is True


def test_a_drained_evaluation_of_another_phase_is_judged_like_its_own(base, tmp_path, monkeypatch):
    # round 3: the drain applies the full acceptance (_finalize) to the other
    # phase's evaluation. Here it fails again: the phase-B launch halts on the
    # phase-A cell BEFORE submitting anything, the cell is durably FAILED, and it
    # never blocks phase B afterwards (no cross-phase deadlock).
    m = two_phase_campaign(base, tmp_path)
    cell_a, cell_b = m.cells()
    FakeOllama(m.models).install(monkeypatch)
    with running_app(m.db_path(), failing_factory) as (app, api):
        with pytest.raises(CampaignStop, match="is failed"):
            run_phase(m, api, "A")
        resume_cell(m, api, cell_a.key)  # the backend is NOT fixed: it fails again
        with pytest.raises(CampaignStop) as stop:
            run_phase(m, api, "B")
        assert f"cell {cell_a.key} " in str(stop.value) and "is failed" in str(stop.value)
        assert len(api.posts) == 1  # nothing submitted for phase B
        ledger = load_ledger(m)
        assert ledger.active_entry(cell_a.key)["state"] == FAILED
        assert ledger.active_entry(cell_b.key) is None
        app.state.agent_factory = declared_factory()
        # phase B is not blocked by phase A's halted cell
        assert run_phase(m, api, "B")["submitted"] == 1
        with pytest.raises(CampaignStop, match="is failed"):
            run_phase(m, api, "A")  # phase A still halts until the operator acts
    assert load_ledger(m).active_entry(cell_b.key)["state"] == SUCCEEDED
    assert api.violations == []
    assert validate_mod.validate_campaign(m)["complete"] is False


def test_another_phases_unreconciled_submission_never_blocks_nor_duplicates(base, tmp_path, monkeypatch):
    # round 3 (was: an in-flight entry of ANOTHER phase halted the launch): a
    # phase-A 'submitting' entry whose POST created nothing is not running
    # anything. Round 4: the drain at the start of ANY launch drops it (event
    # submission_abandoned) - the cell starts over; phase A then submits it once.
    m = two_phase_campaign(base, tmp_path)
    cell_a, cell_b = m.cells()
    FakeOllama(m.models).install(monkeypatch)
    with running_app(m.db_path(), declared_factory()) as (_app, api):
        run_phase(m, api, "B", max_evaluations=0)  # creates the ledger
        ledger = load_ledger(m)
        ledger.new_entry(key=cell_a.key, model=cell_a.model, task_id=cell_a.task_id, phase="A",
                         evaluation_name=m.evaluation_name(cell_a), positions=[0])
        ledger.save()
        assert run_phase(m, api, "B") == {"submitted": 1, "paused": False, "drained": 0, "skipped": 0,
                                          "succeeded": 1}
        ledger = load_ledger(m)
        assert ledger.active_entry(cell_a.key) is None and ledger.entries_for(cell_a.key) == []
        abandoned = [e for e in ledger.data["events"] if e["type"] == "submission_abandoned"]
        assert [e["cell"] for e in abandoned] == [cell_a.key]
        # phase A starts the cell over (nothing was created: it submits once)
        assert run_phase(m, api, "A")["submitted"] == 1
    assert [p["name"] for p in api.posts] == [m.evaluation_name(cell_b), m.evaluation_name(cell_a)]
    assert api.violations == []
    assert len(load_ledger(m).entries) == 2
    assert validate_mod.validate_campaign(m)["complete"] is True


def test_a_dropped_submission_of_another_phase_no_longer_blocks_a_resume(base, tmp_path, monkeypatch):
    # round 4: a stale 'submitting' entry (a crash before the POST) used to block
    # every resume ('still in flight') until its own phase was launched; any launch
    # now drops it, so the failed cell of the OTHER phase can be resumed.
    m = two_phase_campaign(base, tmp_path)
    cell_a, cell_b = m.cells()
    FakeOllama(m.models).install(monkeypatch)
    with running_app(m.db_path(), failing_factory) as (app, api):
        with pytest.raises(CampaignStop, match="is failed"):
            run_phase(m, api, "A")
        ledger = load_ledger(m)
        ledger.new_entry(key=cell_b.key, model=cell_b.model, task_id=cell_b.task_id, phase="B",
                         evaluation_name=m.evaluation_name(cell_b), positions=[0])
        ledger.save()
        with pytest.raises(CampaignStop, match="still in flight"):
            resume_cell(m, api, cell_a.key)
        with pytest.raises(CampaignStop, match="is failed"):
            run_phase(m, api, "A")  # the drain drops B's entry, then A's own cell halts again
        assert load_ledger(m).active_entry(cell_b.key) is None
        assert any(e["type"] == "submission_abandoned" and e["cell"] == cell_b.key for e in events(m))
        app.state.agent_factory = declared_factory()
        assert resume_cell(m, api, cell_a.key)["state"] == SUBMITTED
        assert run_phase(m, api, "A")["drained"] == 1
        assert run_phase(m, api, "B")["submitted"] == 1
    assert len(api.posts) == 2 and api.violations == []
    assert validate_mod.validate_campaign(m)["complete"] is True


@pytest.mark.parametrize("recorded", ["round-4 launcher", "older launcher"])
def test_another_phases_evaluation_created_before_a_crash_is_adopted_and_drained(base, tmp_path, monkeypatch,
                                                                                  recorded):
    # round 3: a phase-A launcher died between its POST and recording the id; the
    # phase-B launch adopts that evaluation by name, waits for it, accepts it
    # (drained) and only then submits phase B - never a second phase-A POST.
    # Round 4: the crashed launcher had recorded (BEFORE its POST) the identity, the
    # warm-up and the code check it submitted under; an entry without them (an older
    # launcher) is still drained, but its evidence is never accepted.
    m = two_phase_campaign(base, tmp_path)
    cell_a, cell_b = m.cells()
    fake = FakeOllama(m.models).install(monkeypatch)
    probe = ConcurrencyProbe()
    with running_app(m.db_path(), probe.factory) as (_app, api):
        run_phase(m, api, "B", max_evaluations=0)  # creates the ledger (and the identity reference)
        ledger = load_ledger(m)
        entry = ledger.new_entry(key=cell_a.key, model=cell_a.model, task_id=cell_a.task_id, phase="A",
                                 evaluation_name=m.evaluation_name(cell_a), positions=[0])
        ledger.update(entry, model_digest_at_submit=fake.digests[cell_a.model])
        if recorded == "round-4 launcher":
            ledger.update(entry, ollama_version_at_submit=fake.version, warmed_up_at_submit=True,
                          code_check_at_submit=True, submitted_by_launch="2026-09-26T00:00:00Z")
        ledger.save()
        created = api.create_job(m.job_body(cell_a))["id"]  # the POST the crashed launcher made
        api.posts.clear()
        if recorded == "older launcher":
            # round 5: the launcher applies the validator's predicate before marking a
            # cell succeeded, so the drained evaluation lands REJECTED (supersedable),
            # the launch halts, and phase B is not submitted behind it
            with pytest.raises(CampaignStop, match="not official campaign evidence"):
                run_phase(m, api, "B")
            assert api.posts == []
            entry = load_ledger(m).active_entry(cell_a.key)
            assert entry["state"] == REJECTED and entry["evaluation_id"] == created
            assert any("a passing runtime-code check" in p
                       for p in entry["problems"])
            assert any("Ollama server version" in p for p in entry["problems"])
            assert any("not loaded before every start" in p for p in entry["problems"])
            launcher.supersede_cell(m, cell_a.key, "submitted by an older launcher without identity records")
            assert load_ledger(m).active_entry(cell_a.key) is None
            receipt = validate_mod.validate_campaign(m)
            assert receipt["complete"] is False and cell_a.key in receipt["missing"]["cells"]
            return
        result = run_phase(m, api, "B")
    assert result == {"submitted": 1, "paused": False, "drained": 1, "skipped": 0, "succeeded": 1}
    assert [p["name"] for p in api.posts] == [m.evaluation_name(cell_b)]
    ledger = load_ledger(m)
    assert ledger.active_entry(cell_a.key)["evaluation_id"] == created
    assert ledger.active_entry(cell_a.key)["state"] == SUCCEEDED
    assert any(e["type"] == "adopted" and e["evaluation_id"] == created for e in ledger.data["events"])
    assert api.violations == [] and probe.max_active == 1
    assert evaluation_ids(m) == {created, ledger.active_entry(cell_b.key)["evaluation_id"]}
    receipt = validate_mod.validate_campaign(m)
    assert receipt["complete"] is True, receipt["problems"]


class Killed(BaseException):
    """The launcher process dies (SIGKILL) - not an Exception, never handled."""


class GatedProbe(ConcurrencyProbe):
    """ConcurrencyProbe whose trials block until ``gate`` is set (bounded)."""

    def __init__(self) -> None:
        super().__init__()
        self.gate = threading.Event()
        inner = self.factory

        def factory(model, task, params):
            agent = inner(model, task, params)
            act = agent.act

            def gated(workspace, task_, sandbox):
                assert self.gate.wait(60), "the test never opened the gate"
                return act(workspace, task_, sandbox)

            agent.act = gated
            return agent

        factory.backend_kind = "ollama"  # type: ignore[attr-defined]
        self.factory = factory


def test_a_launcher_killed_while_waiting_is_drained_before_any_new_submission(base, tmp_path, monkeypatch):
    m = make_campaign(base, tmp_path, [MODEL, "gemma2:2b"], [TASK], 1)
    first, second = m.cells()
    FakeOllama(m.models).install(monkeypatch)
    probe = GatedProbe()
    try:
        with running_app(m.db_path(), probe.factory) as (_app, api):
            def die(_seconds: float) -> None:
                raise Killed()

            killed = Launcher(m, api, log=lambda _m: None, poll_s=0.01, sleep=die)
            with pytest.raises(Killed):
                killed.run("A", check_code=True)
            ledger = load_ledger(m)
            entry = ledger.active_entry(first.key)
            assert entry["state"] == SUBMITTED
            assert api.get_job(entry["evaluation_id"])["status"] in ("queued", "running")
            assert ledger.data["launches"][-1]["outcome"] == "running"  # it never recorded its end

            inner = deadline_sleep()

            def release(seconds: float) -> None:
                probe.gate.set()
                inner(seconds)

            result = Launcher(m, api, log=lambda _m: None, poll_s=0.01, sleep=release).run("A", check_code=True)
    finally:
        probe.gate.set()
    assert result["submitted"] == 1
    assert api.violations == [] and probe.max_active == 1
    assert len(api.posts) == 2  # the killed launcher's evaluation was waited for, never re-POSTed
    ledger = load_ledger(m)
    assert [ledger.active_entry(c.key)["state"] for c in (first, second)] == [SUCCEEDED, SUCCEEDED]
    assert ledger.active_entry(first.key)["evaluation_id"] == entry["evaluation_id"]
    assert [l["outcome"] for l in ledger.data["launches"]] == ["interrupted", "phase-complete"]
    assert any(e["type"] == "launch_interrupted" for e in ledger.data["events"])
    with closing(cohort.open_readonly(m.db_path())) as conn:
        rows = conn.execute("SELECT id, started_at, finished_at FROM evaluation_jobs ORDER BY created_at, rowid").fetchall()
    assert rows[1]["started_at"] >= rows[0]["finished_at"]


class HookedApi(ApiAdapter):
    """ApiAdapter with a hook run before the n-th ``health`` call (1 = preflight,
    then one per submission) and one run when an evaluation first reads terminal."""

    def __init__(self, client, *, before_health: dict | None = None, on_terminal=None) -> None:
        super().__init__(client)
        self.before_health = before_health or {}
        self.on_terminal = on_terminal
        self.health_calls = 0
        self._seen_terminal: set[str] = set()

    def health(self) -> dict:
        self.health_calls += 1
        hook = self.before_health.get(self.health_calls)
        if hook:
            hook()
        return super().health()

    def get_job(self, evaluation_id: str) -> dict:
        job = super().get_job(evaluation_id)
        if job.get("status") in launcher.TERMINAL and evaluation_id not in self._seen_terminal:
            self._seen_terminal.add(evaluation_id)
            if self.on_terminal:
                self.on_terminal(evaluation_id)
                job = super().get_job(evaluation_id)
        return job


@contextmanager
def hooked_app(db_path: Path, factory, **hooks):
    app = create_app()
    app.state.db_path = db_path
    app.state.agent_factory = factory
    with TestClient(app) as client:
        yield app, HookedApi(client, **hooks)


def test_an_evaluation_appearing_mid_launch_halts_the_next_submission(base, tmp_path, monkeypatch):
    # contract change 3: _check_app_state refuses to submit while ANY evaluation
    # is queued/running on the app (not only non-campaign ones)
    m = make_campaign(base, tmp_path, [MODEL, "gemma2:2b"], [TASK], 1)
    first, second = m.cells()
    FakeOllama(m.models).install(monkeypatch)
    appeared: list[str] = []
    ui_run = lambda: appeared.append(create_directly(m, {"model": MODEL, "tasks": [TASK], "repeats": 1}))  # noqa: E731
    with hooked_app(m.db_path(), declared_factory(), before_health={3: ui_run}) as (_app, api):
        with pytest.raises(CampaignStop, match="queued/running on the app") as stop:
            run(m, api)
    assert appeared and appeared[0] in str(stop.value)
    assert len(api.posts) == 1
    ledger = load_ledger(m)
    assert ledger.active_entry(first.key)["state"] == SUCCEEDED and ledger.active_entry(second.key) is None


def timeout_rewrite(manifest: Manifest, duration_ms: int):
    """On an evaluation's first terminal read (before the launcher inspects its
    evidence): every run becomes a TIMEOUT that lasted ``duration_ms`` - what a
    trial whose model request never answered looks like in the run record."""

    def rewrite(evaluation_id: str) -> None:
        with closing(sqlite3.connect(str(manifest.db_path()))) as conn:
            conn.execute("UPDATE runs SET status='timeout', duration_ms=? WHERE job_id=?",
                         (duration_ms, evaluation_id))
            conn.execute("UPDATE run_scores SET functional_pass=0 WHERE run_id IN "
                         "(SELECT id FROM runs WHERE job_id=?)", (evaluation_id,))
            conn.commit()

    return rewrite


def test_full_request_timeouts_with_an_unresponsive_backend_need_attention(base, tmp_path, monkeypatch):
    # round 3: the probe asks the MODEL for one token (/api/version and /api/ps can
    # keep answering while generation is stuck); its failure is a DURABLE
    # needs_attention - fixing the backend and relaunching never accepts the cell.
    m = make_campaign(base, tmp_path, [MODEL], [TASK], 2)
    cell = m.cells()[0]
    fake = FakeOllama(m.models).install(monkeypatch)
    fake.probe_error = "POST /api/generate: timed out (simulated)"
    full = m.generation["request_timeout_s"] * 1000
    with hooked_app(m.db_path(), declared_factory(), on_terminal=timeout_rewrite(m, full)) as (_app, api):
        with pytest.raises(CampaignStop, match="needs_attention") as stop:
            run(m, api)
        assert "request timeout" in str(stop.value) and "generation probe" in str(stop.value)
        fake.probe_error = None  # the backend answers again
        with pytest.raises(CampaignStop, match="needs_attention"):
            run(m, api)  # halts until superseded; never re-probed, never accepted
    assert fake.probes == 1 and fake.probed == [MODEL]
    entry = load_ledger(m).active_entry(cell.key)
    assert entry["state"] == "needs_attention"
    assert entry["summary"]["request_timeout_hits"] == 2 and entry["summary"]["timeouts"] == 2
    assert any("failed a generation probe" in w for w in entry["warnings"])
    assert "model_digest_at_finalize" not in entry  # halted before the cell could be accepted
    assert len(api.posts) == 1
    assert validate_mod.validate_campaign(m)["complete"] is False
    supersede_cell(m, cell.key, "Ollama hung; restarted it")  # needs_attention is supersedable


def test_full_request_timeouts_with_a_responsive_backend_are_model_behaviour(base, tmp_path, monkeypatch):
    m = make_campaign(base, tmp_path, [MODEL], [TASK], 2)
    cell = m.cells()[0]
    fake = FakeOllama(m.models).install(monkeypatch)
    # the threshold: >= request_timeout_s*1000 - 2000 ms counts as a full-timeout hit
    at_threshold = m.generation["request_timeout_s"] * 1000 - 2000
    with hooked_app(m.db_path(), declared_factory(), on_terminal=timeout_rewrite(m, at_threshold)) as (_app, api):
        assert run(m, api)["submitted"] == 1
    assert fake.probes == 1 and fake.probed == [MODEL]  # the cell's own model was asked for a token
    entry = load_ledger(m).active_entry(cell.key)
    assert entry["state"] == SUCCEEDED
    assert entry["summary"]["request_timeout_hits"] == 2
    assert len(entry["warnings"]) == 1 and "answered a generation probe" in entry["warnings"][0]
    receipt = validate_mod.validate_campaign(m)
    assert receipt["complete"] is True, receipt["problems"]
    assert receipt["per_model"][MODEL]["passed"] == 0 and receipt["present"]["valid_runs"] == 2


def test_timeouts_shorter_than_the_request_timeout_do_not_probe(base, tmp_path, monkeypatch):
    m = make_campaign(base, tmp_path, [MODEL], [TASK], 1)
    fake = FakeOllama(m.models).install(monkeypatch)
    fake.probe_error = "would halt if probed"
    below = m.generation["request_timeout_s"] * 1000 - 2001
    with hooked_app(m.db_path(), declared_factory(), on_terminal=timeout_rewrite(m, below)) as (_app, api):
        assert run(m, api)["submitted"] == 1
    entry = load_ledger(m).active_entry(m.cells()[0].key)
    assert fake.probes == 0 and entry["state"] == SUCCEEDED and entry["warnings"] == []
    assert entry["summary"]["timeouts"] == 1 and entry["summary"]["request_timeout_hits"] == 0


def test_task_drift_found_when_an_evaluation_fails_stops_the_campaign(base, tmp_path, monkeypatch):
    # contract change 5: a failed/canceled evaluation whose task pins drifted is
    # REJECTED (never resumed) and the launcher says STOP THE CAMPAIGN
    m = make_campaign(base, tmp_path, [MODEL], [TASK], 1)
    cell = m.cells()[0]
    FakeOllama(m.models).install(monkeypatch)
    frozen = launcher.check_task_pins
    per_task_calls = []

    def drift_after_submission(manifest, task_ids=None):
        if task_ids is None:
            return frozen(manifest)
        per_task_calls.append(list(task_ids))
        if len(per_task_calls) == 1:  # the pre-submission check still sees the frozen pack
            return frozen(manifest, task_ids)
        return [f"{TASK}: now 9.9.9 sha256:eeeeeeeeeeee..., frozen {m.task_by_id[TASK]['task_version']}"]

    monkeypatch.setattr(launcher, "check_task_pins", drift_after_submission)
    with running_app(m.db_path(), failing_factory) as (_app, api):
        with pytest.raises(CampaignStop, match="STOP THE CAMPAIGN") as stop:
            run(m, api)
        assert "failed on it" in str(stop.value)
        entry = load_ledger(m).active_entry(cell.key)
        assert entry["state"] == REJECTED and entry["job_status"] == "failed"
        assert any("simulated backend failure" in p for p in entry["problems"])
        assert any("now 9.9.9" in p for p in entry["problems"])
        with pytest.raises(LedgerError):
            resume_cell(m, api, cell.key)  # rejected: never resumed
    assert per_task_calls == [[TASK], [TASK]]
    halt = events(m)[-1]
    assert halt["type"] == "halt" and halt["cell"] == cell.key and "STOP THE CAMPAIGN" in halt["message"]


def test_disown_an_untracked_clone_then_the_launch_proceeds(base, tmp_path, monkeypatch, capsys):
    # contract change 6
    m = make_campaign(base, tmp_path, [MODEL, "gemma2:2b"], [TASK], 1)
    first, second = m.cells()
    FakeOllama(m.models).install(monkeypatch)
    manifest_file = tmp_path / "manifest.json"
    dump(m.data, manifest_file)

    def disown(evaluation_id: str, reason: str | None = None) -> int:
        argv = ["--manifest", str(manifest_file), "disown", "--evaluation", evaluation_id]
        return cli.main(argv + (["--reason", reason] if reason is not None else []))

    with running_app(m.db_path(), declared_factory()) as (_app, api):
        run(m, api, max_evaluations=1)
        owned = load_ledger(m).active_entry(first.key)["evaluation_id"]
        with closing(app_db.connect(m.db_path())) as conn:  # a UI "retry" of the campaign evaluation
            clone = jobs.retry_job(conn, owned).id
        with pytest.raises(CampaignStop, match="the ledger does not own"):
            run(m, api)
        assert len(api.posts) == 1
        capsys.readouterr()
        # refusals: not terminal, owned, unknown, no reason
        assert disown(clone, "UI retry clone") == 3
        assert "cancel it before disowning" in capsys.readouterr().err
        with closing(sqlite3.connect(str(m.db_path()))) as conn:
            conn.execute("UPDATE evaluation_jobs SET status='running' WHERE id=?", (clone,))
            conn.commit()
        assert disown(clone, "UI retry clone") == 3
        assert "running" in capsys.readouterr().err
        with closing(sqlite3.connect(str(m.db_path()))) as conn:
            conn.execute("UPDATE evaluation_jobs SET status='queued' WHERE id=?", (clone,))
            conn.commit()
        with closing(app_db.connect(m.db_path())) as conn:
            assert jobs.request_cancel(conn, clone).status == "canceled"
        assert disown(owned, "I do not like this result") == 3
        assert "owned by a ledger entry" in capsys.readouterr().err
        assert disown("0" * 32, "typo") == 3
        assert "not in the campaign database" in capsys.readouterr().err
        assert disown(clone, "   ") == 3
        assert "reason" in capsys.readouterr().err
        with pytest.raises(SystemExit):
            disown(clone)  # --reason is required by the CLI
        capsys.readouterr()
        assert load_ledger(m).data["disowned"] == []
        # the real thing
        assert disown(clone, "  UI retry clone of the first cell ") == 0
        assert f"disowned {clone}" in capsys.readouterr().out
        assert disown(clone, "again") == 3
        ledger = load_ledger(m)
        assert [(d["evaluation_id"], d["reason"]) for d in ledger.data["disowned"]] == [
            (clone, "UI retry clone of the first cell")]
        assert ledger.data["events"][-1]["type"] == "disowned"
        result = run(m, api)
    assert result["submitted"] == 1 and len(api.posts) == 2
    receipt = validate_mod.validate_campaign(m)
    assert receipt["complete"] is True, receipt["problems"]
    assert receipt["extra"]["disowned_evaluations"] == [clone]
    assert receipt["extra"]["untracked_campaign_evaluations"] == []
    assert "1 disowned" in validate_mod.render(receipt)
    assert clone not in {e.get("evaluation_id") for e in load_ledger(m).entries}


def test_cli_launch_with_a_refused_preflight_creates_no_ledger(base, tmp_path, monkeypatch, capsys):
    # contract change 7, through the operator command
    m = make_campaign(base, tmp_path, [MODEL], [TASK], 1)
    fake = FakeOllama(m.models).install(monkeypatch)
    fake.missing = {MODEL}
    manifest_file = tmp_path / "manifest.json"
    dump(m.data, manifest_file)
    with running_app(m.db_path(), declared_factory()) as (_app, api):
        monkeypatch.setattr(api_mod, "AgentForgeApi", lambda url, **_: api)
        rc = cli.main(["--manifest", str(manifest_file), "launch", "--phase", "A",
                       "--confirm", m.campaign_id, "--no-code-check", "--poll", "0.01"])
    assert rc == 3 and "preflight failed" in capsys.readouterr().err
    assert not m.ledger_path().exists()
    assert api.posts == [] and evaluation_ids(m) == set()


@pytest.mark.parametrize(
    "label, corrupt",
    [
        ("non-dict entry", lambda d: d.update(entries=["garbage"])),
        ("entries not a list", lambda d: d.update(entries={"m|t": {}})),
        ("entry missing keys", lambda d: d.update(entries=[{"cell": f"{MODEL}|{TASK}", "state": "succeeded"}])),
        ("disowned not a list", lambda d: d.update(disowned="x")),
        ("disowned record without reason", lambda d: d.update(disowned=[{"evaluation_id": "e1"}])),
        ("disowned record not an object", lambda d: d.update(disowned=["e1"])),
        ("launches not a list", lambda d: d.update(launches={})),
        ("events not a list", lambda d: d.update(events=None)),
        # round 4 (7d3a444): events, launch records and resume records are checked too
        ("event not an object", lambda d: d["events"].append(["launch"])),
        ("event without a type", lambda d: d["events"][0].pop("type")),
        ("launch without started_at", lambda d: d["launches"][0].pop("started_at")),
        ("launch check_code not a bool", lambda d: d["launches"][0].update(check_code="true")),
        ("resume records not a list", lambda d: d.update(entries=[{
            "cell": f"{MODEL}|{TASK}", "model": MODEL, "task_id": TASK, "phase": "A",
            "evaluation_name": f"campaign:t-launch:A:{MODEL}|{TASK}", "state": "failed",
            "evaluation_id": "e1", "resumes": "accepted"}])),
    ],
)
def test_a_corrupt_ledger_refuses_the_launch_with_a_ledger_error(base, tmp_path, monkeypatch, label, corrupt):
    # contract change 8, launch path
    m = make_campaign(base, tmp_path, [MODEL], [TASK], 1)
    FakeOllama(m.models).install(monkeypatch)
    with running_app(m.db_path(), declared_factory()) as (_app, api):
        run(m, api, max_evaluations=0)
        data = json.loads(m.ledger_path().read_text())
        corrupt(data)
        m.ledger_path().write_text(json.dumps(data))
        before = m.ledger_path().read_text()
        with pytest.raises(LedgerError):
            run(m, api)
    assert api.posts == [] and m.ledger_path().read_text() == before


@pytest.mark.parametrize(
    "label, corrupt",
    [
        ("launch record not an object", lambda d: d["launches"].insert(0, "garbage")),
        ("inventory not an object", lambda d: d["launches"][0].update(inventory=["x"])),
        ("inventory model entry not an object", lambda d: d["launches"][0]["inventory"]["models"].update({MODEL: "x"})),
    ],
)
def test_a_corrupt_launch_record_is_a_ledger_error_not_a_crash(base, tmp_path, monkeypatch, label, corrupt):
    # Was a PRODUCT BUG (fixed in 138c75f): contract change 8 promises
    # LedgerError, never KeyError / AttributeError, for a corrupt ledger; a launch
    # record that is not an object (or whose inventory is malformed) used to crash
    # validate_campaign and Launcher.run with an AttributeError in
    # reference_digests / ollama.digests / the 'interrupted' sweep.
    m = make_campaign(base, tmp_path, [MODEL], [TASK], 1)
    FakeOllama(m.models).install(monkeypatch)
    with running_app(m.db_path(), declared_factory()) as (_app, api):
        run(m, api, max_evaluations=0)
        data = json.loads(m.ledger_path().read_text())
        corrupt(data)
        m.ledger_path().write_text(json.dumps(data))
        receipt = validate_mod.validate_campaign(m)
        assert receipt["complete"] is False and any(p.startswith("ledger:") for p in receipt["problems"])
        with pytest.raises(LedgerError):
            run(m, api)
    assert api.posts == []


def _case_variants(path: Path) -> list[Path]:
    swapped = path.with_name(path.name.swapcase())
    upper_dirs = Path(str(path.parent).upper()) / path.name
    return [swapped, upper_dirs]


def test_same_path_accepts_other_spellings_of_the_same_file(tmp_path):
    # contract change 10: samefile, so a case-insensitive volume's other
    # spellings, symlinks and relative spellings are the same database
    db = tmp_path / "Campaign.sqlite"
    db.write_bytes(b"")
    link = tmp_path / "link.sqlite"
    link.symlink_to(db)
    other = tmp_path / "other.sqlite"
    other.write_bytes(b"")
    assert launcher.same_path(db, db) and launcher.same_path(str(db), db)
    assert launcher.same_path(link, db)
    assert launcher.same_path(tmp_path / "x" / ".." / db.name, db)
    assert not launcher.same_path(other, db)
    assert not launcher.same_path(tmp_path / "absent.sqlite", db)
    assert launcher.same_path(tmp_path / "absent.sqlite", tmp_path / "absent.sqlite")
    variants = _case_variants(db)
    if not all(os.path.exists(v) for v in variants):
        pytest.skip("this volume is case-sensitive")
    for variant in variants:
        assert str(variant) != str(db)
        assert launcher.same_path(variant, db) and launcher.same_path(str(variant), str(db))


def test_preflight_accepts_the_app_reporting_a_differently_cased_db_path(base, tmp_path, monkeypatch):
    m = make_campaign(base, tmp_path, [MODEL], [TASK], 1)
    FakeOllama(m.models).install(monkeypatch)
    variants = [v for v in _case_variants(m.db_path()) if os.path.exists(v)]
    if not variants:
        pytest.skip("this volume is case-sensitive")

    class CasedHealth(StubApp):
        def __init__(self, reported: str) -> None:
            super().__init__([])
            self.reported = reported

        def health(self):
            return {"status": "ok", "db_path": self.reported}

    for variant in variants:
        pf = launcher.preflight(m, CasedHealth(str(variant)), check_code=False)
        assert pf.ok, pf.problems
    other = make_campaign(base, tmp_path, [MODEL], [TASK], 1, name="other")
    pf = launcher.preflight(m, CasedHealth(str(other.db_path()).swapcase()), check_code=False)
    assert any("bound to" in p for p in pf.problems)


# =========================================================================== #
# Contract of 138c75f (review round 2): durable halts, identity watch, all-phase
# drain, API+DB busy checks, runtime-code audit, CLI refusals, awaiting_finalize
# =========================================================================== #


def test_model_absent_at_finalize_is_a_durable_rejection(base, tmp_path, monkeypatch):
    # The model vanished (ollama rm / re-pull) by the time its evaluation finished:
    # REJECTED, and re-pulling the weights then relaunching never accepts it.
    m = make_campaign(base, tmp_path, [MODEL], [TASK], 1)
    cell = m.cells()[0]
    fake = FakeOllama(m.models).install(monkeypatch)
    fake.from_call = {3: {"missing": {MODEL}}}  # 1 preflight, 2 before the submission, 3 at finalize
    with running_app(m.db_path(), declared_factory()) as (_app, api):
        with pytest.raises(CampaignStop, match="model identity not proven") as stop:
            run(m, api)
        assert "absent from Ollama" in str(stop.value) and "supersede" in str(stop.value)
        entry = load_ledger(m).active_entry(cell.key)
        rejected_id = entry["evaluation_id"]
        assert entry["state"] == REJECTED and entry["job_status"] == "succeeded"
        assert entry["model_digest_at_finalize"] is None
        assert entry["model_digest_at_submit"] == fake.digests[MODEL]
        assert any("absent from Ollama" in p for p in entry["problems"])
        fake.from_call = {}  # the model is back, with its original digest
        calls = fake.calls
        with pytest.raises(CampaignStop, match="is rejected"):
            run(m, api)
        assert fake.calls == calls + 1  # only the preflight: the evaluation is never re-judged
        assert load_ledger(m).active_entry(cell.key)["state"] == REJECTED
        receipt = validate_mod.validate_campaign(m)
        assert receipt["complete"] is False and receipt["missing"]["cells"] == [cell.key]
        st = status_mod.campaign_status(m)
        assert st["totals"]["completed_runs"] == 0 and st["totals"]["excluded_runs"] == 1
        assert len(api.posts) == 1
        supersede_cell(m, cell.key, "model was removed during the evaluation; re-pulled the same digest")
        result = run(m, api)
    assert result == {"submitted": 1, "paused": False, "drained": 0, "skipped": 0, "succeeded": 1}
    fresh = load_ledger(m).active_entry(cell.key)
    assert fresh["state"] == SUCCEEDED and fresh["evaluation_id"] != rejected_id
    receipt = validate_mod.validate_campaign(m)
    assert receipt["complete"] is True, receipt["problems"]
    assert receipt["cells"][0]["superseded_evaluations"] == [rejected_id]


def _watch_clock(on_sleep: dict):
    """A fake clock that jumps 31 s per launcher sleep (so every poll after the
    first runs the 30 s identity watch) and runs ``on_sleep[n]`` at the n-th
    sleep. Returns (clock, sleep)."""
    now = [0.0]
    count = [0]
    inner = deadline_sleep()

    def sleep(seconds: float) -> None:
        count[0] += 1
        action = on_sleep.get(count[0])
        if action:
            action()
        now[0] += 31.0
        inner(seconds)

    return (lambda: now[0]), sleep


def test_identity_violation_mid_wait_is_rejected_even_when_restored_before_finalize(base, tmp_path, monkeypatch):
    # An 'ollama pull' re-tags the model WHILE its evaluation runs and the original
    # weights are back before it finishes: the digest at submission and at
    # finalize both equal the reference, so only the 30 s identity watch can see
    # it. The violation is recorded durably and the cell is REJECTED; restoring
    # and relaunching never accepts it; supersede re-evaluates it fresh.
    m = make_campaign(base, tmp_path, [MODEL], [TASK], 1)
    cell = m.cells()[0]
    fake = FakeOllama(m.models).install(monkeypatch)
    reference, moved = fake.digests[MODEL], "sha256:" + "4" * 64
    probe = GatedProbe()  # the evaluation cannot finish before the test opens the gate

    def retag() -> None:
        fake.digests[MODEL] = moved

    def restore_and_finish() -> None:
        fake.digests[MODEL] = reference
        probe.gate.set()

    # wait loop: poll 1 (no watch yet) -> sleep 1 (re-tag) -> poll 2 + watch (sees
    # the moved digest) -> sleep 2 (restore, let the trial finish) -> ... finalize
    clock, sleep = _watch_clock({1: retag, 2: restore_and_finish})
    logs: list[str] = []
    try:
        with running_app(m.db_path(), probe.factory) as (_app, api):
            watched = make_launcher(m, api, logs, identity_poll_s=30.0, clock=clock, sleep=sleep)
            with pytest.raises(CampaignStop, match="model identity not proven") as stop:
                watched.run("A", check_code=True)
            assert "changed while the evaluation ran" in str(stop.value)
            # 1 preflight, 2 before the submission, 3 the watch, 4 finalize (a
            # recorded violation is not re-read)
            assert fake.calls == 4
            entry = load_ledger(m).active_entry(cell.key)
            violated_id = entry["evaluation_id"]
            assert entry["state"] == REJECTED
            assert entry["model_digest_at_submit"] == entry["model_digest_at_finalize"] == reference
            assert (entry["identity_violation"]["observed"], entry["identity_violation"]["expected"]) == (
                moved, reference)
            assert any("IDENTITY VIOLATION" in line for line in logs)
            receipt = validate_mod.validate_campaign(m)
            assert receipt["complete"] is False and receipt["missing"]["cells"] == [cell.key]
            with pytest.raises(CampaignStop, match="is rejected"):
                run(m, api)  # the weights are the reference again: still never accepted
            assert load_ledger(m).active_entry(cell.key)["state"] == REJECTED
            assert len(api.posts) == 1
            supersede_cell(m, cell.key, "model re-tagged mid-evaluation (identity watch)")
            result = run(m, api)
    finally:
        probe.gate.set()
    assert result["submitted"] == 1
    fresh = load_ledger(m).active_entry(cell.key)
    assert fresh["state"] == SUCCEEDED and fresh["evaluation_id"] != violated_id
    assert "identity_violation" not in fresh
    assert validate_mod.validate_campaign(m)["complete"] is True


def test_a_hand_cleared_violation_is_still_rejected_by_the_validator(base, tmp_path, monkeypatch):
    # Adversarial: the evaluation above, but someone flips the rejected entry to
    # 'succeeded' in the ledger (keeping the recorded violation): the shared
    # acceptance predicate still refuses it, in the validator AND the monitor.
    m = make_campaign(base, tmp_path, [MODEL], [TASK], 1)
    cell = m.cells()[0]
    fake = FakeOllama(m.models).install(monkeypatch)
    reference = fake.digests[MODEL]
    with running_app(m.db_path(), declared_factory()) as (_app, api):
        run(m, api)
    ledger = load_ledger(m)
    ledger.update(ledger.active_entry(cell.key),
                  identity_violation={"observed": "sha256:" + "4" * 64, "expected": reference, "at": "x"})
    ledger.save()
    receipt = validate_mod.validate_campaign(m)
    assert receipt["complete"] is False and receipt["missing"]["cells"] == [cell.key]
    assert any("identity violation" in p for p in receipt["problems"])
    st = status_mod.campaign_status(m)
    assert st["cells"]["complete"] == 0 and st["totals"]["completed_runs"] == 0
    assert {r["cell"]: r["state"] for r in st["cells_detail"]}[cell.key] == "succeeded-but-invalid"


def test_an_identity_watch_read_failure_is_only_counted(base, tmp_path, monkeypatch):
    # The documented limitation: Ollama not answering one watch poll is counted on
    # the entry, not treated as a violation; the digest at finalize still decides.
    m = make_campaign(base, tmp_path, [MODEL], [TASK], 1)
    cell = m.cells()[0]
    fake = FakeOllama(m.models).install(monkeypatch)
    fake.from_call = {3: {"unreachable": True}, 4: {"unreachable": False}}  # only the first watch fails
    probe = GatedProbe()
    clock, sleep = _watch_clock({2: probe.gate.set})
    try:
        with running_app(m.db_path(), probe.factory) as (_app, api):
            make_launcher(m, api, identity_poll_s=30.0, clock=clock, sleep=sleep).run("A", check_code=True)
    finally:
        probe.gate.set()
    entry = load_ledger(m).active_entry(cell.key)
    assert entry["state"] == SUCCEEDED and entry["identity_checks_failed"] == 1
    assert "identity_violation" not in entry
    assert entry["model_digest_at_finalize"] == fake.digests[MODEL]
    assert validate_mod.validate_campaign(m)["complete"] is True


def test_ollama_unreachable_at_finalize_is_a_durable_needs_attention(base, tmp_path, monkeypatch):
    m = make_campaign(base, tmp_path, [MODEL], [TASK], 1)
    cell = m.cells()[0]
    fake = FakeOllama(m.models).install(monkeypatch)
    fake.from_call = {3: {"unreachable": True}}  # the identity read at finalize fails
    with running_app(m.db_path(), declared_factory()) as (_app, api):
        with pytest.raises(CampaignStop, match="needs_attention") as stop:
            run(m, api)
        assert "model identity could not be verified" in str(stop.value)
        entry = load_ledger(m).active_entry(cell.key)
        first_id = entry["evaluation_id"]
        assert entry["state"] == "needs_attention" and "model_digest_at_finalize" not in entry
        fake.from_call = {}  # Ollama answers again (same digest)
        calls = fake.calls
        with pytest.raises(CampaignStop, match="needs_attention"):
            run(m, api)
        assert fake.calls == calls + 1  # never re-finalized: identity unproven stays unproven
        assert load_ledger(m).active_entry(cell.key)["state"] == "needs_attention"
        assert validate_mod.validate_campaign(m)["complete"] is False
        with pytest.raises(LedgerError):
            resume_cell(m, api, cell.key)  # not failed/canceled: never resumed
        supersede_cell(m, cell.key, "Ollama was down when the evaluation finished")
        assert run(m, api)["submitted"] == 1
    fresh = load_ledger(m).active_entry(cell.key)
    assert fresh["state"] == SUCCEEDED and fresh["evaluation_id"] != first_id
    assert validate_mod.validate_campaign(m)["complete"] is True


def test_the_generation_probe_asks_the_model_for_one_token(monkeypatch):
    # ollama.probe(base, model): /api/version and /api/ps can keep answering while
    # generation is stuck, so the probe must also generate - and its failure must
    # propagate (a server that only answers metadata is not healthy).
    calls: list[tuple] = []
    failing = {"path": None}

    def fake_call(base_url, method, path, body=None, timeout=30.0):
        calls.append((method, path, body, timeout))
        if path == failing["path"]:
            raise ollama.OllamaError(f"{method} {path}: timed out (simulated)")
        return {}

    monkeypatch.setattr(ollama, "_call", fake_call)
    ollama.probe("http://ollama", MODEL)
    assert [(c[0], c[1]) for c in calls] == [("GET", "/api/version"), ("GET", "/api/ps"), ("POST", "/api/generate")]
    body = calls[2][2]
    assert body["model"] == MODEL and body["stream"] is False and body["options"] == {"num_predict": 1}
    assert body["prompt"]  # a real prompt: an empty one only loads the model, it never samples
    calls.clear()
    ollama.probe("http://ollama")  # no model: server liveness only
    assert [c[1] for c in calls] == ["/api/version", "/api/ps"]
    failing["path"] = "/api/generate"
    with pytest.raises(ollama.OllamaError, match="generate"):
        ollama.probe("http://ollama", MODEL)


class CappedApi(ApiAdapter):
    """The app's evaluation list is capped (newest 200): ``hidden`` ids are in the
    database but never listed by the API."""

    def __init__(self, client: TestClient) -> None:
        super().__init__(client)
        self.hidden: set[str] = set()

    def list_jobs(self) -> list[dict]:
        return [j for j in super().list_jobs() if j["id"] not in self.hidden]


@pytest.mark.parametrize("db_status", ["queued", "running"])
def test_an_evaluation_only_the_database_shows_blocks_the_submission(base, tmp_path, monkeypatch, db_status):
    m = make_campaign(base, tmp_path, [MODEL], [TASK], 1)
    FakeOllama(m.models).install(monkeypatch)
    app = create_app()
    app.state.db_path = m.db_path()
    app.state.agent_factory = declared_factory()
    with TestClient(app) as client:
        api = CappedApi(client)
        foreign = create_directly(m, {"model": MODEL, "tasks": [TASK], "repeats": 1})  # a UI run, never dispatched
        with closing(sqlite3.connect(str(m.db_path()))) as conn:
            conn.execute("UPDATE evaluation_jobs SET status=? WHERE id=?", (db_status, foreign))
            conn.commit()
        api.hidden.add(foreign)
        assert all(j["id"] != foreign for j in api.list_jobs())  # the API does not report it
        with pytest.raises(CampaignStop, match="queued/running on the app") as stop:
            run(m, api)
    assert foreign in str(stop.value)
    assert api.posts == [] and evaluation_ids(m) == {foreign}
    assert load_ledger(m).entries == []  # halted before writing the cell's entry


def test_an_evaluation_only_the_database_shows_blocks_the_resume(base, tmp_path, monkeypatch):
    m = make_campaign(base, tmp_path, [MODEL], [TASK], 1)
    fake = FakeOllama(m.models).install(monkeypatch)
    key = seed_failed_cell(m, fake)
    foreign = create_directly(m, {"model": MODEL, "tasks": [TASK], "repeats": 1})  # queued, in the DB only
    idle_api = StubApp([])  # the API lists nothing queued/running
    with pytest.raises(CampaignStop, match="resume only on an idle app") as stop:
        resume_cell(m, idle_api, key)
    assert foreign in str(stop.value)
    assert not any(isinstance(c, tuple) for c in idle_api.calls) and fake.warmed == []
    assert load_ledger(m).active_entry(key)["state"] == FAILED
    with closing(app_db.connect(m.db_path())) as conn:
        assert jobs.request_cancel(conn, foreign).status == "canceled"
    assert resume_cell(m, idle_api, key)["state"] == SUBMITTED  # idle now: resumed
    assert ("resume", "e-original") in idle_api.calls


@pytest.mark.parametrize("in_flight", [SUBMITTED, SUBMITTING])
def test_resume_is_refused_while_any_campaign_evaluation_is_in_flight(base, tmp_path, monkeypatch, code_check,
                                                                      in_flight):
    m = make_campaign(base, tmp_path, [MODEL, "gemma2:2b"], [TASK], 1)
    fake = FakeOllama(m.models).install(monkeypatch)
    key = seed_failed_cell(m, fake)
    other = m.cells()[1]
    ledger = load_ledger(m)
    entry = ledger.new_entry(key=other.key, model=other.model, task_id=other.task_id, phase=other.phase,
                             evaluation_name=m.evaluation_name(other), positions=[0])
    ledger.update(entry, state=in_flight, evaluation_id="e-live" if in_flight == SUBMITTED else None)
    ledger.save()
    stub = StubApp([])
    with pytest.raises(CampaignStop, match="still in flight") as stop:
        resume_cell(m, stub, key)
    assert other.key in str(stop.value)
    assert stub.calls == [] and fake.warmed == [] and code_check == []  # refused before anything else
    assert load_ledger(m).active_entry(key)["state"] == FAILED


def test_resume_runs_the_code_check_and_records_it(base, tmp_path, monkeypatch):
    m = make_campaign(base, tmp_path, [MODEL], [TASK], 1)
    fake = FakeOllama(m.models).install(monkeypatch)
    key = seed_failed_cell(m, fake)
    monkeypatch.setattr(launcher, "check_runtime_code",
                        lambda manifest: (["runtime paths differ from the pinned release (simulated)"], {"head": "x"}))
    stub = StubApp([])
    with pytest.raises(CampaignStop, match="runtime code check failed"):
        resume_cell(m, stub, key)
    assert stub.calls == [] and fake.warmed == []
    assert load_ledger(m).active_entry(key)["state"] == FAILED
    # --no-code-check (rehearsals): allowed, but recorded as such
    assert resume_cell(m, stub, key, check_code=False)["state"] == SUBMITTED
    resumed = [e for e in events(m) if e["type"] == "resumed"]
    assert len(resumed) == 1 and resumed[0]["check_code"] is False


def test_the_evidence_hash_is_rechecked_before_every_submission(base, tmp_path, monkeypatch):
    # The historical evidence DB is only READ here: its hash as seen by the
    # launcher is simulated to change after the first submission.
    m = make_campaign(base, tmp_path, [MODEL, "gemma2:2b"], [TASK], 1)
    first, second = m.cells()
    FakeOllama(m.models).install(monkeypatch)
    # round 4: the launcher's guard hash is manifest.evidence_sha256 (the main file,
    # plus any uncheckpointed WAL), imported into the launcher module
    assert not hasattr(launcher, "file_sha256")
    real = launcher.evidence_sha256
    evidence = paths.resolve(m.data["historical_evidence"]["path"])
    seen = {"evidence": 0}

    def hashed(path):
        if launcher.same_path(path, evidence):
            seen["evidence"] += 1
            if seen["evidence"] >= 3:  # 1 preflight, 2 before cell 1, 3 before cell 2
                return "0" * 64
        return real(path)

    monkeypatch.setattr(launcher, "evidence_sha256", hashed)
    with running_app(m.db_path(), declared_factory()) as (_app, api):
        with pytest.raises(CampaignStop, match="historical evidence DB hash changed"):
            run(m, api)
    assert len(api.posts) == 1 and api.posts[0]["name"] == m.evaluation_name(first)
    ledger = load_ledger(m)
    assert ledger.active_entry(first.key)["state"] == SUCCEEDED and ledger.active_entry(second.key) is None
    assert ledger.data["launches"][-1]["outcome"] == "halted"
    assert real(evidence) == HISTORICAL_SHA256  # the real file never changed


def test_a_no_code_check_launch_makes_its_cells_non_official_for_good(base, tmp_path, monkeypatch, capsys):
    # --no-code-check is recorded in the launch AND on every entry it submits. Round 5:
    # the launcher applies the validator's predicate before marking a cell succeeded,
    # so the first such cell lands REJECTED and the rehearsal halts; an official
    # launch cannot launder it (it halts on the rejected cell) - only a supersede
    # followed by a fresh, code-checked re-evaluation completes the campaign.
    from afa_campaign import analysis

    m = make_campaign(base, tmp_path, [MODEL], [TASK, "grid-paths"], 1)
    first, second = m.cells()
    FakeOllama(m.models).install(monkeypatch)
    manifest_file = tmp_path / "manifest.json"
    dump(m.data, manifest_file)
    with running_app(m.db_path(), declared_factory()) as (_app, api):
        monkeypatch.setattr(api_mod, "AgentForgeApi", lambda url, **_: api)
        rc = cli.main(["--manifest", str(manifest_file), "launch", "--phase", "A", "--confirm", m.campaign_id,
                       "--no-code-check", "--poll", "0.01"])
        assert rc == 3
        assert "not official campaign evidence" in capsys.readouterr().err
        ledger = load_ledger(m)
        entry = ledger.active_entry(first.key)
        assert entry["state"] == REJECTED and ledger.active_entry(second.key) is None
        assert entry["code_check_at_submit"] is False and entry["code_check_at_finalize"] is False
        assert any("a passing runtime-code check" in p for p in entry["problems"])
        receipt = validate_mod.validate_campaign(m)
        assert receipt["complete"] is False and receipt["present"]["cells_complete"] == 0
        assert receipt["per_model"][MODEL]["runs"] == 0  # only accepted evidence is counted
        assert [w for w in receipt["warnings"] if "runtime-code check False" in w]
        st = status_mod.campaign_status(m)
        assert st["cells"]["complete"] == 0 and st["totals"]["excluded_runs"] == 1
        assert analysis.official_baseline(m) is None
        with pytest.raises(CampaignStop, match="is rejected"):
            run(m, api)  # an official launch halts on the rejected cell; it never launders it
        launcher.supersede_cell(m, first.key, "submitted by a --no-code-check rehearsal launch")
        assert run(m, api)["submitted"] == 2  # fresh, code-checked re-evaluation + the second cell
    ledger = load_ledger(m)
    assert [l["check_code"] for l in ledger.data["launches"]] == [False, True, True]
    receipt = validate_mod.validate_campaign(m)
    assert receipt["complete"] is True, receipt["problems"]
    row = next(r for r in receipt["cells"] if r["cell"] == first.key)
    assert row["superseded_evaluations"] == [entry["evaluation_id"]]
    assert [w for w in receipt["warnings"] if "runtime-code check False" in w]  # still disclosed
    assert analysis.official_baseline(m) is not None
    assert cli.main(["--manifest", str(manifest_file), "validate", "--receipt", str(tmp_path / "r.json")]) == 0


def test_a_rehearsal_launch_that_touched_no_cell_leaves_the_campaign_complete(base, tmp_path, monkeypatch):
    # round 4: the audit is tied to evidence. A --no-code-check / --no-warmup launch
    # that submitted, resumed and finalized nothing is disclosed (a warning); the
    # campaign completed by official launches is COMPLETE and has an OFFICIAL baseline.
    from afa_campaign import analysis

    m = make_campaign(base, tmp_path, [MODEL], [TASK], 1)
    FakeOllama(m.models).install(monkeypatch)
    with running_app(m.db_path(), declared_factory()) as (_app, api):
        rehearsal = make_launcher(m, api, warmup=False).run("A", check_code=False, max_evaluations=0)
        assert rehearsal["submitted"] == 0
        assert run(m, api)["submitted"] == 1
    launches = load_ledger(m).data["launches"]
    assert [(l["check_code"], l["warmup"]) for l in launches] == [(False, False), (True, True)]
    receipt = validate_mod.validate_campaign(m)
    assert receipt["complete"] is True and receipt["problems"] == [], receipt["problems"]
    assert len(receipt["warnings"]) == 1 and launches[0]["started_at"] in receipt["warnings"][0]
    assert "runtime-code check False and warm-up False" in receipt["warnings"][0]
    assert analysis.official_baseline(m)["official"] is True


def test_a_no_warmup_launch_makes_the_cells_it_submits_non_official(base, tmp_path, monkeypatch):
    # round 4: --no-warmup is recorded on every entry it submits (warmed_up_at_submit
    # False): a cold load may have been charged to a trial's time budget. Round 5: the
    # cell lands REJECTED when it finishes (supersedable), never succeeded-but-invalid.
    m = make_campaign(base, tmp_path, [MODEL], [TASK, "grid-paths"], 1)
    first, second = m.cells()
    fake = FakeOllama(m.models).install(monkeypatch)
    with running_app(m.db_path(), declared_factory()) as (_app, api):
        with pytest.raises(CampaignStop, match="not official campaign evidence"):
            make_launcher(m, api, warmup=False).run("A", check_code=True)
        assert fake.warmed == []
        entry = load_ledger(m).active_entry(first.key)
        assert entry["state"] == REJECTED and entry["warmed_up_at_submit"] is False
        assert entry["problems"] == [
            "the model was not loaded before every start of this evaluation (--no-warmup): a cold load "
            "may have been charged to a trial's time budget; not official evidence"]
        assert load_ledger(m).active_entry(second.key) is None  # the rehearsal halted on the first cell
        st = status_mod.campaign_status(m)
        assert {r["cell"]: r["state"] for r in st["cells_detail"]}[first.key] == REJECTED
        launcher.supersede_cell(m, first.key, "submitted by a --no-warmup rehearsal launch")
        assert run(m, api)["submitted"] == 2  # official, warmed launches of both cells
    assert fake.warmed == [MODEL, MODEL]
    ledger = load_ledger(m)
    assert all(ledger.active_entry(c.key)["warmed_up_at_submit"] is True for c in m.cells())
    receipt = validate_mod.validate_campaign(m)
    assert receipt["complete"] is True, receipt["problems"]
    assert any("warm-up False" in w for w in receipt["warnings"])


def test_a_no_code_check_launch_that_only_finalizes_a_cell_makes_it_non_official(base, tmp_path, monkeypatch):
    # round 4: an official submission finalized (drained) by a --no-code-check launch
    # is not official either: code_check_at_finalize records the finalizing launch.
    # Round 5: it lands REJECTED (supersedable) and the rehearsal launch halts.
    m = make_campaign(base, tmp_path, [MODEL], [TASK], 1)
    cell = m.cells()[0]
    FakeOllama(m.models).install(monkeypatch)
    probe = GatedProbe()

    def die(_seconds: float) -> None:
        raise Killed()

    try:
        with running_app(m.db_path(), probe.factory) as (_app, api):
            with pytest.raises(Killed):
                make_launcher(m, api, sleep=die).run("A", check_code=True)  # official submission
            probe.gate.set()
            with pytest.raises(CampaignStop, match="not official campaign evidence"):
                make_launcher(m, api).run("A", check_code=False)  # a rehearsal launch drains it
    finally:
        probe.gate.set()
    entry = load_ledger(m).active_entry(cell.key)
    assert entry["state"] == REJECTED
    assert (entry["code_check_at_submit"], entry["code_check_at_finalize"]) == (True, False)
    first_launch, second_launch = load_ledger(m).data["launches"]
    assert (first_launch["check_code"], second_launch["check_code"]) == (True, False)
    assert entry["submitted_by_launch"] == first_launch["started_at"]
    assert entry["finalized_by_launch"] == second_launch["started_at"]
    assert any("a passing runtime-code check" in p for p in entry["problems"])
    receipt = validate_mod.validate_campaign(m)
    assert receipt["complete"] is False and receipt["missing"]["cells"] == [cell.key]


def test_a_resume_without_the_code_check_makes_the_cell_non_official(base, tmp_path, monkeypatch):
    # round 4: the resume record on the ENTRY says check_code False; the official
    # launch that finalizes the resumed evaluation cannot launder it (round 5: it
    # lands REJECTED and the launch halts)
    m = make_campaign(base, tmp_path, [MODEL], [TASK], 1)
    cell = m.cells()[0]
    FakeOllama(m.models).install(monkeypatch)
    with running_app(m.db_path(), failing_factory) as (app, api):
        with pytest.raises(CampaignStop, match="is failed"):
            run(m, api)
        app.state.agent_factory = declared_factory()
        resume_cell(m, api, cell.key, check_code=False)
        with pytest.raises(CampaignStop, match="not official campaign evidence"):
            run(m, api)  # an official launch finalizes the resumed evaluation
    entry = load_ledger(m).active_entry(cell.key)
    assert entry["state"] == REJECTED
    assert [(r["check_code"], r["warmed_up"], r["outcome"]) for r in entry["resumes"]] == [(False, True, "accepted")]
    assert entry["problems"] == ["submitted or resumed without a passing runtime-code check (--no-code-check or an "
                                 "older launcher): not official evidence"]
    assert all(l["check_code"] is True for l in load_ledger(m).data["launches"])
    receipt = validate_mod.validate_campaign(m)
    assert receipt["present"]["cells_complete"] == 0 and receipt["complete"] is False
    assert status_mod.campaign_status(m)["cells"]["complete"] == 0


def test_cli_launch_refusals_exit_3(base, tmp_path, monkeypatch, capsys):
    # an operator-facing refusal is a message and exit 3 - never a traceback. (The
    # --confirm guard is a usage guard: exit 2, see
    # test_cli_launch_requires_confirming_the_exact_campaign_id.)
    m = make_campaign(base, tmp_path, [MODEL], [TASK], 1)
    FakeOllama(m.models).install(monkeypatch)
    manifest_file = tmp_path / "manifest.json"
    dump(m.data, manifest_file)
    with running_app(m.db_path(), declared_factory()) as (_app, api):
        monkeypatch.setattr(api_mod, "AgentForgeApi", lambda url, **_: api)
        run(m, api, max_evaluations=0)  # the ledger now freezes the manifest hash
        edited = tmp_path / "edited.json"
        dump(dict(m.data, generation={**m.data["generation"], "temperature": 0.2}), edited)
        argv = ["launch", "--phase", "A", "--confirm", m.campaign_id, "--poll", "0.01"]
        assert cli.main(["--manifest", str(edited), *argv]) == 3
        err = capsys.readouterr().err
        assert err.startswith("refused:") and "manifest changed" in err
        # resume / supersede of a cell that is not halted: refused
        key = m.cells()[0].key
        assert cli.main(["--manifest", str(manifest_file), "resume", "--cell", key]) == 3
        assert cli.main(["--manifest", str(manifest_file), "supersede", "--cell", key, "--reason", "x"]) == 3
        assert capsys.readouterr().err.count("refused:") == 2
        # a manifest file that does not exist
        assert cli.main(["--manifest", str(tmp_path / "missing.json"), *argv]) == 3
        assert "refused:" in capsys.readouterr().err
    assert api.posts == [] and evaluation_ids(m) == set()
    assert len(load_ledger(m).data["launches"]) == 1


def test_cli_preflight_reports_an_unloadable_ledger_as_a_problem(base, tmp_path, monkeypatch, capsys):
    m = make_campaign(base, tmp_path, [MODEL], [TASK], 1)
    FakeOllama(m.models).install(monkeypatch)
    manifest_file = tmp_path / "manifest.json"
    dump(m.data, manifest_file)
    with running_app(m.db_path(), declared_factory()) as (_app, api):
        monkeypatch.setattr(api_mod, "AgentForgeApi", lambda url, **_: api)
        assert cli.main(["--manifest", str(manifest_file), "preflight"]) == 0  # no ledger yet: fine
        assert "preflight OK" in capsys.readouterr().out
        run(m, api, max_evaluations=0)
        data = json.loads(m.ledger_path().read_text())
        data["launches"][0]["inventory"] = ["not", "an", "inventory"]
        m.ledger_path().write_text(json.dumps(data))
        assert cli.main(["--manifest", str(manifest_file), "preflight", "--json"]) == 1
        out = json.loads(capsys.readouterr().out)
        assert out["ok"] is False and out["problems"][0].startswith("ledger:")
        assert "malformed inventory" in out["problems"][0]


def test_status_shows_awaiting_finalize_until_a_launcher_accepts_it(base, tmp_path, monkeypatch):
    # A launcher dies while waiting; the evaluation then finishes. Until a launch
    # judges it, the monitor shows 'awaiting_finalize' (in progress, never
    # completed, not running); the validator agrees it is not complete.
    m = make_campaign(base, tmp_path, [MODEL], [TASK], 1)
    cell = m.cells()[0]
    FakeOllama(m.models).install(monkeypatch)
    probe = GatedProbe()

    def die(_seconds: float) -> None:
        raise Killed()

    try:
        with running_app(m.db_path(), probe.factory) as (_app, api):
            with pytest.raises(Killed):
                make_launcher(m, api, sleep=die).run("A", check_code=True)
            evaluation_id = load_ledger(m).active_entry(cell.key)["evaluation_id"]
            st = status_mod.campaign_status(m)
            assert [r["cell"] for r in st["evaluations_running"]] == [cell.key]
            probe.gate.set()
            end = time.monotonic() + 60
            while api.get_job(evaluation_id)["status"] not in launcher.TERMINAL:
                assert time.monotonic() < end, "the evaluation never finished"
                time.sleep(0.02)
            st = status_mod.campaign_status(m)
            assert {r["cell"]: r["state"] for r in st["cells_detail"]} == {cell.key: "awaiting_finalize"}
            assert st["evaluations_running"] == []
            assert [(h["cell"], h["state"]) for h in st["evaluations_halted"]] == [(cell.key, "awaiting_finalize")]
            assert st["totals"]["completed_runs"] == 0 and st["totals"]["in_progress_runs"] == 1
            assert st["cells"]["complete"] == 0 and st["failed_states"] == []
            assert "is awaiting_finalize" in status_mod.render(st)
            assert validate_mod.validate_campaign(m)["complete"] is False
            result = run(m, api)
    finally:
        probe.gate.set()
    assert result == {"submitted": 0, "paused": False, "drained": 1, "skipped": 1, "succeeded": 0}
    st = status_mod.campaign_status(m)
    assert st["cells"]["complete"] == 1 and st["evaluations_halted"] == []
    assert st["totals"]["completed_runs"] == 1 and st["totals"]["in_progress_runs"] == 0
    assert validate_mod.validate_campaign(m)["complete"] is True


# =========================================================================== #
# Contract of 7d3a444 (review round 3): resume window, server version,
# concurrency, evidence-tied audits, drain reconciliation, identity retries
# =========================================================================== #


def wait_terminal(api: ApiAdapter, evaluation_id: str, limit_s: float = 60.0) -> dict:
    end = time.monotonic() + limit_s
    while True:
        job = api.get_job(evaluation_id)
        if job["status"] in launcher.TERMINAL:
            return job
        assert time.monotonic() < end, f"{evaluation_id} never finished"
        time.sleep(0.02)


def wait_status(api: ApiAdapter, evaluation_id: str, statuses: tuple[str, ...], limit_s: float = 60.0) -> str:
    end = time.monotonic() + limit_s
    while True:
        status = api.get_job(evaluation_id)["status"]
        if status in statuses:
            return status
        assert time.monotonic() < end, f"{evaluation_id} never reached {statuses} (is {status})"
        time.sleep(0.02)


LOST_RESPONSES = {
    "connection reset": lambda: ApiUnreachable("POST /jobs/x/resume: connection reset by peer (simulated)"),
    "HTTP 502": lambda: ApiError("POST /jobs/x/resume -> HTTP 502: None", status=502, body=None),
    "HTTP 503": lambda: ApiError("POST /jobs/x/resume -> HTTP 503: None", status=503, body=None),
    "non-JSON answer": lambda: ApiError("POST /jobs/x/resume: non-JSON response"),  # status None
}


@pytest.mark.parametrize("app_resumed", [True, False], ids=["app-resumed-it", "app-never-resumed-it"])
@pytest.mark.parametrize("lost", sorted(LOST_RESPONSES))
def test_a_lost_resume_answer_is_reconciled_by_the_next_launch(base, tmp_path, monkeypatch, lost, app_resumed):
    # round 4: the entry is marked in flight (state submitted + a 'requested'
    # resume record) BEFORE POST /resume. A transport failure or a non-4xx error
    # leaves the outcome UNKNOWN: the entry stays submitted (a resume is refused
    # meanwhile), and the next launch waits for the evaluation if the app resumed
    # it (accepted as official evidence) or halts on it again if not.
    m = make_campaign(base, tmp_path, [MODEL], [TASK], 1)
    cell = m.cells()[0]
    fake = FakeOllama(m.models).install(monkeypatch)
    with running_app(m.db_path(), failing_factory) as (app, api):
        with pytest.raises(CampaignStop, match="is failed"):
            run(m, api)
        evaluation_id = load_ledger(m).active_entry(cell.key)["evaluation_id"]
        app.state.agent_factory = declared_factory()  # the backend is fixed
        real_resume = api.resume

        def lost_answer(eid: str) -> dict:
            assert load_ledger(m).active_entry(cell.key)["state"] == SUBMITTED  # saved BEFORE the POST
            if app_resumed:
                real_resume(eid)
            raise LOST_RESPONSES[lost]()

        api.resume = lost_answer
        with pytest.raises(CampaignStop, match="is unknown") as stop:
            resume_cell(m, api, cell.key)
        assert "run launch" in str(stop.value)
        entry = load_ledger(m).active_entry(cell.key)
        assert (entry["state"], entry["evaluation_id"], entry["problems"]) == (SUBMITTED, evaluation_id, [])
        assert [(r["outcome"], r["from_state"], r["check_code"], r["warmed_up"]) for r in entry["resumes"]] == [
            ("unknown", FAILED, True, True)]
        kinds = [e["type"] for e in events(m)]
        assert "resume_requested" in kinds and "resumed" not in kinds and "resume_refused" not in kinds
        assert fake.warmed == [MODEL, MODEL]  # the submission and the resume
        with pytest.raises(LedgerError, match="is submitted"):
            resume_cell(m, api, cell.key)  # never a second resume while the outcome is unknown
        del api.resume  # the real client again
        if app_resumed:
            wait_terminal(api, evaluation_id)
            assert status_mod.campaign_status(m)["cells_detail"][0]["state"] == "awaiting_finalize"
            result = run(m, api)
            assert result == {"submitted": 0, "paused": False, "drained": 1, "skipped": 1, "succeeded": 0}
        else:
            with pytest.raises(CampaignStop, match="is failed") as again:
                run(m, api)  # the app never resumed it: the evaluation is still failed
            assert "resume it under the same id" in str(again.value)
            entry = load_ledger(m).active_entry(cell.key)
            # round 5: the drain settled the unknown outcome from the app's resume events
            assert entry["state"] == FAILED and entry["resumes"][0]["outcome"] == "not_executed"
            assert validate_mod.validate_campaign(m)["complete"] is False
            resume_cell(m, api, cell.key)  # an operator resumes it again, answered this time
            assert run(m, api)["drained"] == 1
    entry = load_ledger(m).active_entry(cell.key)
    assert entry["state"] == SUCCEEDED and entry["evaluation_id"] == evaluation_id
    outcomes = [r["outcome"] for r in entry["resumes"]]
    assert outcomes == (["executed"] if app_resumed else ["not_executed", "accepted"])
    assert any(e["type"] == "resume_outcome_settled" for e in events(m))
    assert len(api.posts) == 1 and evaluation_ids(m) == {evaluation_id}
    receipt = validate_mod.validate_campaign(m)
    assert receipt["complete"] is True, receipt["problems"]
    assert status_mod.campaign_status(m)["cells"]["complete"] == 1


@pytest.mark.parametrize("app_resumed", [True, False], ids=["app-resumed-it", "app-never-resumed-it"])
def test_a_resume_command_killed_mid_request_is_reconciled_by_the_next_launch(base, tmp_path, monkeypatch,
                                                                              app_resumed):
    # round 4: the process dies (SIGKILL) during POST /resume - after the in-flight
    # marking was saved. The record stays 'requested'; the next launch reconciles.
    m = make_campaign(base, tmp_path, [MODEL], [TASK], 1)
    cell = m.cells()[0]
    FakeOllama(m.models).install(monkeypatch)
    with running_app(m.db_path(), failing_factory) as (app, api):
        with pytest.raises(CampaignStop, match="is failed"):
            run(m, api)
        app.state.agent_factory = declared_factory()
        real_resume = api.resume

        def killed(eid: str) -> dict:
            if app_resumed:
                real_resume(eid)
            raise Killed()

        api.resume = killed
        with pytest.raises(Killed):
            resume_cell(m, api, cell.key)
        del api.resume
        entry = load_ledger(m).active_entry(cell.key)
        assert entry["state"] == SUBMITTED and [r["outcome"] for r in entry["resumes"]] == ["requested"]
        if app_resumed:
            assert run(m, api)["drained"] == 1
            assert load_ledger(m).active_entry(cell.key)["state"] == SUCCEEDED
            assert validate_mod.validate_campaign(m)["complete"] is True
        else:
            with pytest.raises(CampaignStop, match="is failed"):
                run(m, api)
            assert load_ledger(m).active_entry(cell.key)["state"] == FAILED
            assert validate_mod.validate_campaign(m)["complete"] is False


@pytest.mark.parametrize("status", [400, 404, 409, 422])
def test_a_refused_resume_reverts_the_entry(base, tmp_path, monkeypatch, status):
    # round 4: a 4xx answer means the app did NOT resume: the in-flight marking is
    # reverted, the record says 'refused' (it never counts), a resume_refused event
    # is written, and the cell can be resumed again
    m = make_campaign(base, tmp_path, [MODEL], [TASK], 1)
    fake = FakeOllama(m.models).install(monkeypatch)
    key = seed_failed_cell(m, fake)
    stub = StubApp(resume_error=ApiError(f"HTTP {status}", status=status, body={"error": "no"}))
    with pytest.raises(CampaignStop, match="refused to resume"):
        resume_cell(m, stub, key)
    entry = load_ledger(m).active_entry(key)
    assert (entry["state"], entry["evaluation_id"]) == (FAILED, "e-original")
    assert [(r["outcome"], r["from_state"]) for r in entry["resumes"]] == [("refused", FAILED)]
    refused = [e for e in events(m) if e["type"] == "resume_refused"]
    assert len(refused) == 1 and refused[0]["status"] == status and refused[0]["evaluation_id"] == "e-original"
    assert not any(e["type"] == "resumed" for e in events(m))
    # resumable again; the refused record never counts against the evidence
    resumed = resume_cell(m, StubApp(), key)
    assert resumed["state"] == SUBMITTED
    assert [r["outcome"] for r in resumed["resumes"]] == ["refused", "accepted"]


def test_a_refused_resume_keeps_the_failure_reason(base, tmp_path, monkeypatch):
    m = make_campaign(base, tmp_path, [MODEL], [TASK], 1)
    cell = m.cells()[0]
    FakeOllama(m.models).install(monkeypatch)
    with running_app(m.db_path(), failing_factory) as (_app, api):
        with pytest.raises(CampaignStop, match="is failed"):
            run(m, api)
        before = load_ledger(m).active_entry(cell.key)["problems"]
        assert any("simulated backend failure" in p for p in before)
        def refuse(_evaluation_id: str) -> dict:
            raise ApiError("HTTP 409", status=409, body={"error": "not resumable now"})

        api.resume = refuse
        with pytest.raises(CampaignStop, match="refused to resume"):
            resume_cell(m, api, cell.key)
        del api.resume
        assert load_ledger(m).active_entry(cell.key)["state"] == FAILED
        assert load_ledger(m).active_entry(cell.key)["problems"] == before


@pytest.mark.parametrize("when", ["finished before the launch", "still running when the launch starts"])
def test_a_resume_outside_the_tooling_is_detected_waited_for_and_rejected(base, tmp_path, monkeypatch, when):
    # round 4: the API's /resume (or the UI) bypasses the code, identity and busy
    # checks and the warm-up. The next launch sees the database say queued /
    # running / succeeded while the ledger says failed: it records
    # external_resume_detected, waits for the evaluation, and REJECTS the cell
    # durably whatever its result.
    m = make_campaign(base, tmp_path, [MODEL], [TASK], 1)
    cell = m.cells()[0]
    FakeOllama(m.models).install(monkeypatch)
    probe = GatedProbe()
    inner = deadline_sleep()

    def release(seconds: float) -> None:
        probe.gate.set()
        inner(seconds)

    try:
        with running_app(m.db_path(), failing_factory) as (app, api):
            with pytest.raises(CampaignStop, match="is failed"):
                run(m, api)
            evaluation_id = load_ledger(m).active_entry(cell.key)["evaluation_id"]
            if when == "finished before the launch":
                app.state.agent_factory = declared_factory()
                assert api.resume(evaluation_id)["id"] == evaluation_id  # outside the tooling
                assert wait_terminal(api, evaluation_id)["status"] == "succeeded"
                expected_db_status = ("succeeded",)
                # round 5: the tooling's resume detects it BEFORE any POST (the database
                # says succeeded while the ledger says failed) and rejects the cell
                with pytest.raises(CampaignStop, match="resumed outside the campaign tooling"):
                    resume_cell(m, api, cell.key)
                refused = load_ledger(m).active_entry(cell.key)
                assert refused["state"] == REJECTED and not refused.get("resumes")
            else:
                app.state.agent_factory = probe.factory
                assert api.resume(evaluation_id)["id"] == evaluation_id
                wait_status(api, evaluation_id, ("running",))
                expected_db_status = ("queued", "running")
            logs: list[str] = []
            with pytest.raises(CampaignStop, match="is rejected") as stop:
                make_launcher(m, api, logs, sleep=release).run("A", check_code=True)
            assert "resumed outside the campaign tooling" in str(stop.value) and "supersede" in str(stop.value)
            entry = load_ledger(m).active_entry(cell.key)
            assert (entry["state"], entry["job_status"], entry["evaluation_id"]) == (
                REJECTED, "succeeded", evaluation_id)
            detected = [e for e in events(m) if e["type"] == "external_resume_detected"]
            assert len(detected) == 1
            assert any(f"the database {status}" in detected[0]["detail"] for status in expected_db_status)
            assert events(m)[-1]["type"] == "halt"
            if when == "still running when the launch starts":
                assert detected[0]["ledger_state"] == FAILED
                assert any("resumed outside the campaign tooling" in line for line in logs)
            # never (successfully) resumed through the tooling
            assert all(r["outcome"] == "refused" for r in entry.get("resumes", []))
            # never accepted: validator, monitor, analysis
            receipt = validate_mod.validate_campaign(m)
            assert receipt["complete"] is False and receipt["missing"]["cells"] == [cell.key]
            st = status_mod.campaign_status(m)
            assert st["cells"]["complete"] == 0 and st["totals"]["excluded_runs"] == 1
            from afa_campaign import analysis
            assert analysis.official_baseline(m) is None
            # durable: a relaunch halts on it without re-judging it; never resumed
            with pytest.raises(CampaignStop, match="is rejected"):
                run(m, api)
            assert len([e for e in events(m) if e["type"] == "external_resume_detected"]) == 1
            with pytest.raises(LedgerError):
                resume_cell(m, api, cell.key)
            supersede_cell(m, cell.key, "resumed through the API by mistake")
            app.state.agent_factory = declared_factory()
            assert run(m, api)["submitted"] == 1
    finally:
        probe.gate.set()
    assert len(api.posts) == 2
    assert validate_mod.validate_campaign(m)["complete"] is True


def failing_at_positions(*positions: int):
    """Declared-ollama factory whose trial at any of ``positions`` fails the
    evaluation (the per-trial seed hook raises); the other positions complete."""

    def factory(model, task, params):
        agent = worker.mock_agent_factory(model, task, params)

        def set_run_seed(seed: int) -> None:
            if seed - params.base_seed in positions:
                raise RuntimeError(f"simulated backend failure at position {seed - params.base_seed}")

        agent.set_run_seed = set_run_seed  # type: ignore[attr-defined]
        return agent

    factory.backend_kind = "ollama"  # type: ignore[attr-defined]
    return factory


def test_an_outside_resume_that_failed_again_is_still_detected(base, tmp_path, monkeypatch):
    m = make_campaign(base, tmp_path, [MODEL], [TASK], 2)
    cell = m.cells()[0]
    FakeOllama(m.models).install(monkeypatch)
    with running_app(m.db_path(), failing_at_positions(0, 1)) as (app, api):
        with pytest.raises(CampaignStop, match="is failed"):
            run(m, api)
        evaluation_id = load_ledger(m).active_entry(cell.key)["evaluation_id"]
        app.state.agent_factory = failing_at_positions(1)  # position 0 now completes, position 1 fails
        assert api.resume(evaluation_id)["id"] == evaluation_id  # outside the tooling
        assert wait_terminal(api, evaluation_id)["status"] == "failed"
        with closing(cohort.open_readonly(m.db_path())) as conn:
            assert cohort.evaluation_progress(conn, evaluation_id)["completed"] == 1  # unguarded evidence
        with pytest.raises(CampaignStop, match="resumed outside the campaign tooling"):
            run(m, api)
    assert load_ledger(m).active_entry(cell.key)["state"] == REJECTED


def test_a_failed_entry_whose_evaluation_is_still_failed_is_not_an_external_resume(base, tmp_path, monkeypatch):
    # control for the reconciliation: nothing resumed it, so the launch halts on the
    # failed cell as before (resumable), without an external_resume_detected event
    m = make_campaign(base, tmp_path, [MODEL], [TASK], 1)
    cell = m.cells()[0]
    FakeOllama(m.models).install(monkeypatch)
    with running_app(m.db_path(), failing_factory) as (_app, api):
        with pytest.raises(CampaignStop, match="is failed"):
            run(m, api)
        with pytest.raises(CampaignStop, match="resume it under the same id"):
            run(m, api)
    assert load_ledger(m).active_entry(cell.key)["state"] == FAILED
    assert not any(e["type"] == "external_resume_detected" for e in events(m))


@pytest.mark.parametrize("violation", ["identity_violation", "concurrency_violation"])
def test_resume_is_refused_for_an_evaluation_that_recorded_a_violation(base, tmp_path, monkeypatch, code_check,
                                                                       capsys, violation):
    # round 4: its evidence can never count; the only remedy is supersede
    m = make_campaign(base, tmp_path, [MODEL], [TASK], 1)
    fake = FakeOllama(m.models).install(monkeypatch)
    key = seed_failed_cell(m, fake)
    ledger = load_ledger(m)
    ledger.update(ledger.active_entry(key), **{violation: {"at": "2026-09-26T00:10:00Z", "evaluations": ["e-x"]}})
    ledger.save()
    stub = StubApp([])
    with pytest.raises(CampaignStop, match="supersede") as stop:
        resume_cell(m, stub, key)
    assert violation.replace("_", " ") in str(stop.value)
    assert stub.calls == [] and fake.warmed == [] and code_check == []  # refused before anything else
    entry = load_ledger(m).active_entry(key)
    assert entry["state"] == FAILED and "resumes" not in entry
    assert not any(e["type"] in ("resume_requested", "resumed") for e in events(m))
    manifest_file = tmp_path / "manifest.json"
    dump(m.data, manifest_file)
    monkeypatch.setattr(api_mod, "AgentForgeApi", lambda url, **_: stub)
    assert cli.main(["--manifest", str(manifest_file), "resume", "--cell", key]) == 3
    assert "refused:" in capsys.readouterr().err
    supersede_cell(m, key, "tainted evaluation")
    assert load_ledger(m).active_entry(key) is None


def gated_failing_factory(gate: threading.Event):
    """Declared-ollama factory that blocks (the evaluation is 'running') until
    ``gate`` is set, then fails the trial: the evaluation ends 'failed'."""

    def factory(model, task, params):
        assert gate.wait(60), "the test never opened the gate"
        raise RuntimeError("simulated backend failure after the gate")

    factory.backend_kind = "ollama"  # type: ignore[attr-defined]
    return factory


def violation_clock(launcher_ref: dict, key: str, on_running, *, until: str):
    """Fake clock (+31 s per sleep, so every poll after the first runs the watch)
    whose sleep calls ``on_running()`` once our evaluation is running, and returns
    True from ``done()`` once the launcher's in-memory entry records ``until``."""
    now = [0.0]
    inner = deadline_sleep()
    state = {"fired": False}

    def done() -> bool:
        ledger = launcher_ref["launcher"].ledger
        entry = ledger.active_entry(key) if ledger else None
        return bool(entry and entry.get(until))

    def sleep(seconds: float) -> None:
        ledger = launcher_ref["launcher"].ledger
        entry = ledger.active_entry(key) if ledger else None
        if entry and entry.get("evaluation_id") and not state["fired"]:
            if launcher_ref["api"].get_job(entry["evaluation_id"])["status"] == "running":
                state["fired"] = True
                on_running()
        launcher_ref["after"](done())
        now[0] += 31.0
        inner(seconds)

    return (lambda: now[0]), sleep


@pytest.mark.parametrize("outcome", ["succeeded", "failed"])
def test_a_server_version_change_while_an_evaluation_runs_rejects_it(base, tmp_path, monkeypatch, outcome):
    # round 4: the 30 s watch re-reads the SERVER version too. A change (even one
    # undone before the evaluation finishes) records an identity violation; a
    # succeeded evaluation is REJECTED at finalize, and a failed one is REJECTED
    # too - never advised for a resume (its evidence can no longer count).
    m = make_campaign(base, tmp_path, [MODEL], [TASK], 1)
    cell = m.cells()[0]
    fake = FakeOllama(m.models).install(monkeypatch)
    reference = fake.version
    gate = threading.Event()
    probe = GatedProbe()
    probe.gate = gate
    factory = probe.factory if outcome == "succeeded" else gated_failing_factory(gate)
    ref: dict = {}

    def upgrade() -> None:
        fake.version = "0.0-upgraded"

    def after(violated: bool) -> None:
        if violated:
            fake.version = reference  # restored before the evaluation finishes
            gate.set()

    ref["after"] = after
    clock, sleep = violation_clock(ref, cell.key, upgrade, until="identity_violation")
    logs: list[str] = []
    try:
        with running_app(m.db_path(), factory) as (_app, api):
            ref["api"] = api
            ref["launcher"] = make_launcher(m, api, logs, identity_poll_s=30.0, clock=clock, sleep=sleep)
            with pytest.raises(CampaignStop, match="is rejected|model identity not proven") as stop:
                ref["launcher"].run("A", check_code=True)
            assert "resume it under the same id" not in str(stop.value)
            entry = load_ledger(m).active_entry(cell.key)
            assert entry["state"] == REJECTED and entry["job_status"] == outcome
            violation = entry["identity_violation"]
            assert (violation["observed_ollama_version"], violation["expected_ollama_version"]) == (
                "0.0-upgraded", reference)
            assert violation["observed"] == violation["expected"] == fake.digests[MODEL]  # only the engine moved
            assert any("IDENTITY VIOLATION" in line and "0.0-upgraded" in line for line in logs)
            with pytest.raises(LedgerError):
                resume_cell(m, api, cell.key)
            receipt = validate_mod.validate_campaign(m)
            assert receipt["complete"] is False and receipt["missing"]["cells"] == [cell.key]
    finally:
        gate.set()
    if outcome == "succeeded":
        assert entry["ollama_version_at_submit"] == entry["ollama_version_at_finalize"] == reference
        assert any("model identity changed while the evaluation ran" in p for p in entry["problems"])
        # a hand-flip to 'succeeded' is still refused by the shared predicate
        ledger = load_ledger(m)
        ledger.update(ledger.active_entry(cell.key), state=SUCCEEDED, problems=[])
        ledger.save()
        receipt = validate_mod.validate_campaign(m)
        assert receipt["complete"] is False
        assert any("model identity violation observed" in p for p in receipt["problems"])
        assert status_mod.campaign_status(m)["cells"]["complete"] == 0


def test_a_server_version_change_between_launches_fails_the_preflight(base, tmp_path, monkeypatch):
    m = make_campaign(base, tmp_path, [MODEL], [TASK], 1)
    fake = FakeOllama(m.models).install(monkeypatch)
    with running_app(m.db_path(), declared_factory()) as (_app, api):
        run(m, api, max_evaluations=0)  # the first launch records the reference server version
        assert launcher.reference_ollama_version(load_ledger(m)) == "0.0-fake"
        fake.version = "0.0-upgraded"  # Ollama updated itself between launches
        with pytest.raises(CampaignStop, match="one cohort never mixes inference engines") as stop:
            run(m, api)
        assert "'0.0-upgraded'" in str(stop.value) and "'0.0-fake'" in str(stop.value)
        assert events(m)[-1]["type"] == "preflight_failed"
        assert len(load_ledger(m).data["launches"]) == 1  # the refused launch is not a launch
        pf = launcher.preflight(m, api, ledger=load_ledger(m), check_code=False)
        assert any("Ollama server version" in p for p in pf.problems)
        assert api.posts == [] and fake.warmed == []
        fake.version = "0.0-fake"  # the original server is back
        assert run(m, api)["submitted"] == 1
    assert validate_mod.validate_campaign(m)["complete"] is True


def test_a_server_version_change_before_a_submission_halts_it(base, tmp_path, monkeypatch):
    m = make_campaign(base, tmp_path, [MODEL], [TASK, "grid-paths"], 1)
    first, second = m.cells()
    fake = FakeOllama(m.models).install(monkeypatch)
    # inventory calls: 1 preflight, 2 before cell 1, 3 accepting cell 1, 4 before cell 2
    fake.from_call = {4: {"version": "0.0-upgraded"}}
    with running_app(m.db_path(), declared_factory()) as (_app, api):
        with pytest.raises(CampaignStop, match="never mix inference engines in one cohort"):
            run(m, api)
    assert len(api.posts) == 1 and fake.warmed == [MODEL]  # halted before loading or submitting cell 2
    ledger = load_ledger(m)
    assert ledger.active_entry(first.key)["state"] == SUCCEEDED and ledger.active_entry(second.key) is None
    assert ledger.data["launches"][-1]["outcome"] == "halted"


def test_a_server_version_change_at_finalize_is_a_durable_rejection(base, tmp_path, monkeypatch):
    m = make_campaign(base, tmp_path, [MODEL], [TASK], 1)
    cell = m.cells()[0]
    fake = FakeOllama(m.models).install(monkeypatch)
    fake.from_call = {3: {"version": "0.0-upgraded"}}  # 1 preflight, 2 before the submission, 3 at finalize
    with running_app(m.db_path(), declared_factory()) as (_app, api):
        with pytest.raises(CampaignStop, match="model identity not proven") as stop:
            run(m, api)
        assert "Ollama server version changed around the evaluation" in str(stop.value)
        entry = load_ledger(m).active_entry(cell.key)
        rejected_id = entry["evaluation_id"]
        assert (entry["state"], entry["job_status"]) == (REJECTED, "succeeded")
        assert (entry["ollama_version_at_submit"], entry["ollama_version_at_finalize"]) == ("0.0-fake", "0.0-upgraded")
        assert entry["model_digest_at_submit"] == entry["model_digest_at_finalize"] == fake.digests[MODEL]
        fake.from_call = {}  # the original server is back
        calls = fake.calls
        with pytest.raises(CampaignStop, match="is rejected"):
            run(m, api)
        assert fake.calls == calls + 1  # never re-judged (only the preflight read the inventory)
        receipt = validate_mod.validate_campaign(m)
        assert receipt["complete"] is False and receipt["missing"]["cells"] == [cell.key]
        # a hand-flip to 'succeeded' is still refused: the recorded finalize version is wrong
        ledger = load_ledger(m)
        ledger.update(ledger.active_entry(cell.key), state=SUCCEEDED, problems=[])
        ledger.save()
        receipt = validate_mod.validate_campaign(m)
        assert any("Ollama server version at submit/finalize 0.0-fake/0.0-upgraded" in p for p in receipt["problems"])
        ledger = load_ledger(m)
        ledger.update(ledger.active_entry(cell.key), state=REJECTED)
        ledger.save()
        supersede_cell(m, cell.key, "Ollama updated itself mid-campaign; restored 0.0-fake")
        assert run(m, api)["submitted"] == 1
    fresh = load_ledger(m).active_entry(cell.key)
    assert fresh["state"] == SUCCEEDED and fresh["evaluation_id"] != rejected_id
    assert validate_mod.validate_campaign(m)["complete"] is True


def test_resume_refuses_a_changed_server_version(base, tmp_path, monkeypatch):
    m = make_campaign(base, tmp_path, [MODEL], [TASK], 1)
    fake = FakeOllama(m.models).install(monkeypatch)
    key = seed_failed_cell(m, fake)
    fake.version = "0.0-upgraded"
    stub = StubApp([])
    with pytest.raises(CampaignStop, match="Ollama server version is '0.0-upgraded'"):
        resume_cell(m, stub, key)
    assert not any(isinstance(c, tuple) for c in stub.calls) and fake.warmed == []
    entry = load_ledger(m).active_entry(key)
    assert entry["state"] == FAILED and "resumes" not in entry
    fake.version = "0.0-fake"
    assert resume_cell(m, stub, key)["state"] == SUBMITTED


def test_another_evaluation_running_alongside_is_a_durable_concurrency_violation(base, tmp_path, monkeypatch):
    # round 4: while it waits, the launcher checks that no other evaluation is
    # RUNNING in the campaign database (the app runs every evaluation in its own
    # thread, so a UI run would share the model server). Here a second evaluation
    # really runs alongside the campaign's: recorded durably, then REJECTED.
    m = make_campaign(base, tmp_path, [MODEL], [TASK], 1)
    cell = m.cells()[0]
    FakeOllama(m.models).install(monkeypatch)
    probe = GatedProbe()
    ref: dict = {}
    foreign: list[str] = []

    def start_foreign() -> None:  # a UI evaluation, dispatched into its own worker thread
        response = ref["api"].client.post("/api/v1/jobs", json={"model": MODEL, "tasks": [TASK], "repeats": 1})
        foreign.append(response.json()["id"])

    ref["after"] = lambda violated: probe.gate.set() if violated else None
    clock, sleep = violation_clock(ref, cell.key, start_foreign, until="concurrency_violation")
    logs: list[str] = []
    try:
        with running_app(m.db_path(), probe.factory) as (_app, api):
            ref["api"] = api
            ref["launcher"] = make_launcher(m, api, logs, identity_poll_s=30.0, clock=clock, sleep=sleep)
            with pytest.raises(CampaignStop, match="EXCLUDED") as stop:
                ref["launcher"].run("A", check_code=True)
            assert "another evaluation ran alongside it" in str(stop.value)
            wait_terminal(api, foreign[0])
            entry = load_ledger(m).active_entry(cell.key)
            assert (entry["state"], entry["job_status"]) == (REJECTED, "succeeded")
            assert entry["concurrency_violation"]["evaluations"] == foreign
            assert any("CONCURRENCY VIOLATION" in line for line in logs)
            with pytest.raises(CampaignStop, match="is rejected"):
                run(m, api)  # durable
    finally:
        probe.gate.set()
    receipt = validate_mod.validate_campaign(m)
    assert receipt["complete"] is False and receipt["missing"]["cells"] == [cell.key]
    # a hand-flip to 'succeeded' (problems cleared, the recorded violation kept) is
    # still refused by the shared predicate: validator, monitor and analysis
    ledger = load_ledger(m)
    ledger.update(ledger.active_entry(cell.key), state=SUCCEEDED, problems=[])
    ledger.save()
    receipt = validate_mod.validate_campaign(m)
    assert receipt["complete"] is False
    assert any("another evaluation ran alongside it" in p for p in receipt["problems"])
    st = status_mod.campaign_status(m)
    assert st["cells"]["complete"] == 0
    assert {r["cell"]: r["state"] for r in st["cells_detail"]}[cell.key] == "succeeded-but-invalid"
    from afa_campaign import analysis
    cohort_cell = analysis.load_cohort(m).cells[cell.key]
    assert not cohort_cell.ok and any("alongside" in p for p in cohort_cell.problems)


def test_a_failed_evaluation_with_a_concurrency_violation_is_rejected_not_resumable(base, tmp_path, monkeypatch):
    # round 4: failed/canceled + a recorded violation -> REJECTED (never 'resume it')
    m = make_campaign(base, tmp_path, [MODEL], [TASK], 1)
    cell = m.cells()[0]
    FakeOllama(m.models).install(monkeypatch)
    gate = threading.Event()
    ref: dict = {}
    foreign: list[str] = []

    def start_foreign() -> None:  # never dispatched: a row the database shows 'running'
        foreign.append(create_directly(m, {"model": MODEL, "tasks": [TASK], "repeats": 1}))
        with closing(sqlite3.connect(str(m.db_path()))) as conn:
            conn.execute("UPDATE evaluation_jobs SET status='running' WHERE id=?", (foreign[0],))
            conn.commit()

    def after(violated: bool) -> None:
        if violated:
            with closing(sqlite3.connect(str(m.db_path()))) as conn:
                conn.execute("UPDATE evaluation_jobs SET status='canceled' WHERE id=?", (foreign[0],))
                conn.commit()
            gate.set()

    ref["after"] = after
    clock, sleep = violation_clock(ref, cell.key, start_foreign, until="concurrency_violation")
    try:
        with running_app(m.db_path(), gated_failing_factory(gate)) as (_app, api):
            ref["api"] = api
            ref["launcher"] = make_launcher(m, api, identity_poll_s=30.0, clock=clock, sleep=sleep)
            with pytest.raises(CampaignStop, match="is rejected") as stop:
                ref["launcher"].run("A", check_code=True)
            assert "resume it under the same id" not in str(stop.value) and "supersede" in str(stop.value)
            entry = load_ledger(m).active_entry(cell.key)
            assert (entry["state"], entry["job_status"]) == (REJECTED, "failed")
            assert entry["concurrency_violation"]["evaluations"] == foreign
            assert any("simulated backend failure after the gate" in p for p in entry["problems"])
            assert any(p.startswith("concurrency violation:") for p in entry["problems"])
            with pytest.raises(LedgerError):
                resume_cell(m, api, cell.key)
    finally:
        gate.set()


def straddle_trials(manifest: Manifest, foreign: str, *, before_s: int, after_s: int | None):
    """on_terminal hook: give ``foreign``'s trial the interval [our claimed_at -
    before_s, our completed_at + after_s] (``after_s=None``: still in progress,
    completed_at NULL). Timestamps are the runtime's second-resolution UTC
    ``datetime('now')`` strings."""

    def hook(evaluation_id: str) -> None:
        if evaluation_id == foreign:
            return
        with closing(sqlite3.connect(str(manifest.db_path()))) as conn:
            claimed, completed = conn.execute(
                "SELECT claimed_at, completed_at FROM evaluation_trials WHERE evaluation_id=? AND idx=0",
                (evaluation_id,)).fetchone()
            assert claimed and completed
            if after_s is None:
                conn.execute("UPDATE evaluation_trials SET trial_state='claimed', "
                             "claimed_at=datetime(?, ?), completed_at=NULL WHERE evaluation_id=?",
                             (completed, f"-{before_s} seconds", foreign))
                conn.execute("UPDATE evaluation_jobs SET status='running' WHERE id=?", (foreign,))
            else:
                conn.execute("UPDATE evaluation_trials SET claimed_at=datetime(?, ?), completed_at=datetime(?, ?) "
                             "WHERE evaluation_id=?",
                             (claimed, f"-{before_s} seconds", completed, f"{after_s:+d} seconds", foreign))
            conn.commit()

    return hook


def canceled_foreign(manifest: Manifest) -> str:
    """A non-campaign evaluation, canceled before the app starts (never run)."""
    foreign = create_directly(manifest, {"model": MODEL, "tasks": [TASK], "repeats": 1})
    with closing(app_db.connect(manifest.db_path())) as conn:
        assert jobs.request_cancel(conn, foreign).status == "canceled"
    return foreign


@pytest.mark.parametrize("window", ["straddles ours", "ends inside ours"])
def test_trials_overlapping_another_evaluations_are_rejected_at_finalize(base, tmp_path, monkeypatch, window):
    # round 4: before accepting a cell the launcher asks the database whether any
    # other evaluation's completed trial overlapped this one's (strictly, at the
    # runtime's one-second resolution): the evidence shared the model server
    m = make_campaign(base, tmp_path, [MODEL], [TASK], 1)
    cell = m.cells()[0]
    fake = FakeOllama(m.models).install(monkeypatch)
    foreign = canceled_foreign(m)
    if window == "straddles ours":  # [ours - 5 s, ours + 1 s]
        hook = straddle_trials(m, foreign, before_s=5, after_s=1)
    else:  # [ours - 5 s, our end - 1 s], ours stretched to >= 3 s so the end lies strictly inside it
        inner_hook = straddle_trials(m, foreign, before_s=5, after_s=-1)

        def hook(evaluation_id: str) -> None:
            if evaluation_id != foreign:
                with closing(sqlite3.connect(str(m.db_path()))) as conn:
                    conn.execute("UPDATE evaluation_trials SET claimed_at=datetime(completed_at, '-3 seconds') "
                                 "WHERE evaluation_id=?", (evaluation_id,))
                    conn.commit()
            inner_hook(evaluation_id)
    with hooked_app(m.db_path(), declared_factory(), on_terminal=hook) as (_app, api):
        with pytest.raises(CampaignStop, match="EXCLUDED") as stop:
            run(m, api)
    assert "ran at the same time as this evaluation's" in str(stop.value) and foreign in str(stop.value)
    entry = load_ledger(m).active_entry(cell.key)
    assert (entry["state"], entry["job_status"]) == (REJECTED, "succeeded")
    assert any(foreign in p and "same time" in p for p in entry["problems"])
    assert "model_digest_at_finalize" not in entry  # rejected before the identity read
    assert fake.calls == 2
    with closing(cohort.open_readonly(m.db_path())) as conn:
        assert cohort.overlapping_evaluations(conn, entry["evaluation_id"]) == [foreign]
        assert cohort.overlapping_evaluations(conn, foreign) == [entry["evaluation_id"]]
    receipt = validate_mod.validate_campaign(m)
    assert receipt["complete"] is False and receipt["missing"]["cells"] == [cell.key]
    st = status_mod.campaign_status(m)
    assert st["cells"]["complete"] == 0 and st["totals"]["excluded_runs"] == 1
    from afa_campaign import analysis
    assert analysis.official_baseline(m) is None


def test_trials_that_only_touch_at_a_second_boundary_do_not_overlap(base, tmp_path, monkeypatch):
    # control: sequential evaluations share boundary seconds (one ends in the second
    # the next starts); the strict comparison must not reject them
    m = make_campaign(base, tmp_path, [MODEL], [TASK], 1)
    cell = m.cells()[0]
    FakeOllama(m.models).install(monkeypatch)
    foreign = canceled_foreign(m)

    def touching(evaluation_id: str) -> None:
        with closing(sqlite3.connect(str(m.db_path()))) as conn:
            claimed = conn.execute("SELECT claimed_at FROM evaluation_trials WHERE evaluation_id=? AND idx=0",
                                   (evaluation_id,)).fetchone()[0]
            conn.execute("UPDATE evaluation_trials SET claimed_at=datetime(?, '-9 seconds'), completed_at=? "
                         "WHERE evaluation_id=?", (claimed, claimed, foreign))
            conn.commit()

    with hooked_app(m.db_path(), declared_factory(), on_terminal=touching) as (_app, api):
        assert run(m, api)["submitted"] == 1
    entry = load_ledger(m).active_entry(cell.key)
    assert entry["state"] == SUCCEEDED
    with closing(cohort.open_readonly(m.db_path())) as conn:
        assert cohort.overlapping_evaluations(conn, entry["evaluation_id"]) == []
    assert validate_mod.validate_campaign(m)["complete"] is True


def test_a_trial_of_another_evaluation_still_running_at_finalize_rejects_the_cell(base, tmp_path, monkeypatch):
    m = make_campaign(base, tmp_path, [MODEL], [TASK], 1)
    cell = m.cells()[0]
    FakeOllama(m.models).install(monkeypatch)
    foreign = canceled_foreign(m)
    # the foreign trial was claimed 1 s before ours completed and has not finished
    hook = straddle_trials(m, foreign, before_s=1, after_s=None)
    with hooked_app(m.db_path(), declared_factory(), on_terminal=hook) as (_app, api):
        with pytest.raises(CampaignStop, match="EXCLUDED"):
            run(m, api)
    assert load_ledger(m).active_entry(cell.key)["state"] == REJECTED


def test_overlap_the_database_proves_is_never_accepted(base, tmp_path, monkeypatch):
    m = make_campaign(base, tmp_path, [MODEL], [TASK], 1)
    cell = m.cells()[0]
    FakeOllama(m.models).install(monkeypatch)
    foreign = canceled_foreign(m)
    with running_app(m.db_path(), declared_factory()) as (_app, api):
        assert run(m, api)["submitted"] == 1
    evaluation_id = load_ledger(m).active_entry(cell.key)["evaluation_id"]
    assert validate_mod.validate_campaign(m)["complete"] is True  # control
    # the other evaluation's trial, still running at finalize, completes afterwards
    straddle_trials(m, foreign, before_s=1, after_s=5)(evaluation_id)
    with closing(cohort.open_readonly(m.db_path())) as conn:
        assert cohort.overlapping_evaluations(conn, evaluation_id) == [foreign]  # the database proves it
    receipt = validate_mod.validate_campaign(m)
    assert receipt["complete"] is False and receipt["missing"]["cells"] == [cell.key]
    assert status_mod.campaign_status(m)["cells"]["complete"] == 0


@pytest.mark.parametrize("failures", [1, 2, 3])
def test_finalize_retries_a_failed_ollama_read_three_times(base, tmp_path, monkeypatch, failures):
    # round 4: the identity read at finalize is retried (3 attempts, 10 s apart)
    # before the cell becomes a durable needs_attention
    m = make_campaign(base, tmp_path, [MODEL], [TASK], 1)
    cell = m.cells()[0]
    fake = FakeOllama(m.models).install(monkeypatch)
    # 1 preflight, 2 before the submission, 3.. the reads at finalize
    fake.from_call = {3: {"unreachable": True}, 3 + failures: {"unreachable": False}}
    slept: list[float] = []
    inner = deadline_sleep()

    def sleep(seconds: float) -> None:
        slept.append(seconds)
        inner(seconds)

    with running_app(m.db_path(), declared_factory()) as (_app, api):
        launch = make_launcher(m, api, sleep=sleep)
        if failures < 3:
            assert launch.run("A", check_code=True)["submitted"] == 1
        else:
            with pytest.raises(CampaignStop, match="needs_attention") as stop:
                launch.run("A", check_code=True)
            assert "model identity could not be verified" in str(stop.value)
    entry = load_ledger(m).active_entry(cell.key)
    assert slept.count(10.0) == min(failures, 2)
    assert fake.calls == 2 + min(failures + 1, 3)
    if failures < 3:
        assert entry["state"] == SUCCEEDED and entry["model_digest_at_finalize"] == fake.digests[MODEL]
        assert validate_mod.validate_campaign(m)["complete"] is True
    else:
        assert entry["state"] == "needs_attention" and "model_digest_at_finalize" not in entry
        assert validate_mod.validate_campaign(m)["complete"] is False
        assert status_mod.campaign_status(m)["totals"]["excluded_runs"] == 1


def test_the_rehearsal_flags_say_the_touched_cells_are_not_official_evidence(capsys):
    # round 4 (cli): the help text matches the evidence-tied audit
    texts = {}
    for command in ("launch", "resume"):
        with pytest.raises(SystemExit):
            cli.main([command, "--help"])
        texts[command] = " ".join(capsys.readouterr().out.split())
    assert ("--no-warmup ONLY for rehearsals; recorded, and the cells it submits are not official evidence"
            in texts["launch"])
    assert ("--no-code-check ONLY for rehearsals; recorded, and the cells it submits, resumes or finalizes are "
            "not official evidence" in texts["launch"])
    assert ("--no-code-check ONLY for rehearsals; recorded, and the resumed cell is not official evidence"
            in texts["resume"])
    assert not any("makes the campaign non-official" in t for t in texts.values())


# =========================================================================== #
# round 5: every resume is settled from the app's own events; a failure that
# can never become official evidence is never advised to be resumed
# =========================================================================== #


def _resume_event_count(manifest: Manifest, evaluation_id: str) -> int:
    with closing(cohort.open_readonly(manifest.db_path())) as conn:
        return cohort.resume_event_count(conn, evaluation_id)


@pytest.mark.parametrize("killed_first", [True, False], ids=["after-a-killed-resume", "control"])
def test_a_resume_command_killed_before_its_post_never_masks_an_outside_resume(base, tmp_path, monkeypatch,
                                                                                killed_first):
    # R5-F1: a 'requested' record (the command died before its POST reached the app)
    # is settled by the next launch like an 'unknown' one; otherwise it would count as
    # a tooling resume forever and hide one resume made outside the tooling.
    m = make_campaign(base, tmp_path, [MODEL], [TASK], 1)
    cell = m.cells()[0]
    FakeOllama(m.models).install(monkeypatch)
    with running_app(m.db_path(), failing_factory) as (app, api):
        with pytest.raises(CampaignStop, match="is failed"):
            run(m, api)
        eid = load_ledger(m).active_entry(cell.key)["evaluation_id"]
        if killed_first:
            def killed(_eid):
                raise Killed()

            api.resume = killed
            with pytest.raises(Killed):
                resume_cell(m, api, cell.key)
            del api.resume
            assert [r["outcome"] for r in load_ledger(m).active_entry(cell.key)["resumes"]] == ["requested"]
            with pytest.raises(CampaignStop, match="is failed"):
                run(m, api)  # the drain settles it: the app never resumed the evaluation
            entry = load_ledger(m).active_entry(cell.key)
            assert entry["state"] == FAILED
            assert [r["outcome"] for r in entry["resumes"]] == ["not_executed"]
            assert _resume_event_count(m, eid) == 0
        resume_cell(m, api, cell.key)  # a tooling resume, answered; the backend still fails
        assert wait_terminal(api, eid)["status"] == "failed"
        app.state.agent_factory = declared_factory()
        assert api.resume(eid)["id"] == eid  # outside the tooling, while the ledger says submitted
        assert wait_terminal(api, eid)["status"] == "succeeded"
        with pytest.raises(CampaignStop, match="resumed outside the tooling"):
            run(m, api)
    entry = load_ledger(m).active_entry(cell.key)
    assert entry["state"] == REJECTED and _resume_event_count(m, eid) == 2
    assert validate_mod.validate_campaign(m)["complete"] is False


def test_an_executed_killed_resume_is_counted_before_a_later_lost_one_is_judged(base, tmp_path, monkeypatch):
    # R5-F2: settled in order and by event time - the killed resume the app DID run
    # claims its event, so a later resume that never reached the app is not_executed
    m = make_campaign(base, tmp_path, [MODEL], [TASK], 1)
    cell = m.cells()[0]
    FakeOllama(m.models).install(monkeypatch)
    with running_app(m.db_path(), failing_factory) as (_app, api):
        with pytest.raises(CampaignStop, match="is failed"):
            run(m, api)
        eid = load_ledger(m).active_entry(cell.key)["evaluation_id"]
        real_resume = api.resume

        def killed_after_the_app_resumed(e):
            real_resume(e)
            raise Killed()

        api.resume = killed_after_the_app_resumed
        with pytest.raises(Killed):
            resume_cell(m, api, cell.key)
        del api.resume
        assert wait_terminal(api, eid)["status"] == "failed"
        with pytest.raises(CampaignStop, match="is failed"):
            run(m, api)
        assert [r["outcome"] for r in load_ledger(m).active_entry(cell.key)["resumes"]] == ["executed"]

        def never_reached_the_app(_e):
            raise ApiUnreachable("POST /resume: connection refused (simulated)")

        api.resume = never_reached_the_app
        with pytest.raises(CampaignStop, match="is unknown"):
            resume_cell(m, api, cell.key)
        del api.resume
        with pytest.raises(CampaignStop, match="is failed"):
            run(m, api)
    entry = load_ledger(m).active_entry(cell.key)
    assert _resume_event_count(m, eid) == 1
    assert [r["outcome"] for r in entry["resumes"]] == ["executed", "not_executed"]
    settled = [e for e in events(m) if e["type"] == "resume_outcome_settled"]
    assert [e["outcomes"] for e in settled] == [["executed"], ["executed", "not_executed"]]


def test_an_outside_resume_after_a_killed_launcher_that_fails_again_is_rejected_not_advised(
        base, tmp_path, monkeypatch):
    # R5-F3: the launcher is killed while the evaluation runs; it fails; someone
    # resumes it through the API and it fails again. The drain must not advise a
    # resume (that would run the whole evaluation only to be rejected): the app's
    # resume events outnumber the tooling's, so the cell is rejected at once.
    m = make_campaign(base, tmp_path, [MODEL], [TASK], 1)
    cell = m.cells()[0]
    FakeOllama(m.models).install(monkeypatch)
    with running_app(m.db_path(), failing_factory) as (_app, api):
        def die(_seconds: float) -> None:
            raise Killed()

        with pytest.raises(Killed):
            Launcher(m, api, log=lambda _m: None, poll_s=0.01, sleep=die).run("A", check_code=True)
        eid = load_ledger(m).active_entry(cell.key)["evaluation_id"]
        assert wait_terminal(api, eid)["status"] == "failed"
        assert api.resume(eid)["id"] == eid  # outside the tooling
        assert wait_terminal(api, eid)["status"] == "failed"
        with pytest.raises(CampaignStop, match="is rejected") as stop:
            run(m, api)
        assert "resumed outside the tooling" in str(stop.value) and "supersede" in str(stop.value)
        assert "resume it under the same id" not in str(stop.value)
        with pytest.raises(LedgerError):
            resume_cell(m, api, cell.key)
    assert load_ledger(m).active_entry(cell.key)["state"] == REJECTED


def test_an_outside_resume_while_submitted_that_fails_again_is_rejected(base, tmp_path, monkeypatch):
    # R5-F3 (b): a tooling resume (answered), then another one outside the tooling
    # while the ledger still says submitted; both fail
    m = make_campaign(base, tmp_path, [MODEL], [TASK], 1)
    cell = m.cells()[0]
    FakeOllama(m.models).install(monkeypatch)
    with running_app(m.db_path(), failing_factory) as (_app, api):
        with pytest.raises(CampaignStop, match="is failed"):
            run(m, api)
        eid = load_ledger(m).active_entry(cell.key)["evaluation_id"]
        resume_cell(m, api, cell.key)
        assert wait_terminal(api, eid)["status"] == "failed"
        assert api.resume(eid)["id"] == eid
        assert wait_terminal(api, eid)["status"] == "failed"
        with pytest.raises(CampaignStop, match="is rejected"):
            run(m, api)
    entry = load_ledger(m).active_entry(cell.key)
    assert entry["state"] == REJECTED and _resume_event_count(m, eid) == 2
    assert [r["outcome"] for r in entry["resumes"]] == ["accepted"]
    assert any("resumed outside the tooling" in p for p in entry["problems"])


def test_a_no_warmup_submission_that_fails_is_rejected_not_advised_to_resume(base, tmp_path, monkeypatch):
    # R5-F3 (c): a start that can never be official evidence is not worth resuming
    m = make_campaign(base, tmp_path, [MODEL], [TASK], 1)
    cell = m.cells()[0]
    FakeOllama(m.models).install(monkeypatch)
    with running_app(m.db_path(), failing_factory) as (_app, api):
        with pytest.raises(CampaignStop, match="is rejected") as stop:
            make_launcher(m, api, warmup=False).run("A", check_code=True)
        assert "resume it under the same id" not in str(stop.value)
    entry = load_ledger(m).active_entry(cell.key)
    assert entry["state"] == REJECTED
    assert any("not loaded before every start" in p for p in entry["problems"])
    supersede_cell(m, cell.key, "submitted by a --no-warmup rehearsal launch")
    assert load_ledger(m).active_entry(cell.key) is None


# =========================================================================== #
# round 6
# =========================================================================== #


def test_a_refused_connection_is_a_definitive_not_sent(tmp_path):
    # R6-F3 (transport): ECONNREFUSED proves the request never reached the app
    import socket

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]  # closed again when the block ends: nothing listens
    client = api_mod.AgentForgeApi(f"http://127.0.0.1:{port}", timeout=5)
    with pytest.raises(ApiNotSent):
        client.resume("e-anything")
    assert issubclass(ApiNotSent, ApiUnreachable)  # every other caller still treats it as unreachable


def test_a_resume_whose_connection_was_refused_is_not_sent_and_never_masks_an_outside_resume(
        base, tmp_path, monkeypatch):
    # R6-F3: a refused connection is recorded 'not_sent' (never 'unknown'), the entry
    # is reverted, and it can never claim a resume made outside the tooling
    m = make_campaign(base, tmp_path, [MODEL], [TASK], 1)
    cell = m.cells()[0]
    FakeOllama(m.models).install(monkeypatch)
    with running_app(m.db_path(), failing_factory) as (app, api):
        with pytest.raises(CampaignStop, match="is failed"):
            run(m, api)
        eid = load_ledger(m).active_entry(cell.key)["evaluation_id"]

        def refused(_eid):
            raise ApiNotSent("POST /resume: [Errno 61] Connection refused (simulated)")

        api.resume = refused
        with pytest.raises(CampaignStop, match="nothing was resumed"):
            resume_cell(m, api, cell.key)
        del api.resume
        entry = load_ledger(m).active_entry(cell.key)
        assert entry["state"] == FAILED and entry["problems"] == ["simulated backend failure"]
        assert [r["outcome"] for r in entry["resumes"]] == ["not_sent"]
        assert any(e["type"] == "resume_not_sent" for e in events(m))
        app.state.agent_factory = declared_factory()
        assert api.resume(eid)["id"] == eid  # outside the tooling, seconds later
        assert wait_terminal(api, eid)["status"] == "succeeded"
        with pytest.raises(CampaignStop, match="is rejected"):
            run(m, api)
    entry = load_ledger(m).active_entry(cell.key)
    assert entry["state"] == REJECTED
    assert any("resumed outside the campaign tooling" in p for p in entry["problems"])
    assert validate_mod.validate_campaign(m)["complete"] is False


def test_a_lost_resume_the_app_executes_only_after_the_drain_is_rejected_never_credited(
        base, tmp_path, monkeypatch):
    # R6-F1 (documented limit, safe side): outcomes are settled ONCE before the launch
    # waits; a lost request that a stalled app executes afterwards cannot be told
    # from a resume outside the tooling, so the cell is rejected (supersede) - a
    # settled record is never re-opened, since that could credit an outside resume
    m = make_campaign(base, tmp_path, [MODEL], [TASK], 1)
    cell = m.cells()[0]
    FakeOllama(m.models).install(monkeypatch)
    with running_app(m.db_path(), failing_factory) as (app, api):
        with pytest.raises(CampaignStop, match="is failed"):
            run(m, api)
        app.state.agent_factory = declared_factory()
        real_resume = api.resume

        def lost(_eid):
            raise ApiUnreachable("POST /resume: timed out (simulated)")

        api.resume = lost
        with pytest.raises(CampaignStop, match="is unknown"):
            resume_cell(m, api, cell.key)
        del api.resume
        original = cohort.resume_event_times

        def late(conn, evaluation_id):
            times = original(conn, evaluation_id)
            real_resume(evaluation_id)  # the stalled app executes the tooling's request now
            return times

        monkeypatch.setattr(cohort, "resume_event_times", late)
        with pytest.raises(CampaignStop, match="not official campaign evidence"):
            run(m, api)
        monkeypatch.setattr(cohort, "resume_event_times", original)
    entry = load_ledger(m).active_entry(cell.key)
    assert entry["state"] == REJECTED and entry["job_status"] == "succeeded"
    assert [(r["outcome"], r["settled_from"]) for r in entry["resumes"]] == [("not_executed", "unknown")]
    supersede_cell(m, cell.key, "a lost resume request executed late by a stalled app")
    assert load_ledger(m).active_entry(cell.key) is None


def test_resume_refuses_a_failed_start_that_can_never_be_official(base, tmp_path, monkeypatch):
    # R6-F4: a failed entry left by older tooling whose start was not code-checked (or
    # not warmed) is never resumed - that could never make it official
    m = make_campaign(base, tmp_path, [MODEL], [TASK], 1)
    fake = FakeOllama(m.models).install(monkeypatch)
    for field_name in ("code_check_at_submit", "warmed_up_at_submit"):
        key = seed_failed_cell(m, fake)
        ledger = load_ledger(m)
        ledger.update(ledger.active_entry(key), **{field_name: False})
        ledger.save()
        stub = StubApp()
        with pytest.raises(CampaignStop, match="supersede the cell instead"):
            resume_cell(m, stub, key)
        assert ("resume", "e-original") not in stub.calls and fake.warmed == []
        assert load_ledger(m).active_entry(key)["state"] == FAILED
        m.ledger_path().unlink()
