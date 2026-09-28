"""Independent tests of the SEQUENTIAL-LOCAL campaign tooling (``phase0-modern-local-v1``).

A sequential-local plan runs ONE MODEL PER PHASE (M1, M2, ...), installed and
benchmarked one at a time under tight local storage: install or reuse the target
-> smoke (scratch) -> launch --phase Mx -> validate --phase Mx -> model-receipt
-> remove-model -> next model; or the model is CLASSIFIED and leaves the expected
cohort (never ranked).

Almost every campaign here is a small derived subset of the COMMITTED modern
manifest (at most 2 roster models x 2 tasks x 2 repetitions) in the test's tmp
directory, executed end to end through the REAL app (``create_app()`` under a
TestClient, bound to a clean campaign database) with the declared-ollama
reference-overlay agent of ``test_campaign_launcher``. A derived plan inherits the
frozen plan's pins (model digests, Ollama SERVER version, cohort floor
``minimum_ranked_models`` = 3) and needs no recorded smoke; the tests of the
campaign's OWN plan kind (not derived: a smoke is required before a launch) build
one with ``build_modern_manifest`` into the tmp directory (``own_plan``).

Ollama is a LOCAL FAKE HTTP SERVER (127.0.0.1, ephemeral port) started by the
test (``FakeOllamaServer``): the launcher's inventory / warm-up path and the
lifecycle's tags / ps / pull / delete path talk to the SAME fake state, so a
model removed by ``remove_model`` really is gone for the next preflight; it
reports the Ollama server version the frozen plan pins unless a test is about a
mismatch. Every manifest's ``backend.base_url`` is rewritten to the fake, and an
autouse guard refuses any Ollama call (``ollama._call``, ``lifecycle._ollama_call``,
``lifecycle._pull_stream``) to anything but a fake server started here, so no
test can pull or delete a real model; ``lifecycle._start_app`` (the real
``afa_app.py`` subprocess) is disabled. Free disk space is faked
(``lifecycle.disk_free``); ``OLLAMA_MODELS`` and, where an inventory walks it,
``HOME`` point into the tmp directory. A "live smoke app" is a harmless sleeping
child process started by the test in its own session (never this process).

Tests asserting behaviour the product does not have are marked
``xfail(strict=True, reason="PRODUCT BUG: ...")``.
"""

from __future__ import annotations

import copy
import datetime
import hashlib
import json
import re
import signal
import socket
import subprocess
import sys
import threading
import types
import urllib.error
from contextlib import closing, contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import pytest

from afa_campaign import analysis, cli, cohort, launcher, lifecycle, ollama, paths
from afa_campaign import status as status_mod
from afa_campaign import validate as validate_mod
from afa_campaign.analysis import AnalysisError
from afa_campaign.launcher import CampaignStop
from afa_campaign.ledger import FAILED, REJECTED, SUCCEEDED, Ledger, LedgerError
from afa_campaign.lifecycle import (
    GIB, PULL_MARGIN_BYTES, classify_model, model_receipt, pull_model, remove_model, run_smoke, storage_inventory,
)
from afa_campaign.manifest import (
    KIND_HISTORICAL, KIND_SEQUENTIAL, MODERN_CAMPAIGN_ID, MODERN_LOCAL_ROSTER, Manifest, ManifestError,
    build_modern_manifest, canonical_sha256, derive_subset, dump, expected_counts, file_sha256,
)
from afa_campaign.manifest import validate as validate_plan

from afa_api import worker
from afa_api.main import create_app

from test_campaign_launcher import (  # noqa: F401 - ``base`` and the autouse ``code_check`` are fixtures
    HISTORICAL_SHA256, FakeOllama, base, code_check, create_directly, declared_factory, evaluation_ids,
    failing_factory, hooked_app, load_ledger, make_campaign, make_launcher, running_app,
)

M1, M2, M5 = "qwen3.5:9b", "gpt-oss:20b", "qwen3.6:27b"
OTHER = "llama3.2:latest"  # an Ollama model outside the modern roster
TASK, TASK2 = "two-sum-indices", "grid-paths"
STALE = "0" * 64  # a build of the same tag with other weights (never the pin)
# the Ollama SERVER version the frozen plan pins (a fake reports it unless a test is about a mismatch)
PINNED_VERSION = json.loads(paths.MODERN_MANIFEST.read_text())["execution"]["ollama_server_version"]
OTHER_VERSION = "0.12.3-fake"  # any other server build


# --------------------------------------------------------------------------- #
# hermetic Ollama, disk and app
# --------------------------------------------------------------------------- #

FAKE_PORTS: set[int] = set()


def _only_a_fake_ollama(url: str) -> None:
    parts = urlsplit(url)
    if parts.hostname != "127.0.0.1" or parts.port not in FAKE_PORTS:
        raise AssertionError(f"a test tried to reach {url}; only a fake Ollama started by the test is allowed")


class FakeDisk:
    """``lifecycle.disk_free`` stand-in; pulls consume and deletions free space."""

    def __init__(self, free: int = 400 * GIB, total: int = 1000 * GIB) -> None:
        self.free, self.total = free, total

    def __call__(self, path=None) -> dict:
        return {"total_bytes": self.total, "used_bytes": self.total - self.free, "free_bytes": self.free}


class FakeOllamaServer:
    """A local HTTP stand-in for Ollama: /api/version, tags, ps, show, generate
    (warm-up / keep_alive=0 unload), delete and a streamed /api/pull that
    installs what ``registry`` serves for the model."""

    def __init__(self, disk: FakeDisk) -> None:
        self.disk = disk
        self.lock = threading.RLock()
        self.version = PINNED_VERSION
        self.models: dict[str, dict] = {}
        self.registry: dict[str, dict] = {}  # what a pull of that tag installs
        self.loaded: set[str] = set()
        self.sticky: set[str] = set()  # loaded models that ignore an unload
        self.requests: list[tuple[str, str]] = []
        self.pulls: list[str] = []
        self.deletes: list[str] = []
        self.generates: list[tuple[str, object]] = []
        self.unloads: list[str] = []
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), _handler(self))
        self.httpd.daemon_threads = True
        self.port = self.httpd.server_address[1]
        FAKE_PORTS.add(self.port)
        self._thread = threading.Thread(target=self.httpd.serve_forever, kwargs={"poll_interval": 0.05},
                                        daemon=True)
        self._thread.start()
        self._stopped = False

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def stop(self) -> None:
        if not self._stopped:
            self._stopped = True
            self.httpd.shutdown()
            self.httpd.server_close()

    # -- state
    def install(self, model: str, digest: str, *, size: int = GIB, fmt: str = "gguf", family: str = "fake",
                parameter_size: str = "1B", quantization: str = "Q4_K_M") -> None:
        with self.lock:
            self.models[model] = {"digest": digest, "size": size, "format": fmt, "family": family,
                                  "parameter_size": parameter_size, "quantization": quantization}

    @staticmethod
    def _identity(manifest: Manifest, phase: str, digest: str | None) -> tuple[str, dict]:
        entry = manifest.phase_entry(phase)
        ident = entry["expected_identity"]
        return entry["model"], {"digest": digest or ident["digest"], "size": ident["download_bytes"],
                                "fmt": ident["format"], "family": ident["family"],
                                "parameter_size": ident["parameter_size"], "quantization": ident["quantization"]}

    def install_pinned(self, manifest: Manifest, phase: str, digest: str | None = None) -> None:
        model, ident = self._identity(manifest, phase, digest)
        self.install(model, ident.pop("digest"), **ident)

    def serve(self, manifest: Manifest, phase: str, digest: str | None = None) -> None:
        model, ident = self._identity(manifest, phase, digest)
        with self.lock:
            self.registry[model] = ident

    def set_digest(self, model: str, digest: str) -> None:
        with self.lock:
            self.models[model]["digest"] = digest

    def remove(self, model: str) -> None:
        with self.lock:
            info = self.models.pop(model)
            self.loaded.discard(model)
            self.disk.free += info["size"]

    # -- HTTP
    def _tag(self, name: str) -> dict:
        info = self.models[name]
        return {"name": name, "model": name, "digest": info["digest"], "size": info["size"],
                "modified_at": "2026-09-27T12:00:00Z",
                "details": {"format": info["format"], "family": info["family"], "families": [info["family"]],
                            "parameter_size": info["parameter_size"], "quantization_level": info["quantization"]}}

    def handle(self, method: str, path: str, body) -> tuple[int, object]:
        body = body if isinstance(body, dict) else {}
        model = body.get("model") or body.get("name")
        with self.lock:
            self.requests.append((method, path))
            if (method, path) == ("GET", "/api/version"):
                return 200, {"version": self.version}
            if (method, path) == ("GET", "/api/tags"):
                return 200, {"models": [self._tag(name) for name in sorted(self.models)]}
            if (method, path) == ("GET", "/api/ps"):
                return 200, {"models": [{"name": n, "model": n, "size": self.models[n]["size"],
                                         "size_vram": self.models[n]["size"], "digest": self.models[n]["digest"]}
                                        for n in sorted(self.loaded) if n in self.models]}
            if (method, path) == ("POST", "/api/show"):
                if model not in self.models:
                    return 404, {"error": f"model '{model}' not found"}
                tag = self._tag(model)
                return 200, {"details": tag["details"], "modified_at": tag["modified_at"],
                             "capabilities": ["completion"],
                             "model_info": {"general.architecture": self.models[model]["family"]}}
            if (method, path) == ("POST", "/api/generate"):
                if model not in self.models:
                    return 404, {"error": f"model '{model}' not found"}
                keep = body.get("keep_alive")
                self.generates.append((model, keep))
                if keep in (0, "0", "0s"):
                    self.unloads.append(model)
                    if model not in self.sticky:
                        self.loaded.discard(model)
                else:
                    self.loaded.add(model)
                return 200, {"model": model, "response": "", "done": True}
            if (method, path) == ("DELETE", "/api/delete"):
                if model not in self.models:
                    return 404, {"error": f"model '{model}' not found"}
                self.deletes.append(model)
                self.remove(model)
                return 200, None
            if (method, path) == ("POST", "/api/pull"):
                self.pulls.append(model)
                served = self.registry.get(model)
                if served is None:
                    lines = [{"status": "pulling manifest"}, {"error": "pull model manifest: file does not exist"}]
                else:
                    total = served["size"]
                    lines = [{"status": "pulling manifest"},
                             {"status": "pulling 6488c96fa5fa", "total": total, "completed": 0},
                             {"status": "pulling 6488c96fa5fa", "total": total, "completed": total // 2},
                             {"status": "pulling 6488c96fa5fa", "total": total, "completed": total},
                             {"status": "verifying sha256 digest"}, {"status": "writing manifest"},
                             {"status": "success"}]
                    ident = dict(served)
                    self.install(model, ident.pop("digest"), **ident)
                    self.disk.free -= total
                return 200, b"".join(json.dumps(line).encode() + b"\n" for line in lines)
            return 404, {"error": f"unknown endpoint {method} {path}"}


def _handler(fake: FakeOllamaServer):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.0"

        def log_message(self, *_args) -> None:
            pass

        def _serve(self, method: str) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b""
            try:
                body = json.loads(raw) if raw else None
            except ValueError:
                body = None
            status, payload = fake.handle(method, urlsplit(self.path).path, body)
            if isinstance(payload, bytes):
                data, kind = payload, "application/x-ndjson"
            else:
                data, kind = (b"" if payload is None else json.dumps(payload).encode()), "application/json"
            self.send_response(status)
            self.send_header("Content-Type", kind)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:  # noqa: N802
            self._serve("GET")

        def do_POST(self) -> None:  # noqa: N802
            self._serve("POST")

        def do_DELETE(self) -> None:  # noqa: N802
            self._serve("DELETE")

    return Handler


@pytest.fixture(autouse=True)
def _hermetic(monkeypatch, tmp_path):
    """Only a fake Ollama started by the test can be reached; no real app
    subprocess, no memory probes, a scratch OLLAMA_MODELS."""
    real_call, real_pull, real_ollama_call = lifecycle._ollama_call, lifecycle._pull_stream, ollama._call

    def call(base_url, *args, **kwargs):
        _only_a_fake_ollama(base_url)
        return real_call(base_url, *args, **kwargs)

    def pull_stream(base_url, *args, **kwargs):
        _only_a_fake_ollama(base_url)
        return real_pull(base_url, *args, **kwargs)

    def ollama_call(base_url, *args, **kwargs):
        _only_a_fake_ollama(base_url)
        return real_ollama_call(base_url, *args, **kwargs)

    def no_real_app(*_args, **_kwargs):
        raise AssertionError("a test tried to start the real afa_app.py; pass start_app=")

    monkeypatch.setattr(lifecycle, "_ollama_call", call)
    monkeypatch.setattr(lifecycle, "_pull_stream", pull_stream)
    monkeypatch.setattr(ollama, "_call", ollama_call)
    monkeypatch.setattr(lifecycle, "_start_app", no_real_app)
    monkeypatch.setattr(lifecycle, "_memory_snapshot", lambda: {"note": "not measured in tests"})
    models_dir = tmp_path / "ollama-models"
    models_dir.mkdir()  # pull-model refuses a models directory that does not exist
    monkeypatch.setenv("OLLAMA_MODELS", str(models_dir))


@pytest.fixture(autouse=True)
def disk(monkeypatch) -> FakeDisk:
    fake = FakeDisk()
    monkeypatch.setattr(lifecycle, "disk_free", fake)
    return fake


@pytest.fixture
def server(disk):
    fake = FakeOllamaServer(disk)
    try:
        yield fake
    finally:
        fake.stop()


@pytest.fixture(scope="module")
def modern() -> Manifest:
    return Manifest.load(paths.MODERN_MANIFEST)


class BusyApp:
    """The ``list_jobs`` surface of an AgentForge app with evaluations in flight."""

    base = "stub"

    def __init__(self, jobs: list[dict]) -> None:
        self.jobs = jobs

    def list_jobs(self) -> list[dict]:
        return self.jobs


class ThreadedApp:
    """The real AgentForge app on a real local port, in-process (stands in for
    the smoke's app subprocess; ``poll()`` != None makes ``lifecycle._stop`` a no-op)."""

    def __init__(self, db_path: Path, port: int, factory) -> None:
        import uvicorn

        app = create_app()
        app.state.db_path = db_path
        app.state.agent_factory = factory
        self.server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error",
                                                    access_log=False, lifespan="on"))
        self.thread = threading.Thread(target=self.server.run, daemon=True, name=f"smoke-app-{port}")
        self.thread.start()
        self.pid = None

    def poll(self) -> int:
        return 0

    def stop(self) -> None:
        self.server.should_exit = True
        self.thread.join(30)


class ReachedApp(Exception):
    """A smoke got as far as starting its scratch app."""


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #


def make_modern(modern: Manifest, tmp_path: Path, server: FakeOllamaServer, models=(M1, M2),
                tasks=(TASK, TASK2), reps: int = 2, *, name: str = "c", campaign_id: str = "t-modern",
                init: bool = True, minimum_ranked: int | None = None,
                server_version: str | None = None) -> Manifest:
    """A small sequential campaign derived from the committed modern plan, its
    backend rewritten to the fake Ollama. It inherits the committed cohort floor
    (3 complete models) and server-version pin unless ``minimum_ranked`` /
    ``server_version`` set them (part of the frozen plan: set before the ledger)."""
    data = derive_subset(modern.data, campaign_id=campaign_id, models=list(models), task_ids=list(tasks),
                         repetitions=reps, campaign_db=str(tmp_path / f"{name}.sqlite"),
                         runtime_dir=str(tmp_path / f"{name}-rt"),
                         purpose="test of the sequential-local tooling (NOT campaign evidence)")
    data["backend"] = {**data["backend"], "base_url": server.url}
    data["model_files_owner"] = True  # a self-contained test plan owns the (fake) model files it names
    if minimum_ranked is not None:
        data["execution"] = {**data["execution"], "minimum_ranked_models": minimum_ranked}
    if server_version is not None:
        data["execution"] = {**data["execution"], "ollama_server_version": server_version}
    manifest = Manifest(data)
    if init:
        launcher.init_db(manifest)
    return manifest


def launch(manifest: Manifest, api, phase: str, **kw) -> dict:
    return make_launcher(manifest, api, kw.pop("logs", None)).run(phase, check_code=True, **kw)


def complete(manifest: Manifest, server: FakeOllamaServer, phase: str) -> None:
    """Install the phase's pinned target and run its whole batch."""
    server.install_pinned(manifest, phase)
    with running_app(manifest.db_path(), declared_factory()) as (_app, api):
        result = launch(manifest, api, phase)
    assert result["paused"] is False and result["submitted"] == len(manifest.cells(phase)), result
    receipt = validate_mod.validate_campaign(manifest, phase=phase)
    assert receipt["complete"], receipt["problems"]


def pin(manifest: Manifest, phase: str) -> str:
    return manifest.pinned_digests()[manifest.phase_entry(phase)["model"]]


def download_bytes(manifest: Manifest, phase: str) -> int:
    return manifest.phase_entry(phase)["expected_identity"]["download_bytes"]


def storage_log_lines(manifest: Manifest) -> list[dict]:
    target = manifest.runtime_subdir("inventories") / "storage-log.jsonl"
    return [json.loads(line) for line in target.read_text().splitlines()] if target.exists() else []


def ledger_or_none(manifest: Manifest) -> Ledger | None:
    return load_ledger(manifest) if manifest.ledger_path().exists() else None


def add_in_flight(manifest: Manifest, cell) -> None:
    """A ledger entry written before its POST (what a killed launcher leaves)."""
    ledger = Ledger.open_or_create(manifest.ledger_path(), campaign_id=manifest.campaign_id,
                                   manifest_sha256=manifest.sha256, manifest_path="")
    ledger.new_entry(key=cell.key, model=cell.model, task_id=cell.task_id, phase=cell.phase,
                     evaluation_name=manifest.evaluation_name(cell), positions=list(range(manifest.repetitions)))
    ledger.save()


def drop_in_flight(manifest: Manifest, key: str) -> None:
    ledger = load_ledger(manifest)
    ledger.data["entries"] = [e for e in ledger.entries if not (e["cell"] == key and not e.get("evaluation_id"))]
    ledger.save()


def foreign_evaluation(manifest: Manifest, cell) -> str:
    """A queued evaluation NOT named for the campaign (a UI experiment on the same DB)."""
    return create_directly(manifest, {**manifest.job_body(cell), "name": "ui-experiment"})


def evidence_snapshot(manifest: Manifest) -> dict:
    db_sha = file_sha256(manifest.db_path())
    with closing(cohort.open_readonly(manifest.db_path())) as conn:
        runs = conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
        evaluations = sorted((r["id"], r["status"]) for r in conn.execute("SELECT id, status FROM evaluation_jobs"))
    ledger = load_ledger(manifest)
    receipts, reports = manifest.runtime_subdir("receipts"), manifest.runtime_dir() / "evaluation-reports"
    return {
        "db_sha256": db_sha, "runs": runs, "evaluations": evaluations,
        "entries": copy.deepcopy(ledger.entries), "launches": copy.deepcopy(ledger.data["launches"]),
        "receipts": copy.deepcopy(ledger.data.get("receipts")), "model_status": ledger.data.get("model_status"),
        "receipt_files": {p.name: file_sha256(p) for p in sorted(receipts.glob("*"))},
        "reports": {p.name: file_sha256(p) for p in sorted(reports.glob("*"))},
    }


def flipping_factory(server: FakeOllamaServer, model: str, digest: str):
    """Declared-ollama agents that re-tag ``model`` to ``digest`` while a trial runs."""

    def factory(model_, task, params):
        agent = worker.mock_agent_factory(model_, task, params)
        inner = agent.act

        def act(workspace, task_, sandbox):
            server.set_digest(model, digest)
            return inner(workspace, task_, sandbox)

        agent.act = act
        return agent

    factory.backend_kind = "ollama"  # type: ignore[attr-defined]
    return factory


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def closed_api() -> str:
    """An app URL nothing listens on: connection refused (ApiNotSent), never a real app."""
    return f"http://127.0.0.1:{free_port()}"


def leaderboard_section(markdown: str) -> str:
    return markdown.split("## Leaderboard", 1)[1].split("## Task matrix", 1)[0]


def own_plan(modern: Manifest, tmp_path: Path, server: FakeOllamaServer, *, name: str = "own") -> Manifest:
    """The campaign's OWN plan kind, built exactly like the committed plan (all 5
    roster models, all 24 tasks, 5 repetitions, the real campaign id) - NOT a
    derived subset, so a passing smoke is required before any launch - with its
    database, runtime directory, app URL and Ollama in the test's hands."""
    code = modern.data["code"]
    data = build_modern_manifest(created_at=modern.data["created_at"], runtime_tag=code["runtime_release_tag"],
                                 runtime_commit=code["runtime_release_commit"], backend_base_url=server.url,
                                 campaign_db=str(tmp_path / f"{name}.sqlite"), runtime_dir=str(tmp_path / f"{name}-rt"),
                                 api_url=closed_api())
    assert "derived_from" not in data and "smoke_of" not in data
    manifest = Manifest(data)
    launcher.init_db(manifest)
    return manifest


def sleeper() -> subprocess.Popen:
    """A harmless child process in its OWN session (its pid is its process group)."""
    return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(300)"], start_new_session=True,
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def reap(proc: subprocess.Popen) -> None:
    if proc.poll() is None:
        proc.kill()
    proc.wait(30)


@contextmanager
def live_smoke_app(manifest: Manifest, folder: str = "M1-20260928T000000Z"):
    """A smoke app still alive: its pidfile under smoke_dir names a live process group."""
    proc = sleeper()
    try:
        target = manifest.runtime_subdir("smoke_dir") / folder
        target.mkdir(parents=True, exist_ok=True)
        (target / "app.pgid").write_text(str(proc.pid))
        yield proc
    finally:
        reap(proc)


def record_smoke(manifest: Manifest, **fields) -> None:
    """A smoke record in the main ledger (what run_smoke leaves behind)."""
    ledger = Ledger.open_or_create(manifest.ledger_path(), campaign_id=manifest.campaign_id,
                                   manifest_sha256=manifest.sha256, manifest_path="")
    ledger.record("smokes", {"model": manifest.phase_entry(fields["phase"])["model"], **fields})
    ledger.save()


def freeze_lifecycle_clock(monkeypatch, *instants: datetime.datetime) -> None:
    """``lifecycle._dt`` whose ``datetime.now`` returns ``instants`` in turn (the last one repeats)."""
    queue = list(instants)

    class Frozen(datetime.datetime):
        @classmethod
        def now(cls, tz=None):
            return queue.pop(0) if len(queue) > 1 else queue[0]

    monkeypatch.setattr(lifecycle, "_dt", types.SimpleNamespace(datetime=Frozen, timezone=datetime.timezone))


def cli_runner(manifest: Manifest, tmp_path: Path, capsys, name: str = "manifest.json"):
    manifest_file = tmp_path / name
    dump(manifest.data, manifest_file)

    def run_cli(*argv) -> tuple[int, str, str]:
        rc = cli.main(["--manifest", str(manifest_file), *argv])
        captured = capsys.readouterr()
        return rc, captured.out, captured.err

    return run_cli


# =========================================================================== #
# the frozen plan
# =========================================================================== #


def test_the_committed_modern_manifest_is_the_frozen_sequential_plan(modern):
    data = modern.data
    assert modern.kind == KIND_SEQUENTIAL and modern.is_sequential and modern.campaign_id == MODERN_CAMPAIGN_ID
    assert modern.phases == ["M1", "M2", "M3", "M4", "M5"] == data["execution"]["order"]
    assert data["roster"] == list(MODERN_LOCAL_ROSTER)
    assert modern.models == [M1, M2, "devstral-small-2:24b", "qwen3-coder:30b", M5]
    assert [e["optional"] for e in data["roster"]] == [False, False, False, False, True]
    assert modern.pinned_digests() == {e["model"]: e["expected_identity"]["digest"] for e in MODERN_LOCAL_ROSTER}
    assert all(re.fullmatch("[0-9a-f]{64}", d) for d in modern.pinned_digests().values())
    # 24 tasks, each pinned to the checked-out pack's version AND content digest
    assert len(modern.task_ids) == len(set(modern.task_ids)) == 24
    assert launcher.check_task_pins(modern) == []
    assert len(data["cells"]) == 120
    for entry in data["roster"]:
        mine = modern.cells(entry["phase"])
        assert len(mine) == 24 and {c.model for c in mine} == {entry["model"]}
        assert sorted(c.task_id for c in mine) == sorted(modern.task_ids)
    assert data["expected"] == expected_counts(data) == {
        "models": 5, "required_models": 4, "optional_models": 1, "tasks": 24, "cells": 120, "runs_per_cell": 5,
        "runs_per_model": 120, "total_runs": 600, "minimum_runs": 480,
        "phases": {e["phase"]: {"model": e["model"], "cells": 24, "runs": 120} for e in MODERN_LOCAL_ROSTER}}
    assert data["repetitions"] == 5 and data["mode"] == "fresh" and data["evidence_scope"] == "real"
    assert modern.backend["kind"] == "ollama"
    assert data["historical_evidence"]["sha256"] == HISTORICAL_SHA256
    assert Path(data["runtime"]["campaign_db"]).name != "runs.sqlite"
    assert set(data["execution"]["smoke"]["tasks"]) <= set(modern.task_ids)
    assert data["execution"]["smoke"]["repetitions"] == 1 and len(data["execution"]["smoke"]["tasks"]) == 4
    for cell in modern.cells():
        assert modern.job_body(cell)["name"] == f"campaign:{MODERN_CAMPAIGN_ID}:{cell.phase}:{cell.key}"


def test_build_modern_manifest_reproduces_the_committed_plan_from_the_checked_out_pack(modern):
    data = modern.data
    rebuilt = build_modern_manifest(created_at=data["created_at"], runtime_tag=data["code"]["runtime_release_tag"],
                                    runtime_commit=data["code"]["runtime_release_commit"])
    assert rebuilt == data
    assert canonical_sha256(rebuilt) == modern.sha256


def test_the_frozen_plan_pins_the_ollama_server_version_and_a_cohort_floor(modern, tmp_path):
    execution = modern.data["execution"]
    assert execution["ollama_server_version"] == "0.31.1" == PINNED_VERSION
    assert execution["minimum_ranked_models"] == 3
    assert "at least minimum_ranked_models models are COMPLETE" in execution["official_rule"]
    # every derived plan (rehearsal, smoke, the tests' campaigns) carries the same pins
    derived = derive_subset(modern.data, campaign_id="t-pins", models=[M2], task_ids=[TASK], repetitions=1,
                            campaign_db=str(tmp_path / "p.sqlite"), runtime_dir=str(tmp_path / "p-rt"), purpose="test")
    assert derived["execution"]["ollama_server_version"] == PINNED_VERSION
    assert derived["execution"]["minimum_ranked_models"] == 3
    # the validator refuses ill-typed pins
    for key, value, message in (("ollama_server_version", 31, "execution.ollama_server_version must be a string"),
                                ("minimum_ranked_models", "3", "execution.minimum_ranked_models must be an int")):
        data = copy.deepcopy(modern.data)
        data["execution"][key] = value
        with pytest.raises(ManifestError, match=re.escape(message)):
            validate_plan(data)
    # the builder writes exactly what it is given
    code = modern.data["code"]
    other = build_modern_manifest(created_at=modern.data["created_at"], runtime_tag=code["runtime_release_tag"],
                                  runtime_commit=code["runtime_release_commit"], ollama_server_version="0.40.0",
                                  minimum_ranked_models=4)
    assert (other["execution"]["ollama_server_version"], other["execution"]["minimum_ranked_models"]) == ("0.40.0", 4)
    assert canonical_sha256(other) != modern.sha256


BAD_PLANS = [
    pytest.param(lambda d: d["cells"][0].update(phase="M2"), "every cell's phase must be its model's roster phase",
                 id="cell-phase-mismatch"),
    pytest.param(lambda d: d["roster"][0]["expected_identity"].update(digest="6488c96fa5fa"),
                 "expected_identity.digest must be a 64-hex sha256", id="short-digest"),
    pytest.param(lambda d: d["roster"][1]["expected_identity"].update(digest="g" * 64),
                 "expected_identity.digest must be a 64-hex sha256", id="non-hex-digest"),
    pytest.param(lambda d: d["roster"][1]["expected_identity"].update(digest="A" * 64),
                 "expected_identity.digest must be a 64-hex sha256", id="uppercase-digest"),
    pytest.param(lambda d: d["roster"][1]["expected_identity"].update(digest=None),
                 "expected_identity.digest must be a 64-hex sha256", id="no-digest"),
    pytest.param(lambda d: [e.update(optional=True) for e in d["roster"]],
                 "at least one roster model must be required", id="no-required-model"),
    pytest.param(lambda d: d["roster"].reverse(), "roster models must equal models, in order", id="roster-order"),
    pytest.param(lambda d: d["roster"][1].update(phase="M1"), "every roster model needs its own phase",
                 id="duplicate-phase"),
    pytest.param(lambda d: d["roster"][0]["expected_identity"].pop("download_bytes"),
                 "expected_identity.download_bytes missing", id="no-download-size"),
    pytest.param(lambda d: d["roster"][0].update(optional="no"), "optional must be a bool", id="optional-not-bool"),
    pytest.param(lambda d: d["roster"][0].update(logical_name=""), "logical_name missing", id="no-logical-name"),
    pytest.param(lambda d: d.update(backend={"kind": "openai_compat", "base_url": "http://127.0.0.1:1"}),
                 "a sequential local plan runs on the local ollama backend", id="not-ollama"),
    pytest.param(lambda d: d.update(roster=[]), "a sequential plan needs a roster", id="no-roster"),
    pytest.param(lambda d: d.update(kind="parallel-cloud"), "unknown manifest kind", id="unknown-kind"),
]


@pytest.mark.parametrize("mutate, message", BAD_PLANS)
def test_the_manifest_validator_refuses_inconsistent_sequential_plans(modern, mutate, message):
    data = copy.deepcopy(modern.data)
    mutate(data)
    with pytest.raises(ManifestError, match=re.escape(message)):
        validate_plan(data)
    with pytest.raises(ManifestError):
        Manifest(data)


def test_the_manifest_validator_accepts_prefixed_pins_and_refuses_stale_expected_counts(modern):
    data = copy.deepcopy(modern.data)
    data["roster"][0]["expected_identity"]["digest"] = "sha256:" + data["roster"][0]["expected_identity"]["digest"]
    assert Manifest(data).pinned_digests()[M1] == modern.pinned_digests()[M1]
    data = copy.deepcopy(modern.data)
    data["roster"][4]["optional"] = False  # M5 required, but the frozen counts were not recomputed
    with pytest.raises(ManifestError, match="expected counts do not match the plan"):
        validate_plan(data)
    data["expected"] = expected_counts(data)
    assert Manifest(data).expected["minimum_runs"] == 600


def test_derive_subset_of_a_sequential_plan_keeps_each_models_phase_and_pins(modern, tmp_path):
    data = derive_subset(modern.data, campaign_id="t-derived", models=[M2, M1], task_ids=[TASK, TASK2],
                         repetitions=2, campaign_db=str(tmp_path / "d.sqlite"), runtime_dir=str(tmp_path / "d-rt"),
                         purpose="test")
    derived = Manifest(data)
    assert derived.kind == KIND_SEQUENTIAL and derived.models == [M1, M2]  # roster order, not request order
    assert data["roster"] == [e for e in modern.data["roster"] if e["model"] in (M1, M2)]  # pins unchanged
    assert derived.phases == ["M1", "M2"] == data["execution"]["order"]
    assert data["execution"]["smoke"] == modern.data["execution"]["smoke"]
    assert [(c.model, c.task_id, c.phase) for c in derived.cells()] == [
        (M1, TASK2, "M1"), (M1, TASK, "M1"), (M2, TASK2, "M2"), (M2, TASK, "M2")]
    assert data["expected"] == {
        "models": 2, "required_models": 2, "optional_models": 0, "tasks": 2, "cells": 4, "runs_per_cell": 2,
        "runs_per_model": 4, "total_runs": 8, "minimum_runs": 8,
        "phases": {"M1": {"model": M1, "cells": 2, "runs": 4}, "M2": {"model": M2, "cells": 2, "runs": 4}}}
    runtime = data["runtime"]
    for key in ("receipts", "inventories", "smoke_dir"):
        assert runtime[key] == f"{tmp_path / 'd-rt'}/{'smoke' if key == 'smoke_dir' else key}"
    assert runtime["ledger"] == f"{tmp_path / 'd-rt'}/ledger.json"
    assert data["derived_from"] == {"campaign_id": MODERN_CAMPAIGN_ID, "sha256": modern.sha256}
    assert data["generation"] == modern.data["generation"] and data["backend"] == modern.data["backend"]
    assert [t for t in data["tasks"]] == [t for t in modern.data["tasks"] if t["task_id"] in (TASK, TASK2)]

    optional = derive_subset(modern.data, campaign_id="t-opt", models=[M1, M5], task_ids=[TASK], repetitions=3,
                             campaign_db=str(tmp_path / "o.sqlite"), runtime_dir=str(tmp_path / "o-rt"),
                             purpose="test")
    assert optional["expected"]["required_models"] == 1 and optional["expected"]["optional_models"] == 1
    assert optional["expected"]["minimum_runs"] == 3 and optional["expected"]["total_runs"] == 6
    assert [e["phase"] for e in optional["roster"]] == ["M1", "M5"]
    with pytest.raises(ManifestError, match="unknown models"):
        derive_subset(modern.data, campaign_id="x", models=["qwen2.5-coder:7b"], task_ids=[TASK], repetitions=1,
                      campaign_db=str(tmp_path / "x.sqlite"), runtime_dir=str(tmp_path / "x"), purpose="test")


def test_cli_build_modern_manifest_never_overwrites_a_plan_without_force(modern, tmp_path, capsys):
    code = modern.data["code"]
    existing = tmp_path / "manifest.json"
    existing.write_text("{}\n")
    rc = cli.main(["build-modern-manifest", "--out", str(existing), "--runtime-tag", code["runtime_release_tag"],
                   "--runtime-commit", code["runtime_release_commit"]])
    assert rc == 2 and existing.read_text() == "{}\n"
    assert "refusing to overwrite" in capsys.readouterr().out
    fresh = tmp_path / "fresh.json"
    rc = cli.main(["build-modern-manifest", "--out", str(fresh), "--created-at", modern.data["created_at"],
                   "--runtime-tag", code["runtime_release_tag"], "--runtime-commit", code["runtime_release_commit"]])
    assert rc == 0 and json.loads(fresh.read_text()) == modern.data
    assert '"total_runs": 600' in capsys.readouterr().out


# =========================================================================== #
# 1. one model at a time
# =========================================================================== #


def test_launch_runs_only_the_named_models_phase_one_model_at_a_time(modern, tmp_path, server):
    m = make_modern(modern, tmp_path, server)
    m1_cells, m2_cells = m.cells("M1"), m.cells("M2")
    assert m.phases == ["M1", "M2"] and [c.model for c in m1_cells + m2_cells] == [M1, M1, M2, M2]
    server.install_pinned(m, "M1")
    with running_app(m.db_path(), declared_factory()) as (_app, api):
        for phase in ("A", "B", "all", "M9"):
            with pytest.raises(CampaignStop, match="launches one model's phase at a time"):
                launch(m, api, phase)
        assert not m.ledger_path().exists()  # refused before the ledger (the frozen plan) exists
        assert api.posts == []

        assert launch(m, api, "M1") == {"submitted": 2, "paused": False, "drained": 0, "skipped": 0, "succeeded": 2}
        assert api.posts == [m.job_body(c) for c in m1_cells]
        assert all(p["model"] == M1 and f":M1:{M1}|" in p["name"] for p in api.posts)
        # a finished phase is a no-op while its model is still installed: nothing is re-run
        assert launch(m, api, "M1") == {"submitted": 0, "paused": False, "drained": 0, "skipped": 2, "succeeded": 0}
        # the next phase's model is not installed: refused in preflight, never substituted
        with pytest.raises(CampaignStop, match=r"target gpt-oss:20b \(M2\) is not installed"):
            launch(m, api, "M2")
        assert len(api.posts) == 2 and api.violations == []
    assert {model for model, _keep in server.generates} == {M1}  # only the target was ever loaded

    ledger = load_ledger(m)
    assert [(l["phase"], l["model"]) for l in ledger.data["launches"]] == [("M1", M1), ("M1", M1)]
    assert ledger.data["events"][-1]["type"] == "preflight_failed"
    for cell in m1_cells:
        entry = ledger.active_entry(cell.key)
        task = m.task_by_id[cell.task_id]
        assert entry["state"] == SUCCEEDED and entry["phase"] == "M1"
        assert entry["campaign_id"] == m.campaign_id and entry["logical_name"] == "Qwen 3.5 9B"
        assert (entry["task_version"], entry["task_digest"]) == (task["task_version"], task["task_digest"])
        assert entry["backend_kind"] == "ollama" and entry["generation"] == m.generation
        assert entry["expected_runs"] == 2
        assert entry["model_digest_at_submit"] == entry["model_digest_at_finalize"] == pin(m, "M1")
        assert entry["ollama_version_at_submit"] == entry["ollama_version_at_finalize"] == PINNED_VERSION
    assert all(ledger.active_entry(c.key) is None for c in m2_cells)
    with closing(cohort.open_readonly(m.db_path())) as conn:
        assert [r[0] for r in conn.execute("SELECT DISTINCT agent FROM runs")] == [M1]
        assert conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 4

    assert validate_mod.validate_campaign(m, phase="M1")["complete"] is True
    m2 = validate_mod.validate_campaign(m, phase="M2")
    assert m2["complete"] is False and m2["missing"]["cells"] == [c.key for c in m2_cells]
    everything = validate_mod.validate_campaign(m)
    assert everything["complete"] is False and everything["expected"]["runs"] == 8
    assert everything["present"]["runs"] == 4
    assert {p: s["state"] for p, s in everything["cohort"]["models"].items()} == {"M1": "COMPLETE",
                                                                                  "M2": "NOT_STARTED"}
    assert everything["cohort"]["ranked_models"] == [M1]
    assert everything["cohort"]["minimum_runs"] == 8
    assert [(p, s["ranked"]) for p, s in everything["cohort"]["models"].items()] == [("M1", True), ("M2", False)]
    # the derived plan inherits the committed cohort floor: 1 complete model < 3
    assert everything["cohort"]["minimum_ranked_models"] == 3 and everything["cohort"]["meets_minimum"] is False
    assert {p: s["state"] for p, s in status_mod.campaign_status(m)["models"].items()} == {
        "M1": "COMPLETE", "M2": "NOT_STARTED"}


# =========================================================================== #
# 10. the target digest is the frozen PIN, before and after every batch
# =========================================================================== #


def test_preflight_requires_exactly_the_pinned_digest_of_the_phase_target(modern, tmp_path, server):
    m = make_modern(modern, tmp_path, server)
    server.install_pinned(m, "M1", digest=STALE)  # the tag moved upstream: same name, other weights
    with running_app(m.db_path(), declared_factory()) as (_app, api):
        with pytest.raises(CampaignStop, match=rf"STOP - qwen3.5:9b is installed with digest {STALE}, the frozen "
                                               rf"plan pins {pin(m, 'M1')}"):
            launch(m, api, "M1")  # the FIRST launch: there is no earlier launch to compare with
        assert api.posts == []
    assert not m.ledger_path().exists()

    assert any("one model at a time: name the phase" in p
               for p in launcher.preflight(m, None, check_code=False).problems)
    assert any("unknown phase 'M9'" in p for p in launcher.preflight(m, None, check_code=False, phase="M9").problems)
    server.install_pinned(m, "M1")
    pf = launcher.preflight(m, None, check_code=False, phase="M1")
    assert pf.ok, pf.problems
    assert pf.facts["target"] == {"phase": "M1", "model": M1, "logical_name": "Qwen 3.5 9B"}
    server.install_pinned(m, "M2", digest=STALE)  # another target installed: only disclosed
    pf = launcher.preflight(m, None, check_code=False, phase="M1")
    assert pf.ok and any("other campaign targets are installed too (gpt-oss:20b)" in w for w in pf.warnings)
    assert any("installed with digest" in p for p in launcher.preflight(m, None, check_code=False,
                                                                        phase="M2").problems)


def test_a_digest_moving_away_from_the_pin_halts_before_the_next_submission(modern, tmp_path, server):
    m = make_modern(modern, tmp_path, server, models=(M1,))
    first, second = m.cells("M1")
    server.install_pinned(m, "M1")
    # health call 1 = preflight, 2 = before the first submission, 3 = before the second
    with hooked_app(m.db_path(), declared_factory(),
                    before_health={3: lambda: server.set_digest(M1, STALE)}) as (_app, api):
        with pytest.raises(CampaignStop, match=rf"qwen3.5:9b: Ollama digest {STALE} differs"):
            launch(m, api, "M1")
        assert len(api.posts) == 1
    ledger = load_ledger(m)
    assert ledger.active_entry(first.key)["state"] == SUCCEEDED
    assert ledger.active_entry(second.key) is None
    assert ledger.data["events"][-1]["type"] == "halt"


def test_a_digest_moving_during_an_evaluation_is_rejected_at_finalize(modern, tmp_path, server):
    m = make_modern(modern, tmp_path, server, models=(M1,), tasks=(TASK,))
    server.install_pinned(m, "M1")
    with running_app(m.db_path(), flipping_factory(server, M1, STALE)) as (_app, api):
        with pytest.raises(CampaignStop, match="model identity not proven"):
            launch(m, api, "M1")
    entry = load_ledger(m).active_entry(m.cells()[0].key)
    assert entry["state"] == REJECTED
    assert (entry["model_digest_at_submit"], entry["model_digest_at_finalize"]) == (pin(m, "M1"), STALE)
    receipt = validate_mod.validate_campaign(m, phase="M1")
    assert receipt["complete"] is False and receipt["present"]["runs"] == 0
    with pytest.raises(CampaignStop, match="does not validate complete"):
        model_receipt(m, "M1")


def test_the_validator_measures_identity_against_the_pin_not_the_first_launch(modern, tmp_path, server):
    m = make_modern(modern, tmp_path, server, models=(M1,), tasks=(TASK,))
    complete(m, server, "M1")
    ledger = load_ledger(m)
    assert launcher.reference_digests(ledger, m) == m.pinned_digests() == {M1: pin(m, "M1")}
    # as if another build had run the whole batch consistently, first launch included
    for entry in ledger.entries:
        entry.update(model_digest_at_submit=STALE, model_digest_at_finalize=STALE)
    for record in ledger.data["launches"]:
        record["inventory"]["models"][M1]["digest"] = STALE
    ledger.save()
    ledger = load_ledger(m)
    assert launcher.reference_digests(ledger) == {M1: STALE}  # the historical first-launch rule would agree
    assert launcher.reference_digests(ledger, m) == {M1: pin(m, "M1")}
    receipt = validate_mod.validate_campaign(m, phase="M1")
    assert receipt["complete"] is False
    assert any("model identity not proven" in p and pin(m, "M1") in p for p in receipt["problems"])
    assert status_mod.campaign_status(m)["models"]["M1"]["state"] != "COMPLETE"
    with pytest.raises(CampaignStop, match="does not validate complete"):
        model_receipt(m, "M1")


def test_a_stale_build_seen_at_the_first_launch_never_blocks_the_pinned_target_later(modern, tmp_path, server):
    # was a PRODUCT BUG (fixed in 4432f3f): a sequential plan compared every roster model's digest with the
    # campaign's FIRST launch; its reference is the frozen PIN, so the first-launch digest loop no longer applies
    m = make_modern(modern, tmp_path, server)
    server.install_pinned(m, "M1")
    server.install_pinned(m, "M2", digest=STALE)  # an older gpt-oss:20b build the operator had installed
    pf = launcher.preflight(m, None, check_code=False, phase="M1")
    assert pf.ok, pf.problems
    assert any(f"gpt-oss:20b is installed with a NON-PINNED digest {STALE}" in w for w in pf.warnings)
    with running_app(m.db_path(), declared_factory()) as (_app, api):
        assert launch(m, api, "M1", max_evaluations=0)["paused"] is True
    assert load_ledger(m).data["launches"][0]["inventory"]["models"][M2]["digest"] == STALE
    # the tooling never overwrites nor removes an unfinished target (pull/remove refuse it), so the
    # operator replaces the stale build by hand; now exactly the pinned build is installed
    server.remove(M2)
    server.install_pinned(m, "M2")
    pf = launcher.preflight(m, None, ledger=load_ledger(m), check_code=False, phase="M2")
    assert pf.ok, pf.problems


# =========================================================================== #
# 11. the plan (and its roster) is frozen once the ledger exists
# =========================================================================== #


def _edit_m2_pin(data):
    data["roster"][1]["expected_identity"]["digest"] = "1" * 64


def _edit_m2_optional(data):
    data["roster"][1]["optional"] = True


def _edit_m1_size(data):
    data["roster"][0]["expected_identity"]["download_bytes"] += 1


def _edit_m1_name(data):
    data["roster"][0]["logical_name"] = "Qwen 3.5 9B (renamed)"


def _edit_temperature(data):
    data["generation"]["temperature"] = 0.2


def _edit_smoke(data):
    data["execution"]["smoke"]["tasks"] = [TASK]


@pytest.mark.parametrize("edit", [_edit_m2_pin, _edit_m2_optional, _edit_m1_size, _edit_m1_name, _edit_temperature,
                                  _edit_smoke], ids=lambda f: f.__name__[6:])
def test_the_plan_and_its_roster_are_frozen_once_the_ledger_exists(modern, tmp_path, server, edit):
    m = make_modern(modern, tmp_path, server)
    server.install_pinned(m, "M1")
    server.install(OTHER, "1" * 64)
    with running_app(m.db_path(), declared_factory()) as (_app, api):
        assert launch(m, api, "M1", max_evaluations=0)["paused"] is True
        data = copy.deepcopy(m.data)
        edit(data)
        data["expected"] = expected_counts(data)
        edited = Manifest(data)  # a valid plan on its own
        assert edited.sha256 != m.sha256
        for phase in ("M1", "M2"):
            with pytest.raises(LedgerError, match="manifest changed after the ledger was created"):
                launch(edited, api, phase)
        assert api.posts == []
    receipt = validate_mod.validate_campaign(edited)
    assert receipt["complete"] is False and any("manifest changed" in p for p in receipt["problems"])
    for action in (lambda: pull_model(edited, "M1"),
                   lambda: classify_model(edited, "M2", "NOT_BENCHMARKED", "skipped", "operator decision"),
                   lambda: remove_model(edited, OTHER, "free space")):
        with pytest.raises(LedgerError, match="manifest changed"):
            action()
    with pytest.raises(CampaignStop):
        model_receipt(edited, "M1")
    assert server.pulls == [] and server.deletes == [] and OTHER in server.models
    ledger = load_ledger(m)
    assert not ledger.data.get("model_status") and not ledger.data.get("model_deletions")
    assert not any("manifest changed" in p for p in validate_mod.validate_campaign(m)["problems"])


# =========================================================================== #
# 2 / 3. install: reuse, one target at a time, space, activity, pinned digest
# =========================================================================== #


def _never_pull(*_args):
    raise AssertionError("nothing may be downloaded here")


def test_pull_reuses_an_installed_target_with_the_pinned_digest(modern, tmp_path, server, disk):
    m = make_modern(modern, tmp_path, server)
    server.install_pinned(m, "M1")
    free = disk.free
    logs: list[str] = []
    record = pull_model(m, "M1", pull=_never_pull, log=logs.append)
    assert record["outcome"] == "reused" and record["digest"] == pin(m, "M1")
    assert record["bytes"] == download_bytes(m, "M1") and record["phase"] == "M1"
    assert server.pulls == [] and disk.free == free
    assert ("POST", "/api/pull") not in server.requests
    assert load_ledger(m).data["model_pulls"] == [record]
    assert any("reused, not downloaded" in line for line in logs)


def test_pull_refuses_a_target_installed_with_another_digest(modern, tmp_path, server):
    m = make_modern(modern, tmp_path, server)
    server.install_pinned(m, "M1", digest=STALE)
    with pytest.raises(CampaignStop, match=rf"STOP - qwen3.5:9b is installed with digest {STALE}, the frozen plan "
                                           rf"pins {pin(m, 'M1')}"):
        pull_model(m, "M1", pull=_never_pull)
    assert server.pulls == [] and server.deletes == []
    assert server.models[M1]["digest"] == STALE  # never overwritten blindly
    ledger = ledger_or_none(m)
    assert not (ledger and ledger.data.get("model_pulls"))
    assert storage_log_lines(m) == []


def test_pull_downloads_only_the_target_logs_first_and_checks_the_pin(modern, tmp_path, server, disk):
    m = make_modern(modern, tmp_path, server)
    server.serve(m, "M1")
    server.serve(m, "M2")
    free, size = disk.free, download_bytes(m, "M1")
    seen: dict = {}
    real_stream = lifecycle._pull_stream  # the guarded real streaming client

    def recording_stream(base_url, model, log):
        seen["log"] = storage_log_lines(m)
        seen["ledger"] = json.loads(m.ledger_path().read_text()) if m.ledger_path().exists() else None
        seen["installed"] = model in server.models
        return real_stream(base_url, model, log)

    logs: list[str] = []
    record = pull_model(m, "M1", pull=recording_stream, log=logs.append)
    # the audit record is on disk BEFORE the download starts
    assert seen["installed"] is False
    assert len(seen["log"]) == 1 and seen["log"][0]["action"] == "pull-model"
    assert {k: seen["log"][0][k] for k in ("phase", "model", "pinned_digest", "download_bytes", "free_bytes_before")} \
        == {"phase": "M1", "model": M1, "pinned_digest": pin(m, "M1"), "download_bytes": size,
            "free_bytes_before": free}
    if seen["ledger"] is not None:
        assert seen["ledger"]["events"][-1]["type"] == "model_pull_started"
    assert server.pulls == [M1]  # only the phase's target
    assert record["outcome"] == "pulled" and record["digest"] == record["pinned_digest"] == pin(m, "M1")
    assert record["bytes"] == size and record["free_bytes_before"] == free
    assert record["free_bytes_after"] == free - size and record["ollama_version"] == server.version
    lines = storage_log_lines(m)
    assert [line["action"] for line in lines] == ["pull-model", "pull-model-result"]
    assert lines[1]["outcome"] == "pulled" and lines[1]["digest"] == pin(m, "M1")
    assert load_ledger(m).data["model_pulls"][-1] == record
    assert any("pull complete" in line for line in logs)
    # the default streaming path (no pull=) reaches the same fake
    record = pull_model(m, "M1")
    assert record["outcome"] == "reused" and server.pulls == [M1]


def test_pull_refuses_while_another_unfinished_target_is_installed(modern, tmp_path, server):
    m = make_modern(modern, tmp_path, server)
    server.install_pinned(m, "M1")
    server.serve(m, "M2")
    with pytest.raises(CampaignStop, match=r"one target at a time: qwen3.5:9b is installed and its batch is not "
                                           r"finished"):
        pull_model(m, "M2")
    assert server.pulls == [] and storage_log_lines(m) == []
    # a classified model's weights are no longer needed: it does not block the next target
    classify_model(m, "M1", "LOCAL_RESOURCE_LIMIT", "swaps heavily at 9.7B on this machine",
                   "smoke memory pressure: critical")
    assert pull_model(m, "M2")["outcome"] == "pulled" and server.pulls == [M2]


def test_pull_refuses_without_space_for_the_download_and_its_margin(modern, tmp_path, server, disk):
    m = make_modern(modern, tmp_path, server)
    server.serve(m, "M1")
    assert PULL_MARGIN_BYTES == 4 * GIB
    need = download_bytes(m, "M1") + PULL_MARGIN_BYTES
    disk.free = need - 1
    with pytest.raises(CampaignStop, match=r"qwen3.5:9b needs 10\.1 GiB free .*remove-model"):
        pull_model(m, "M1")
    assert server.pulls == [] and storage_log_lines(m) == []
    disk.free = need  # exactly the download plus the margin is enough
    assert pull_model(m, "M1")["outcome"] == "pulled"
    assert disk.free == PULL_MARGIN_BYTES


@pytest.mark.parametrize("source", ["database", "ledger", "app"])
def test_pull_refuses_while_any_evaluation_is_active(modern, tmp_path, server, source):
    m = make_modern(modern, tmp_path, server)
    server.serve(m, "M1")
    client = None
    if source == "database":
        busy = foreign_evaluation(m, m.cells("M2")[0])
    elif source == "ledger":
        add_in_flight(m, m.cells("M2")[0])
        busy = f"ledger:{m.cells('M2')[0].key}"
    else:
        busy = "e-running"
        client = BusyApp([{"id": busy, "status": "running"}, {"id": "e-done", "status": "succeeded"}])
    with pytest.raises(CampaignStop, match=rf"evaluations are active \(\[{re.escape(repr(busy))}\]\)"):
        pull_model(m, "M1", client=client)
    assert server.pulls == [] and storage_log_lines(m) == []


def test_a_pulled_digest_other_than_the_pin_is_an_identity_mismatch_stop(modern, tmp_path, server):
    m = make_modern(modern, tmp_path, server)
    server.serve(m, "M1", digest=STALE)  # the registry tag moved after the plan was frozen
    with pytest.raises(CampaignStop, match=rf"STOP - pulled qwen3.5:9b has digest {STALE}, the frozen plan pins "
                                           rf"{pin(m, 'M1')}"):
        pull_model(m, "M1")
    assert server.pulls == [M1]
    record = load_ledger(m).data["model_pulls"][-1]
    assert record["outcome"] == "IDENTITY MISMATCH"
    assert (record["digest"], record["pinned_digest"]) == (STALE, pin(m, "M1"))
    lines = storage_log_lines(m)
    assert [line["action"] for line in lines] == ["pull-model", "pull-model-result"]
    assert lines[-1]["outcome"] == "IDENTITY MISMATCH"
    # the mismatched build is never benchmarked, nor "reused" by a second pull
    with running_app(m.db_path(), declared_factory()) as (_app, api):
        with pytest.raises(CampaignStop, match=rf"STOP - qwen3.5:9b is installed with digest {STALE}"):
            launch(m, api, "M1")
        assert api.posts == []
    with pytest.raises(CampaignStop, match="installed with digest"):
        pull_model(m, "M1")
    assert server.pulls == [M1]


def test_a_refused_pull_leaves_no_ledger_behind(modern, tmp_path, server, disk, monkeypatch):
    # was a PRODUCT BUG (fixed in cfa9025): a refused pull created the ledger (froze the plan)
    m = make_modern(modern, tmp_path, server)
    server.serve(m, "M1")
    refusals = []

    def refused(match: str, **kw) -> None:
        with pytest.raises(CampaignStop, match=match):
            pull_model(m, "M1", **kw)
        refusals.append(match)
        assert server.pulls == [] and storage_log_lines(m) == []
        assert not m.ledger_path().exists(), f"refused ({match}) but the ledger was created"

    disk.free = GIB
    refused(r"qwen3.5:9b needs 10\.1 GiB free")
    disk.free = 400 * GIB
    server.install_pinned(m, "M2")  # another unfinished target, with its pinned weights
    refused(r"one target at a time: gpt-oss:20b is installed")
    server.remove(M2)
    refused(r"evaluations are active \(\['e-running'\]\)", client=BusyApp([{"id": "e-running", "status": "running"}]))
    missing = tmp_path / "no-such-models-dir"
    monkeypatch.setenv("OLLAMA_MODELS", str(missing))
    refused(r"Ollama models directory .*no-such-models-dir does not exist")
    assert not missing.exists()
    monkeypatch.setenv("OLLAMA_MODELS", str(tmp_path / "ollama-models"))
    busy = foreign_evaluation(m, m.cells("M2")[0])
    refused(rf"evaluations are active \(\['{busy}'\]\)")
    server.version = OTHER_VERSION
    refused(rf"Ollama server version is '{OTHER_VERSION}', the frozen plan pins '{PINNED_VERSION}': pull-model refused")
    server.version = PINNED_VERSION
    server.stop()
    refused(r"Ollama is not reachable .*pull-model needs it")
    assert len(refusals) == 7


def test_a_failed_download_is_recorded_and_refused(modern, tmp_path, server, disk):
    m = make_modern(modern, tmp_path, server)
    free = disk.free  # the registry does not serve the tag: the stream reports an error
    with pytest.raises(CampaignStop, match=r"pull of qwen3.5:9b failed: .*file does not exist"):
        pull_model(m, "M1")
    assert server.pulls == [M1] and M1 not in server.models and disk.free == free
    pulls = load_ledger(m).data["model_pulls"]
    assert [(p["phase"], p["model"], p["outcome"]) for p in pulls] == [("M1", M1, "failed")]
    assert "file does not exist" in pulls[0]["error"] and pulls[0]["free_bytes_after"] == free
    lines = storage_log_lines(m)
    assert [line["action"] for line in lines] == ["pull-model", "pull-model-result"]
    assert lines[1]["outcome"] == "failed" and lines[1]["model"] == M1
    # nothing was installed, so the launch is still refused in preflight
    assert any("is not installed" in p for p in launcher.preflight(m, None, ledger=load_ledger(m), check_code=False,
                                                                    phase="M1").problems)


# =========================================================================== #
# 4. safe removal bookkeeping
# =========================================================================== #


def test_removing_a_non_campaign_model_is_logged_first_and_never_creates_the_ledger(modern, tmp_path, server, disk):
    m = make_modern(modern, tmp_path, server)
    server.install(OTHER, "1" * 64, size=2 * GIB)
    server.loaded.add(OTHER)
    free = disk.free
    deleted: list[str] = []

    def delete(name):
        last = storage_log_lines(m)[-1]
        assert (last["action"], last["model"], last["outcome"]) == ("remove-model", name, "requested")
        assert last["free_bytes_before"] == free and last["size_bytes"] == 2 * GIB
        assert last["reason"] == "free space for the campaign" and last["digest"] == "1" * 64
        assert name not in server.loaded  # unloaded through Ollama first
        assert not m.ledger_path().exists()
        deleted.append(name)
        server.remove(name)

    record = remove_model(m, OTHER, "  free space for the campaign  ", delete=delete)
    assert deleted == [OTHER] and OTHER not in server.models and server.unloads == [OTHER]
    assert record["outcome"] == "removed" and record["reason"] == "free space for the campaign"
    assert record["evidence_status"].startswith("not a campaign model") and record["campaign_target"] is None
    assert (record["digest"], record["size_bytes"], record["runtime"]) == ("1" * 64, 2 * GIB, "ollama")
    assert record["free_bytes_before"] == free and record["free_bytes_after"] == free + 2 * GIB
    assert record["reclaimed_bytes"] == 2 * GIB and record["completed_at"]
    lines = storage_log_lines(m)
    assert [line["action"] for line in lines] == ["remove-model", "remove-model-result"]
    assert lines[1]["outcome"] == "removed" and lines[1]["reclaimed_bytes"] == 2 * GIB
    assert not m.ledger_path().exists()  # a removal never creates the ledger (the frozen plan)


def test_a_removal_is_in_the_ledger_before_the_weights_are_removed(modern, tmp_path, server, disk):
    m = make_modern(modern, tmp_path, server)
    server.install_pinned(m, "M2")
    server.install(OTHER, "1" * 64, size=GIB)
    classify_model(m, "M2", "LOCAL_RUNTIME_UNSUPPORTED", "the runner rejects its MXFP4 tensors",
                   "smoke app.log: unsupported tensor type")

    def delete(name):
        last = json.loads(m.ledger_path().read_text())["model_deletions"][-1]
        assert (last["model"], last["outcome"]) == (name, "requested")
        assert storage_log_lines(m)[-1]["action"] == "remove-model"
        server.remove(name)

    first = remove_model(m, M2, "classified: its weights are not needed", delete=delete)
    assert first["evidence_status"] == "classified LOCAL_RUNTIME_UNSUPPORTED" and first["campaign_target"] == "M2"
    second = remove_model(m, OTHER, "free space")  # the default path: DELETE /api/delete
    assert server.deletes == [OTHER] and second["outcome"] == "removed"
    ledger = load_ledger(m)
    deletions = ledger.data["model_deletions"]
    assert [(d["model"], d["outcome"]) for d in deletions] == [(M2, "removed"), (OTHER, "removed")]
    assert deletions[0]["reclaimed_bytes"] == download_bytes(m, "M2")
    assert [e["type"] for e in ledger.data["events"]].count("model_deletion") == 2


def test_remove_model_refusals_leave_everything_in_place(modern, tmp_path, server):
    m = make_modern(modern, tmp_path, server)
    server.install_pinned(m, "M1")
    server.install(OTHER, "1" * 64)
    with pytest.raises(LedgerError, match="written reason"):
        remove_model(m, OTHER, "   ")
    with pytest.raises(CampaignStop, match="mistral:7b is not installed"):
        remove_model(m, "mistral:7b", "free space")
    with pytest.raises(CampaignStop, match=r"qwen3.5:9b is campaign target M1 and its evidence is not frozen yet"):
        remove_model(m, M1, "free space")  # no ledger: nothing was ever frozen
    server.loaded.add(OTHER)
    server.sticky.add(OTHER)
    with pytest.raises(CampaignStop, match="still loaded"):
        remove_model(m, OTHER, "free space")
    assert server.deletes == [] and set(server.models) == {M1, OTHER}
    assert storage_log_lines(m) == []
    assert not m.ledger_path().exists()


def test_a_roster_model_with_non_pinned_weights_is_removable_and_never_blocks_the_next_pull(modern, tmp_path,
                                                                                            server, disk):
    m = make_modern(modern, tmp_path, server)
    server.install_pinned(m, "M2", digest=STALE)  # the tag's weights are NOT the pinned identity
    server.serve(m, "M1")
    # those weights can never become campaign evidence: they are not an 'unfinished target'
    assert pull_model(m, "M1")["outcome"] == "pulled" and server.pulls == [M1]
    pf = launcher.preflight(m, None, ledger=load_ledger(m), check_code=False, phase="M1")
    assert pf.ok, pf.problems
    assert any(f"gpt-oss:20b is installed with a NON-PINNED digest {STALE}" in w for w in pf.warnings)
    free = disk.free
    record = remove_model(m, M2, "not the pinned build; pull the pinned one later")
    assert record["outcome"] == "removed" and M2 not in server.models and server.deletes == [M2]
    assert record["campaign_target"] == "M2" and record["digest"] == STALE
    assert record["evidence_status"] == (f"campaign target M2 installed with NON-PINNED weights {STALE} (pin "
                                         f"{pin(m, 'M2')}): never campaign evidence")
    assert record["reclaimed_bytes"] == download_bytes(m, "M2") and disk.free == free + download_bytes(m, "M2")
    assert [d["outcome"] for d in load_ledger(m).data["model_deletions"]] == ["removed"]
    assert [line["action"] for line in storage_log_lines(m)] == [
        "pull-model", "pull-model-result", "remove-model", "remove-model-result"]
    assert storage_log_lines(m)[2]["evidence_status"] == record["evidence_status"]
    # the PINNED target is different: unfinished, it is never removed (also spelled 'sha256:<pin>')
    server.set_digest(M1, "sha256:" + pin(m, "M1"))
    with pytest.raises(CampaignStop, match=r"qwen3.5:9b is campaign target M1 and its evidence is not frozen yet"):
        remove_model(m, M1, "free space")
    assert M1 in server.models and server.deletes == [M2]


def test_remove_model_never_calls_a_historical_plans_own_model_a_non_campaign_model(base, tmp_path, server):
    # was a PRODUCT BUG (fixed in 4432f3f): remove_model had no plan-kind check, so every model of a
    # historical plan (no roster) was removed as 'not a campaign model'
    model = "qwen2.5-coder:3b"
    data = derive_subset(base.data, campaign_id="t-hist", models=[model], task_ids=[TASK], repetitions=1,
                         campaign_db=str(tmp_path / "h.sqlite"), runtime_dir=str(tmp_path / "h-rt"), purpose="test")
    data["backend"] = {**data["backend"], "base_url": server.url}
    m = Manifest(data)
    assert not m.is_sequential and model in m.models
    server.install(model, "3" * 64)
    with pytest.raises(CampaignStop, match="remove-model applies only to a sequential-local campaign plan .*this "
                                           "plan is historical-replication"):
        remove_model(m, model, "free space")
    assert server.deletes == [] and model in server.models and server.requests == []
    assert not m.ledger_path().exists() and storage_log_lines(m) == []


def test_model_files_are_never_managed_under_a_smoke_plan(modern, tmp_path, server):
    """A smoke's scratch plan lists only the smoked model: under it every other campaign target would look
    like 'not a campaign model'. Derived test plans (no smoke_of) are allowed (every other test here)."""
    m = make_modern(modern, tmp_path, server)
    data = derive_subset(m.data, campaign_id="t-modern-smoke-M1", models=[M1], task_ids=[TASK], repetitions=1,
                         campaign_db=str(tmp_path / "s.sqlite"), runtime_dir=str(tmp_path / "s-rt"),
                         api_url=closed_api(), purpose="operational smoke (NOT campaign evidence)")
    data["smoke_of"] = m.campaign_id
    smoke = Manifest(data)
    assert smoke.is_sequential and smoke.models == [M1]
    server.install_pinned(m, "M1")
    server.install_pinned(m, "M2")  # a campaign target the smoke plan does not list
    server.serve(m, "M1")

    def no_app(*_args):
        raise AssertionError("no smoke of a smoke plan")

    for what, action in (("pull-model", lambda: pull_model(smoke, "M1", pull=_never_pull)),
                         ("remove-model", lambda: remove_model(smoke, M2, "free space")),
                         ("classify-model", lambda: classify_model(smoke, "M1", "NOT_BENCHMARKED", "r", "e")),
                         ("smoke", lambda: run_smoke(smoke, "M1", port=free_port(), tasks=[TASK], start_app=no_app))):
        with pytest.raises(CampaignStop, match=rf"^{what} applies only to a sequential-local campaign plan .*this "
                                               "plan is a smoke plan$"):
            action()
    assert server.pulls == [] and server.deletes == [] and set(server.models) == {M1, M2}
    assert not smoke.ledger_path().exists() and not m.ledger_path().exists()
    assert not smoke.runtime_subdir("smoke_dir").exists() and storage_log_lines(smoke) == []


# =========================================================================== #
# 5 / 6 / 9. receipt before removal; no rerun after removal; evidence untouched
# =========================================================================== #


def test_one_model_at_a_time_lifecycle_receipt_removal_and_next_model(modern, tmp_path, server, disk):
    m = make_modern(modern, tmp_path, server, minimum_ranked=2)
    server.serve(m, "M1")
    server.serve(m, "M2")
    assert pull_model(m, "M1")["outcome"] == "pulled" and server.pulls == [M1]
    with pytest.raises(CampaignStop, match="one target at a time: qwen3.5:9b"):
        pull_model(m, "M2")
    with running_app(m.db_path(), declared_factory()) as (_app, api):
        assert launch(m, api, "M1")["submitted"] == 2
    assert validate_mod.validate_campaign(m, phase="M1")["complete"] is True

    # 5. the weights stay until the receipt is frozen
    with pytest.raises(CampaignStop, match="evidence is not frozen yet"):
        remove_model(m, M1, "make room for gpt-oss:20b")
    assert server.deletes == [] and M1 in server.models
    result, target = model_receipt(m, "M1")
    ledger = load_ledger(m)
    m1_ids = [ledger.active_entry(c.key)["evaluation_id"] for c in m.cells("M1")]
    assert result["receipt_kind"] == "model" and result["phase"] == "M1" and result["model"] == M1
    assert result["expected_identity"] == m.phase_entry("M1")["expected_identity"]
    assert result["observed_identity"]["digests"] == [pin(m, "M1")]
    assert result["observed_identity"]["digest_matches_pin"] is True
    assert result["observed_identity"]["ollama_versions"] == [server.version]
    assert (result["tasks"], result["expected_runs"], result["accepted_runs"]) == (2, 4, 4)
    assert result["evaluation_ids"] == m1_ids and result["totals"]["valid"] == 4
    assert result["validation"]["complete"] is True and result["manifest_sha256"] == m.sha256
    assert target.parent == m.runtime_subdir("receipts") and target.with_suffix(".md").exists()
    assert "4 / 4" in target.with_suffix(".md").read_text()
    assert ledger.data["receipts"]["M1"]["sha256"] == file_sha256(target)
    assert ledger.data["receipts"]["M1"]["accepted_runs"] == 4
    assert ledger.data["receipts"]["M1"]["digest"] == pin(m, "M1")

    # 9. removing the weights never touches campaign evidence
    before = evidence_snapshot(m)
    record = remove_model(m, M1, "make room for gpt-oss:20b")
    assert record["outcome"] == "removed" and server.deletes == [M1] and M1 not in server.models
    assert "re-validated complete" in record["evidence_status"] and record["campaign_target"] == "M1"
    assert record["reclaimed_bytes"] == download_bytes(m, "M1")
    assert evidence_snapshot(m) == before
    after_removal = validate_mod.validate_campaign(m, phase="M1")
    assert after_removal["complete"] is True and after_removal["present"]["runs"] == 4
    everything = validate_mod.validate_campaign(m)
    assert everything["per_model"][M1]["cells_complete"] == 2 and everything["per_model"][M1]["runs"] == 4
    assert everything["cohort"]["models"]["M1"]["state"] == "COMPLETE"
    assert everything["cohort"]["ranked_models"] == [M1] and everything["complete"] is False  # M2 pending

    # 6. the next model; M1 is never re-run
    assert pull_model(m, "M2")["outcome"] == "pulled" and server.pulls == [M1, M2]
    with running_app(m.db_path(), declared_factory()) as (_app, api):
        assert launch(m, api, "M2") == {"submitted": 2, "paused": False, "drained": 0, "skipped": 0, "succeeded": 2}
        assert [p["model"] for p in api.posts] == [M2, M2]
        # launching the finished, removed model again is refused in PREFLIGHT (its target is not installed);
        # it neither skips nor re-submits anything
        with pytest.raises(CampaignStop, match=r"preflight failed:[\s\S]*target qwen3.5:9b \(M1\) is not installed"):
            launch(m, api, "M1")
        assert len(api.posts) == 2
    ledger = load_ledger(m)
    assert [ledger.active_entry(c.key)["evaluation_id"] for c in m.cells("M1")] == m1_ids
    assert ledger.data["events"][-1]["type"] == "preflight_failed"
    assert len(evaluation_ids(m)) == 4
    everything = validate_mod.validate_campaign(m)
    assert everything["complete"] is True and everything["present"]["runs"] == 8
    assert everything["cohort"]["ranked_models"] == [M1, M2]
    assert everything["cohort"]["minimum_ranked_models"] == 2 and everything["cohort"]["meets_minimum"] is True
    assert all(info["ranked"] and info["accepted_runs"] == 4 for info in everything["cohort"]["models"].values())
    models = status_mod.campaign_status(m)["models"]
    assert models["M1"] == {"model": M1, "logical_name": "Qwen 3.5 9B", "optional": False, "state": "COMPLETE",
                            "cells_complete": 2, "cells": 2, "accepted_runs": 4,
                            "receipt": ledger.data["receipts"]["M1"]["path"], "weights_removed": True}
    assert models["M2"]["state"] == "COMPLETE" and models["M2"]["weights_removed"] is False
    assert "weights removed" in status_mod.render(status_mod.campaign_status(m))
    board = analysis.official_baseline(m)
    assert board["official"] is True and board["label"] == "OFFICIAL modern local leaderboard"
    assert sorted(e["agent"] for e in board["leaderboard"]) == sorted([M1, M2])


def test_a_tampered_or_no_longer_valid_receipt_blocks_the_removal(modern, tmp_path, server):
    m = make_modern(modern, tmp_path, server, tasks=(TASK,))
    complete(m, server, "M1")
    _result, target = model_receipt(m, "M1")
    frozen = target.read_bytes()
    assert lifecycle.phase_finished(m, load_ledger(m), "M1")
    target.write_bytes(frozen + b" ")
    with pytest.raises(CampaignStop, match="evidence is not frozen yet"):
        remove_model(m, M1, "free space")
    target.unlink()
    with pytest.raises(CampaignStop, match="evidence is not frozen yet"):
        remove_model(m, M1, "free space")
    target.write_bytes(frozen)
    assert lifecycle.phase_finished(m, load_ledger(m), "M1")
    # the receipt file is intact, but the evidence no longer re-validates (an evaluation named for the
    # campaign that the ledger does not own appeared in the database)
    create_directly(m, m.job_body(m.cells("M1")[0]))
    assert validate_mod.validate_campaign(m, phase="M1")["complete"] is False
    assert lifecycle.phase_finished(m, load_ledger(m), "M1") is None
    with pytest.raises(CampaignStop, match="evidence is not frozen yet"):
        remove_model(m, M1, "free space")
    assert server.deletes == [] and M1 in server.models
    assert not any(line["action"] == "remove-model" for line in storage_log_lines(m))
    assert not load_ledger(m).data.get("model_deletions")


def test_removing_a_finished_target_is_refused_while_any_evaluation_is_active(modern, tmp_path, server):
    m = make_modern(modern, tmp_path, server, tasks=(TASK,))
    complete(m, server, "M1")
    model_receipt(m, "M1")
    other_cell = m.cells("M2")[0]
    add_in_flight(m, other_cell)
    with pytest.raises(CampaignStop, match=r"evaluations are active .*ledger:gpt-oss:20b"):
        remove_model(m, M1, "free space")
    drop_in_flight(m, other_cell.key)
    with pytest.raises(CampaignStop, match=r"evaluations are active \(\['e-queued'\]\)"):
        remove_model(m, M1, "free space", client=BusyApp([{"id": "e-queued", "status": "queued"}]))
    foreign = foreign_evaluation(m, other_cell)
    assert lifecycle.phase_finished(m, load_ledger(m), "M1")  # still frozen: only the activity refuses
    with pytest.raises(CampaignStop, match=rf"evaluations are active \(\['{foreign}'\]\)"):
        remove_model(m, M1, "free space")
    assert server.deletes == [] and M1 in server.models
    assert not any(line["action"] == "remove-model" for line in storage_log_lines(m))
    assert not load_ledger(m).data.get("model_deletions")


def test_a_model_receipt_is_refused_until_the_phase_validates_complete(modern, tmp_path, server):
    m = make_modern(modern, tmp_path, server)
    server.install_pinned(m, "M1")
    with pytest.raises(CampaignStop, match="does not validate complete"):
        model_receipt(m, "M1")  # nothing launched
    with running_app(m.db_path(), declared_factory()) as (_app, api):
        assert launch(m, api, "M1", max_evaluations=1)["paused"] is True
    with pytest.raises(CampaignStop, match=r"qwen3.5:9b \(M1\) does not validate complete"):
        model_receipt(m, "M1")
    assert not list(m.runtime_subdir("receipts").glob("*"))
    assert not load_ledger(m).data.get("receipts")


# =========================================================================== #
# 7. classification; the optional model
# =========================================================================== #


def test_classification_requires_a_known_status_a_reason_and_evidence(modern, tmp_path, server):
    m = make_modern(modern, tmp_path, server)
    for status, reason, evidence, message in (
            ("TOO_BIG", "does not fit", "inventory", "unknown model classification"),
            ("LOCAL_RESOURCE_LIMIT", "  ", "inventory", "reason AND supporting evidence"),
            ("LOCAL_RESOURCE_LIMIT", "does not fit", "", "reason AND supporting evidence")):
        with pytest.raises(LedgerError, match=message):
            classify_model(m, "M2", status, reason, evidence)
    ledger = ledger_or_none(m)
    assert not (ledger and ledger.data.get("model_status"))
    record = classify_model(m, "M2", "LOCAL_RESOURCE_LIMIT", " 13.8 GB of weights, 12 GB free ", " inventory.json ")
    assert (record["phase"], record["model"], record["status"]) == ("M2", M2, "LOCAL_RESOURCE_LIMIT")
    assert (record["reason"], record["evidence"]) == ("13.8 GB of weights, 12 GB free", "inventory.json")
    with pytest.raises(LedgerError, match="already classified LOCAL_RESOURCE_LIMIT"):
        classify_model(m, "M2", "NOT_BENCHMARKED", "changed my mind", "none")
    ledger = load_ledger(m)
    assert ledger.data["model_status"] == {"M2": record}
    assert ledger.data["events"][-1]["type"] == "model_classified"


def test_a_refused_classification_leaves_no_ledger_behind(modern, tmp_path, server, capsys):
    m = make_modern(modern, tmp_path, server)
    run_cli = cli_runner(m, tmp_path, capsys)
    rc, _, err = run_cli("classify-model", "--phase", "M2", "--status", "LOCAL_RESOURCE_LIMIT", "--reason", " ",
                         "--evidence", "inventories/start.json")
    assert rc == 3 and "reason AND supporting evidence" in err
    assert not m.ledger_path().exists(), "a refused classification created the ledger (froze the plan)"


def test_a_classified_model_leaves_the_expected_cohort_and_is_never_launched_or_pulled(modern, tmp_path, server):
    m = make_modern(modern, tmp_path, server, minimum_ranked=1)  # the subject is exclusion, not the cohort floor
    complete(m, server, "M1")
    before = validate_mod.validate_campaign(m)
    assert before["complete"] is False and before["expected"]["cells"] == 4
    classify_model(m, "M2", "LOCAL_RESOURCE_LIMIT", "13.8 GB does not fit beside the OS", "storage inventory")
    receipt = validate_mod.validate_campaign(m)
    assert receipt["complete"] is True, receipt["problems"]
    assert receipt["expected"]["cells"] == 2 and receipt["expected"]["runs"] == 4 and receipt["missing"]["cells"] == []
    assert list(receipt["per_model"]) == [M1]
    cohort_info = receipt["cohort"]
    assert cohort_info["ranked_models"] == [M1]
    assert cohort_info["models"]["M2"]["state"] == "LOCAL_RESOURCE_LIMIT"
    assert cohort_info["models"]["M2"]["accepted_runs"] == 0
    assert cohort_info["models"]["M2"]["classification"]["reason"] == "13.8 GB does not fit beside the OS"
    assert cohort_info["required_models_complete"] == 1 and cohort_info["required_models"] == 2
    single = validate_mod.validate_campaign(m, phase="M2")
    assert single["complete"] is False
    assert any("gpt-oss:20b (M2) is classified LOCAL_RESOURCE_LIMIT" in p for p in single["problems"])
    # a classified model is never launched, pulled or given a receipt
    server.install_pinned(m, "M2")
    with running_app(m.db_path(), declared_factory()) as (_app, api):
        with pytest.raises(CampaignStop, match=r"gpt-oss:20b \(M2\) is classified LOCAL_RESOURCE_LIMIT"):
            launch(m, api, "M2")
        assert api.posts == []
    server.remove(M2)
    server.serve(m, "M2")
    with pytest.raises(CampaignStop, match="is classified"):
        pull_model(m, "M2")
    assert server.pulls == []
    with pytest.raises(CampaignStop, match="does not validate complete"):
        model_receipt(m, "M2")
    assert status_mod.campaign_status(m)["models"]["M2"]["state"] == "LOCAL_RESOURCE_LIMIT"


def test_classifying_a_complete_or_in_flight_phase_is_refused(modern, tmp_path, server):
    m = make_modern(modern, tmp_path, server, tasks=(TASK,))
    complete(m, server, "M1")
    with pytest.raises(CampaignStop, match=r"qwen3.5:9b \(M1\) completed its batch: it is ranked, not classified"):
        classify_model(m, "M1", "LOCAL_RESOURCE_LIMIT", "late regret", "none")
    add_in_flight(m, m.cells("M2")[0])
    with pytest.raises(CampaignStop, match="has evaluations in flight"):
        classify_model(m, "M2", "LOCAL_RUNTIME_UNSUPPORTED", "crashes", "app.log")
    assert not load_ledger(m).data.get("model_status")


def test_an_optional_model_is_left_not_benchmarked_and_never_ranked(modern, tmp_path, server):
    m = make_modern(modern, tmp_path, server, models=(M1, M5), tasks=(TASK,), reps=1, minimum_ranked=1)
    assert m.expected["required_models"] == 1 and m.expected["optional_models"] == 1
    assert m.expected["minimum_runs"] == 1 and m.phases == ["M1", "M5"]
    complete(m, server, "M1")
    pending = validate_mod.validate_campaign(m)
    assert pending["complete"] is False  # an optional model is still expected until it is classified
    assert pending["cohort"]["models"]["M5"]["state"] == "NOT_STARTED"
    assert pending["cohort"]["required_models_complete"] == pending["cohort"]["required_models"] == 1
    classify_model(m, "M5", "NOT_BENCHMARKED", "optional model skipped: the required cohort is complete",
                   "operator decision recorded in the campaign notes")
    receipt = validate_mod.validate_campaign(m)
    assert receipt["complete"] is True, receipt["problems"]
    info = receipt["cohort"]["models"]["M5"]
    assert info["state"] == "NOT_BENCHMARKED" and info["optional"] is True and info["accepted_runs"] == 0
    assert info["ranked"] is False and info["accepted_cells"] == 0
    assert receipt["cohort"]["ranked_models"] == [M1] and receipt["cohort"]["meets_minimum"] is True
    board = analysis.official_baseline(m)
    assert board["official"] is True and [e["agent"] for e in board["leaderboard"]] == [M1]
    assert board["model_states"]["M5"]["state"] == "NOT_BENCHMARKED"
    assert board["task_matrix"][0]["cells"][M5] == {"evidence": None, "note": "not ranked (NOT_BENCHMARKED)"}
    markdown = analysis.render_official_baseline(board)
    assert M5 not in leaderboard_section(markdown)
    assert "| M5 | qwen3.6:27b | Qwen3.6 27B | NOT_BENCHMARKED | 0 |" in markdown


# =========================================================================== #
# 8. the leaderboard ranks only complete models
# =========================================================================== #


def test_only_complete_models_are_ranked_partial_and_classified_ones_are_listed_apart(modern, tmp_path, server):
    m = make_modern(modern, tmp_path, server, minimum_ranked=1)
    complete(m, server, "M1")
    model_receipt(m, "M1")  # one model at a time: M1 is finished before M2 starts
    server.install_pinned(m, "M2")
    with running_app(m.db_path(), declared_factory()) as (_app, api):
        assert launch(m, api, "M2", max_evaluations=1)["paused"] is True  # M2 stays PARTIAL
    ledger = load_ledger(m)
    m1_ids = sorted(ledger.active_entry(c.key)["evaluation_id"] for c in m.cells("M1"))
    assert ledger.active_entry(m.cells("M2")[0].key)["state"] == SUCCEEDED
    progress = status_mod.campaign_status(m)["models"]["M2"]
    assert (progress["state"], progress["cells_complete"], progress["cells"]) == ("IN_PROGRESS", 1, 2)
    assert validate_mod.validate_campaign(m)["cohort"]["models"]["M2"]["state"] == "INCOMPLETE"

    assert analysis.official_baseline(m) is None  # incomplete: no official report
    provisional = analysis.official_baseline(m, allow_incomplete=True)
    assert provisional["official"] is False and provisional["label"] == "PROVISIONAL - campaign incomplete"
    assert [e["agent"] for e in provisional["leaderboard"]] == [M1]
    assert provisional["model_states"]["M2"]["state"] == "INCOMPLETE"
    assert provisional["model_states"]["M2"]["accepted_cells"] == 1
    assert provisional["model_states"]["M2"]["accepted_runs"] == 2  # disclosed, never ranked
    assert provisional["model_states"]["M2"]["ranked"] is False and provisional["model_states"]["M1"]["ranked"]
    assert set(provisional["provenance"]["evaluation_per_cell"].values()) == set(m1_ids)
    assert all(row["cells"][M2] == {"evidence": None, "note": "not ranked (INCOMPLETE)"}
               for row in provisional["task_matrix"])
    assert provisional["missing_cells"] == [m.cells("M2")[1].key]
    markdown = analysis.render_official_baseline(provisional)
    assert "PROVISIONAL" in markdown and M2 not in leaderboard_section(markdown)

    with pytest.raises(CampaignStop, match=r"already has 1 accepted cell\(s\)"):
        classify_model(m, "M2", "LOCAL_RUNTIME_UNSUPPORTED", "generation stalls after the first cell",
                       "evaluation report of the first cell")
    record = classify_model(m, "M2", "LOCAL_RUNTIME_UNSUPPORTED", "generation stalls after the first cell",
                            "evaluation report of the first cell", after_results=True)
    assert (record["accepted_cells_at_classification"], record["accepted_runs_at_classification"]) == (1, 2)
    board = analysis.official_baseline(m)
    assert board["official"] is True and board["label"] == "OFFICIAL modern local leaderboard"
    assert board["report"] == "modern-local-leaderboard" and board["missing_cells"] == []
    assert [e["agent"] for e in board["leaderboard"]] == [M1]
    assert all(e["n"] > 0 for e in board["leaderboard"])  # never a zero-score entry
    assert board["model_states"]["M2"]["state"] == "LOCAL_RUNTIME_UNSUPPORTED"
    assert (board["model_states"]["M2"]["accepted_cells"], board["model_states"]["M2"]["accepted_runs"]) == (1, 2)
    assert board["model_states"]["M2"]["ranked"] is False
    assert board["evidence"]["evaluation_ids"] == m1_ids  # the classified model's accepted cell is not used
    assert set(board["domain_profiles"]) == {M1}
    assert board["provenance"]["model_identity"]["reference_digests"] == m.pinned_digests()
    markdown = analysis.render_official_baseline(board)
    assert M2 not in leaderboard_section(markdown)
    assert "LOCAL_RUNTIME_UNSUPPORTED | 2 | generation stalls after the first cell" in markdown
    assert "pinned registry digest in the frozen manifest" in markdown


def test_the_leaderboard_evidence_lists_only_the_ranked_models(modern, tmp_path, server):
    # was a PRODUCT BUG (fixed in cfa9025): the report's evidence listed a PARTIAL model's accepted cells
    m = make_modern(modern, tmp_path, server, reps=1)
    complete(m, server, "M1")
    model_receipt(m, "M1")
    server.install_pinned(m, "M2")
    with running_app(m.db_path(), declared_factory()) as (_app, api):
        assert launch(m, api, "M2", max_evaluations=1)["paused"] is True  # M2 stays PARTIAL
    ledger = load_ledger(m)
    m1_ids = sorted(ledger.active_entry(c.key)["evaluation_id"] for c in m.cells("M1"))
    provisional = analysis.official_baseline(m, allow_incomplete=True)
    assert [e["agent"] for e in provisional["leaderboard"]] == [M1]
    evidence = provisional["evidence"]
    assert evidence["evaluation_ids"] == m1_ids
    assert set(evidence["by_cell"]) == {c.key for c in m.cells("M1")}
    assert len(evidence["run_ids"]) == evidence["runs_verified_owned"] == 2
    assert "Evaluations used: 2; runs used (ownership verified): 2" in analysis.render_official_baseline(provisional)


def test_the_historical_comparisons_refuse_a_sequential_plan(modern, tmp_path, server, capsys):
    m = make_modern(modern, tmp_path, server)
    with pytest.raises(AnalysisError, match="does not apply to a sequential-local campaign"):
        analysis.phase_a_comparison(m)
    with pytest.raises(AnalysisError, match="does not apply to a sequential-local campaign"):
        analysis.baseline_comparison(m)
    manifest_file = tmp_path / "manifest.json"
    dump(m.data, manifest_file)
    for command in ("phase-a-report", "compare-baselines"):
        assert cli.main(["--manifest", str(manifest_file), command, "--out-dir", str(tmp_path / "out")]) == 3
        assert "refused:" in capsys.readouterr().err
    assert not (tmp_path / "out").exists()


def test_a_campaign_whose_every_model_is_classified_is_not_an_official_leaderboard(modern, tmp_path, server,
                                                                                    capsys):
    # was a PRODUCT BUG (fixed in 4432f3f): an all-classified cohort produced an OFFICIAL empty leaderboard.
    # The OFFICIAL gate is the plan's cohort floor (even a floor of 1 is never met by 0 complete models);
    # the completeness receipt itself only says that nothing expected is missing.
    m = make_modern(modern, tmp_path, server, minimum_ranked=1)
    for phase in m.phases:
        classify_model(m, phase, "LOCAL_RESOURCE_LIMIT", "does not fit on this machine", "storage inventory")
    receipt = validate_mod.validate_campaign(m)
    assert receipt["cohort"]["ranked_models"] == [] and receipt["present"]["runs"] == 0
    assert receipt["cohort"]["minimum_ranked_models"] == 1 and receipt["cohort"]["meets_minimum"] is False
    assert not any(info["ranked"] for info in receipt["cohort"]["models"].values())
    assert "cohort below its floor: 0 complete model(s) < 1" in validate_mod.render(receipt)
    assert analysis.official_baseline(m) is None
    provisional = analysis.official_baseline(m, allow_incomplete=True)
    assert provisional["official"] is False and provisional["leaderboard"] == []
    assert provisional["label"] == "PROVISIONAL - campaign incomplete"
    run_cli = cli_runner(m, tmp_path, capsys)
    rc, out, _ = run_cli("baseline-report", "--out-dir", str(tmp_path / "board"))
    assert rc == 1 and "OFFICIAL baseline is not produced" in out and not (tmp_path / "board").exists()


def test_a_cohort_below_the_plans_floor_of_complete_models_is_never_official(modern, tmp_path, server, capsys):
    m = make_modern(modern, tmp_path, server, tasks=(TASK,), reps=1)
    assert m.data["execution"]["minimum_ranked_models"] == 3  # inherited from the frozen plan
    complete(m, server, "M1")
    model_receipt(m, "M1")
    complete(m, server, "M2")
    receipt = validate_mod.validate_campaign(m)
    # nothing expected is missing, but the validator itself enforces the floor (final review RT-6)
    assert receipt["missing"]["cells"] == [] and receipt["present"]["cells_complete"] == 2
    assert receipt["complete"] is False
    assert receipt["problems"] == ["cohort below the plan's floor: 2 complete model(s) < minimum_ranked_models 3"]
    cohort_info = receipt["cohort"]
    assert cohort_info["ranked_models"] == [M1, M2] and all(i["ranked"] for i in cohort_info["models"].values())
    assert cohort_info["minimum_ranked_models"] == 3 and cohort_info["meets_minimum"] is False  # ... but 2 < 3
    assert "cohort below its floor: 2 complete model(s) < 3" in validate_mod.render(receipt)
    assert analysis.official_baseline(m) is None
    provisional = analysis.official_baseline(m, allow_incomplete=True)
    assert provisional["official"] is False and provisional["label"] == "PROVISIONAL - campaign incomplete"
    assert sorted(e["agent"] for e in provisional["leaderboard"]) == sorted([M1, M2])
    assert provisional["cohort"]["meets_minimum"] is False
    assert "PROVISIONAL" in analysis.render_official_baseline(provisional)
    run_cli = cli_runner(m, tmp_path, capsys)
    rc, _, _ = run_cli("validate", "--receipt", str(tmp_path / "receipt.json"))
    assert rc == 1  # below the floor: never COMPLETE, and the leaderboard is never OFFICIAL
    rc, out, _ = run_cli("baseline-report", "--out-dir", str(tmp_path / "board"))
    assert rc == 1 and not (tmp_path / "board").exists()
    rc, _, _ = run_cli("baseline-report", "--allow-incomplete", "--out-dir", str(tmp_path / "board"))
    assert rc == 0 and (tmp_path / "board" / "modern-local-leaderboard-PROVISIONAL.json").exists()


# =========================================================================== #
# status
# =========================================================================== #


def test_status_of_one_phase_never_misreports_the_other_models(modern, tmp_path, server):
    # was a PRODUCT BUG (fixed in cfa9025): 'status --phase M2' reported a COMPLETE M1 as NOT_STARTED
    m = make_modern(modern, tmp_path, server, tasks=(TASK,), reps=1)
    complete(m, server, "M1")
    model_receipt(m, "M1")
    everything = status_mod.campaign_status(m)["models"]
    assert everything["M1"]["state"] == "COMPLETE"
    scoped = status_mod.campaign_status(m, "M2")
    assert scoped["scope"] == "M2" and scoped["models"] == everything  # every model, whatever the scope


# =========================================================================== #
# smoke: a scratch database, never evidence
# =========================================================================== #


def test_the_smoke_runs_in_a_scratch_database_and_is_only_recorded_in_the_main_ledger(modern, tmp_path, server):
    m = make_modern(modern, tmp_path, server)
    server.install_pinned(m, "M1")
    port = free_port()
    started: list[ThreadedApp] = []

    def start_app(db_path, port_, log_path):
        assert port_ == port and Path(db_path) != m.db_path()
        assert Path(db_path).parent.parent == m.runtime_subdir("smoke_dir")
        app = ThreadedApp(Path(db_path), port_, declared_factory())
        started.append(app)
        return app

    try:
        record = run_smoke(m, "M1", port=port, tasks=[TASK], start_app=start_app, log=lambda _m: None)
    finally:
        for app in started:
            app.stop()
    assert len(started) == 1
    assert record["operational_ok"] is True and (record["outcome"], record["failure"]) == ("ok", None)
    assert (record["phase"], record["model"], record["tasks"]) == ("M1", M1, [TASK])
    assert record["valid"] == 1 and record["smoke_problems"] == []
    assert record["smoke_campaign_id"].startswith(f"{m.campaign_id}-smoke-M1-")
    assert [p["name"] for p in record["ollama_ps"]] == [M1]
    # what the campaign's own preflight needs from a smoke: the observed digest and the server version
    assert record["digest"] == pin(m, "M1") and record["ollama_version"] == PINNED_VERSION
    scratch = paths.resolve(record["scratch"])
    assert scratch.parent == m.runtime_subdir("smoke_dir")
    assert not (scratch / "app.pgid").exists() and lifecycle.live_smoke_apps(m) == []  # its app is gone
    # never campaign evidence: the campaign database is untouched and the main ledger owns nothing
    assert evaluation_ids(m) == set()
    ledger = load_ledger(m)
    assert ledger.entries == [] and ledger.data["launches"] == []
    assert ledger.data["smokes"] == [record]
    smoke = Manifest.load(scratch / "smoke.manifest.json")
    assert smoke.campaign_id == record["smoke_campaign_id"] and smoke.models == [M1]
    assert smoke.data["smoke_of"] == m.campaign_id and smoke.data["derived_from"]["campaign_id"] == m.campaign_id
    assert smoke.task_ids == [TASK] and smoke.repetitions == 1 and smoke.phases == ["M1"]
    assert smoke.backend == m.backend and smoke.generation == m.generation
    assert smoke.db_path() == scratch / "smoke.sqlite" and smoke.ledger_path() == scratch / "ledger.json"
    assert Ledger.load(smoke.ledger_path()).data["campaign_id"] == smoke.campaign_id
    with closing(cohort.open_readonly(smoke.db_path())) as conn:
        names = [e["name"] for e in cohort.evaluations_named(conn, smoke.data["evaluation_name_prefix"])]
    assert names == [f"campaign:{smoke.campaign_id}:M1:{M1}|{TASK}"]
    receipt = validate_mod.validate_campaign(m, phase="M1")
    assert receipt["complete"] is False and receipt["present"]["runs"] == 0


def test_a_smoke_never_runs_beside_active_campaign_evaluations(modern, tmp_path, server):
    m = make_modern(modern, tmp_path, server)
    server.install_pinned(m, "M1")
    add_in_flight(m, m.cells("M2")[0])

    def start_app(*_args):
        raise AssertionError("no smoke app may start beside a campaign evaluation")

    with pytest.raises(CampaignStop, match="a smoke never runs beside them"):
        run_smoke(m, "M1", port=free_port(), tasks=[TASK], start_app=start_app)
    assert not m.runtime_subdir("smoke_dir").exists()
    assert not load_ledger(m).data.get("smokes")


def test_a_smoke_plan_is_derived_and_validated_before_the_main_ledger_is_touched(modern, tmp_path, server):
    m = make_modern(modern, tmp_path, server)
    server.install_pinned(m, "M1")

    def start_app(*_args):
        raise AssertionError("no smoke app for an invalid smoke plan")

    with pytest.raises(ManifestError, match=r"unknown models \[\] / tasks \['no-such-task'\]"):
        run_smoke(m, "M1", port=free_port(), tasks=["no-such-task"], start_app=start_app)
    assert not m.ledger_path().exists() and not m.runtime_subdir("smoke_dir").exists()


def test_the_optional_model_can_be_smoked(modern, tmp_path, server):
    # was a PRODUCT BUG (fixed in 4432f3f): the smoke plan of the OPTIONAL model had no required model
    m = make_modern(modern, tmp_path, server, models=(M1, M5), tasks=(TASK,), reps=1)
    server.install_pinned(m, "M5")

    def start_app(db_path, _port, _log):
        raise ReachedApp(db_path)

    with pytest.raises(ReachedApp):
        run_smoke(m, "M5", port=free_port(), tasks=[TASK], start_app=start_app)
    folder = next(m.runtime_subdir("smoke_dir").glob("M5-*"))
    smoke = Manifest.load(folder / "smoke.manifest.json")
    assert smoke.models == [M5] and [e["optional"] for e in smoke.data["roster"]] == [False]
    assert m.phase_entry("M5")["optional"] is True  # the campaign's own roster is unchanged
    # the failed smoke is recorded in the main ledger all the same
    [record] = load_ledger(m).data["smokes"]
    assert (record["phase"], record["model"], record["outcome"]) == ("M5", M5, "error")
    assert record["operational_ok"] is False and record["failure"].startswith("ReachedApp")
    assert record["ollama_version"] == PINNED_VERSION and record["digest"] is None and record["finished_at"]


# =========================================================================== #
# storage inventory
# =========================================================================== #


def _weights(folder: Path, name: str, size: int) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / name).write_bytes(b"\0" * size)


def test_the_storage_inventory_reports_everything_and_changes_nothing(modern, tmp_path, server, disk, monkeypatch):
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    hub = home / ".cache" / "huggingface" / "hub"
    _weights(hub / "models--mlx-community--Qwen3-4B-4bit" / "snapshots" / "a", "model.safetensors", 3000)
    _weights(hub / "models--TheBloke--tiny-GGUF" / "snapshots" / "b", "tiny.Q4_K_M.gguf", 500)
    _weights(home / ".lmstudio" / "models" / "lmstudio-community" / "phi-4", "phi-4.gguf", 700)
    m = make_modern(modern, tmp_path, server)
    server.install_pinned(m, "M1")
    server.install(OTHER, "1" * 64, size=2 * GIB)
    server.install("qwen3-4b-mlx", "2" * 64, size=GIB, fmt="safetensors")
    inventory, target = storage_inventory(m, "before-m1")
    assert target == m.runtime_subdir("inventories") / "before-m1.json"
    assert json.loads(target.read_text()) == inventory
    assert inventory["disk"]["free_bytes"] == disk.free and inventory["disk"]["volume_of"].endswith("ollama-models")
    assert inventory["ollama"]["reachable"] is True and inventory["ollama"]["version"] == server.version
    by_name = {model["name"]: model for model in inventory["ollama"]["models"]}
    assert by_name[M1]["campaign_target"] == "M1" and by_name[M1]["digest"] == pin(m, "M1")
    assert by_name[M1]["quantization"] == "Q4_K_M" and by_name[M1]["mlx"] is False
    assert by_name[OTHER]["campaign_target"] is None and by_name["qwen3-4b-mlx"]["mlx"] is True
    others = {w["model"]: w for w in inventory["other_model_weights"]}
    assert others["mlx-community/Qwen3-4B-4bit"]["kind"] == "mlx"
    assert others["mlx-community/Qwen3-4B-4bit"]["bytes"] == 3000
    assert others["mlx-community/Qwen3-4B-4bit"]["path"].startswith("~/.cache/huggingface/hub/")
    assert others["TheBloke/tiny-GGUF"]["kind"] == "gguf"
    assert others["lmstudio-community/phi-4"]["runtime"] == "lm-studio"
    assert inventory["reclaimable_estimate_bytes"]["ollama_non_target_models"] == 3 * GIB
    assert inventory["reclaimable_estimate_bytes"]["mlx_weights_outside_ollama"] == 3000
    assert [(r["phase"], r["installed"]) for r in inventory["roster"]] == [("M1", True), ("M2", False)]
    assert {method for method, _path in server.requests} == {"GET"}  # read-only
    assert server.pulls == server.deletes == [] and not m.ledger_path().exists()
    assert all(p.exists() for p in (hub / "models--mlx-community--Qwen3-4B-4bit", home / ".lmstudio"))
    server.stop()
    unreachable, _ = storage_inventory(m, "ollama-down")
    assert isinstance(unreachable["ollama"]["reachable"], str) and unreachable["ollama"]["models"] == []
    assert [r["installed"] for r in unreachable["roster"]] == [False, False]


BAD_LABELS = ["", "../escape", "a/b", "/abs", ".hidden", "-dash", "_under", "a b", "a..b", "..", "x" * 65, "é",
              "tab\t", "new\nline", "before:M1"]


def test_an_inventory_label_is_a_plain_name_and_an_inventory_is_never_overwritten(modern, tmp_path, server,
                                                                                   monkeypatch, capsys):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    m = make_modern(modern, tmp_path, server)
    folder = m.runtime_subdir("inventories")
    for label in BAD_LABELS:
        with pytest.raises(CampaignStop, match="must be a plain name"):
            storage_inventory(m, label)
    assert server.requests == []  # refused before Ollama is asked anything
    assert not folder.exists() and not (m.runtime_dir() / "escape.json").exists()
    assert not (tmp_path / "escape.json").exists()
    for label in ("before-M1_v2.0", "x" * 64, "9"):
        _inventory, target = storage_inventory(m, label)
        assert target == folder / f"{label}.json" and target.exists()
    frozen = (folder / "before-M1_v2.0.json").read_bytes()
    server.install(OTHER, "1" * 64)  # the next inventory would differ
    with pytest.raises(CampaignStop, match="already exists; inventories are never overwritten"):
        storage_inventory(m, "before-M1_v2.0")
    assert (folder / "before-M1_v2.0.json").read_bytes() == frozen
    assert sorted(p.name for p in folder.iterdir()) == sorted(["before-M1_v2.0.json", "x" * 64 + ".json", "9.json"])
    run_cli = cli_runner(m, tmp_path, capsys)
    for label in ("../escape", "before-M1_v2.0"):
        rc, _, err = run_cli("storage-inventory", "--label", label)
        assert rc == 3 and err.startswith("refused:")
    assert (folder / "before-M1_v2.0.json").read_bytes() == frozen


# =========================================================================== #
# CLI
# =========================================================================== #

# the lifecycle commands (pull-model, classify-model, model-receipt, smoke) validate --phase too: was a
# PRODUCT BUG (fixed in 4432f3f) - an uncaught KeyError traceback instead of 'refused: unknown phase'
CLI_UNKNOWN_PHASES = [
    pytest.param(["launch", "--phase", "A", "--confirm", "{cid}"], id="launch-A"),
    pytest.param(["launch", "--phase", "all", "--confirm", "{cid}"], id="launch-all"),
    pytest.param(["launch", "--phase", "M9", "--confirm", "{cid}"], id="launch-M9"),
    pytest.param(["preflight", "--phase", "B", "--api", "{api}"], id="preflight-B"),
    pytest.param(["validate", "--phase", "M9"], id="validate-M9"),
    pytest.param(["status", "--phase", "A"], id="status-A"),
    pytest.param(["plan", "--phase", "B"], id="plan-B"),
    pytest.param(["pull-model", "--phase", "M9", "--api", "{api}"], id="pull-model-M9"),
    pytest.param(["pull-model", "--phase", "all", "--api", "{api}"], id="pull-model-all"),
    pytest.param(["classify-model", "--phase", "M9", "--status", "NOT_BENCHMARKED", "--reason", "r",
                  "--evidence", "e"], id="classify-model-M9"),
    pytest.param(["classify-model", "--phase", "A", "--status", "NOT_BENCHMARKED", "--reason", "r",
                  "--evidence", "e", "--after-results"], id="classify-model-A"),
    pytest.param(["model-receipt", "--phase", "M9"], id="model-receipt-M9"),
    pytest.param(["model-receipt", "--phase", "all", "--reissue"], id="model-receipt-all"),
    pytest.param(["smoke", "--phase", "M9", "--confirm", "{cid}"], id="smoke-M9"),
    pytest.param(["smoke", "--phase", "all", "--confirm", "{cid}"], id="smoke-all"),
]


@pytest.mark.parametrize("argv", CLI_UNKNOWN_PHASES)
def test_the_cli_refuses_phases_the_plan_does_not_have(modern, tmp_path, server, capsys, argv):
    m = make_modern(modern, tmp_path, server)
    server.install_pinned(m, "M1")
    manifest_file = tmp_path / "manifest.json"
    dump(m.data, manifest_file)
    args = [a.format(cid=m.campaign_id, api=closed_api()) for a in argv]
    rc = cli.main(["--manifest", str(manifest_file), *args])
    err = capsys.readouterr().err
    assert rc == 3 and err.startswith("refused:"), err
    assert re.search(r"unknown phase|one model's phase at a time", err), err
    assert not m.ledger_path().exists()
    assert server.pulls == [] and server.deletes == [] and evaluation_ids(m) == set()


def test_the_cli_manifest_defaults_to_the_environment_variable(modern, tmp_path, server, monkeypatch, capsys):
    m = make_modern(modern, tmp_path, server, init=False)
    manifest_file = tmp_path / "plan.json"
    dump(m.data, manifest_file)
    monkeypatch.setenv("AFA_CAMPAIGN_MANIFEST", str(manifest_file))
    assert cli.build_parser().parse_args(["plan"]).manifest == str(manifest_file)
    assert cli.main(["plan", "--phase", "M2"]) == 0
    out = capsys.readouterr().out
    assert all(c.key in out for c in m.cells("M2")) and M1 not in out
    assert "2 cells x 2 = 4 runs" in out
    assert cli.main(["plan"]) == 0 and "4 cells x 2 = 8 runs" in capsys.readouterr().out


def test_the_cli_lifecycle_commands(modern, tmp_path, server, monkeypatch, capsys):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    m = make_modern(modern, tmp_path, server)
    manifest_file = tmp_path / "manifest.json"
    dump(m.data, manifest_file)
    api = ["--api", closed_api()]

    def run_cli(*argv) -> tuple[int, str, str]:
        rc = cli.main(["--manifest", str(manifest_file), *argv])
        captured = capsys.readouterr()
        return rc, captured.out, captured.err

    server.serve(m, "M1")
    rc, out, _ = run_cli("storage-inventory", "--label", "start")
    assert rc == 0 and (m.runtime_subdir("inventories") / "start.json").exists()
    rc, out, _ = run_cli("pull-model", "--phase", "M1", *api)
    assert rc == 0 and json.loads(out.strip().splitlines()[-1])["outcome"] == "pulled"
    rc, _, err = run_cli("model-receipt", "--phase", "M1")
    assert rc == 3 and "refused:" in err and "does not validate complete" in err
    # remove-model deletes weights: it needs the exact campaign id, like launch and smoke
    for confirm in ([], ["--confirm", "phase0-modern-local-v1"], ["--confirm", ""]):
        rc, out, _ = run_cli("remove-model", "--model", M1, "--reason", "free space", *confirm, *api)
        assert rc == 2 and f"Re-run with --confirm {m.campaign_id}" in out
    assert M1 in server.models and not any(l["action"] == "remove-model" for l in storage_log_lines(m))
    rc, _, err = run_cli("remove-model", "--model", M1, "--reason", "free space", "--confirm", m.campaign_id, *api)
    assert rc == 3 and "evidence is not frozen yet" in err and M1 in server.models
    rc, out, _ = run_cli("classify-model", "--phase", "M2", "--status", "LOCAL_RESOURCE_LIMIT", "--reason",
                         "does not fit", "--evidence", "inventories/start.json")
    assert rc == 0 and "classified gpt-oss:20b (M2) LOCAL_RESOURCE_LIMIT" in out
    rc, _, err = run_cli("classify-model", "--phase", "M2", "--status", "NOT_BENCHMARKED", "--reason", "r",
                         "--evidence", "e")
    assert rc == 3 and "already classified" in err
    with pytest.raises(SystemExit):
        run_cli("classify-model", "--phase", "M2", "--status", "TOO_BIG", "--reason", "r", "--evidence", "e")
    server.serve(m, "M2")
    rc, _, err = run_cli("pull-model", "--phase", "M2", *api)
    assert rc == 3 and "is classified" in err
    server.install(OTHER, "1" * 64)
    rc, out, _ = run_cli("remove-model", "--model", OTHER, "--reason", "free space", *api)
    assert rc == 2 and OTHER in server.models
    rc, out, _ = run_cli("remove-model", "--model", OTHER, "--reason", "free space", "--confirm", m.campaign_id,
                         *api)
    assert rc == 0 and server.deletes == [OTHER]
    rc, out, _ = run_cli("smoke", "--phase", "M1")
    assert rc == 2 and f"--confirm {m.campaign_id}" in out and not m.runtime_subdir("smoke_dir").exists()
    assert server.pulls == [M1]
    # an unreachable Ollama is an operator-facing refusal (exit 3), never a traceback
    server.install(OTHER, "1" * 64)
    server.stop()
    for argv in (("remove-model", "--model", OTHER, "--reason", "free space", "--confirm", m.campaign_id, *api),
                 ("pull-model", "--phase", "M1", *api),
                 ("smoke", "--phase", "M1", "--confirm", m.campaign_id, "--port", str(free_port()))):
        rc, _, err = run_cli(*argv)
        assert rc == 3 and err.startswith("refused:"), (argv, err)
    assert server.deletes == [OTHER] and server.pulls == [M1]


# =========================================================================== #
# 13. the red-team contract: server-version pin, smoke before launch, one model
#     at a time, live smoke apps, classification after results, frozen receipts
# =========================================================================== #


def test_the_pinned_ollama_server_version_is_required_to_launch_pull_and_smoke(modern, tmp_path, server):
    m = make_modern(modern, tmp_path, server)
    server.install_pinned(m, "M1")
    server.serve(m, "M2")
    server.version = OTHER_VERSION
    mismatch = f"Ollama server version is '{OTHER_VERSION}', the frozen plan pins '{PINNED_VERSION}'"
    pf = launcher.preflight(m, None, check_code=False, phase="M1")
    assert pf.problems == [f"{mismatch}; one cohort never mixes inference engines"]
    with running_app(m.db_path(), declared_factory()) as (_app, api):
        with pytest.raises(CampaignStop, match=re.escape(mismatch)):
            launch(m, api, "M1")  # the FIRST launch: there is no earlier launch to compare with
        assert api.posts == []

    def no_app(*_args):
        raise AssertionError("no smoke app on another server version")

    for what, action in (("pull-model", lambda: pull_model(m, "M1", pull=_never_pull)),  # not even a reuse
                         ("pull-model", lambda: pull_model(m, "M2")),
                         ("smoke", lambda: run_smoke(m, "M1", port=free_port(), tasks=[TASK], start_app=no_app))):
        with pytest.raises(CampaignStop, match=re.escape(f"{mismatch}: {what} refused")):
            action()
    assert server.pulls == [] and storage_log_lines(m) == []
    assert not m.ledger_path().exists() and not m.runtime_subdir("smoke_dir").exists()
    # a server that does not report its version is not the pinned one either
    server.version = None
    problems = launcher.preflight(m, None, check_code=False, phase="M1").problems
    assert any("did not report its server version" in p for p in problems)
    assert any(f"Ollama server version is None, the frozen plan pins '{PINNED_VERSION}'" in p for p in problems)
    with pytest.raises(CampaignStop, match="Ollama server version is None"):
        pull_model(m, "M1", pull=_never_pull)
    # the pin is the PLAN's: a plan pinning the other build accepts it and refuses the committed one
    other = make_modern(modern, tmp_path, server, name="o", campaign_id="t-other-server",
                        server_version=OTHER_VERSION)
    server.version = OTHER_VERSION
    assert launcher.preflight(other, None, check_code=False, phase="M1").ok
    assert pull_model(other, "M1", pull=_never_pull)["outcome"] == "reused"
    server.version = PINNED_VERSION
    assert any(f"the frozen plan pins '{OTHER_VERSION}'" in p
               for p in launcher.preflight(other, None, check_code=False, phase="M1").problems)
    with pytest.raises(CampaignStop, match=re.escape(f"the frozen plan pins '{OTHER_VERSION}': pull-model refused")):
        pull_model(other, "M1", pull=_never_pull)
    assert launcher.preflight(m, None, check_code=False, phase="M1").ok
    assert not m.ledger_path().exists()


def test_the_campaigns_own_plan_is_never_launched_without_a_passing_smoke_of_the_pinned_target(modern, tmp_path,
                                                                                                server, monkeypatch):
    m = own_plan(modern, tmp_path, server)
    assert m.campaign_id == MODERN_CAMPAIGN_ID and m.phases == ["M1", "M2", "M3", "M4", "M5"]
    assert m.data["execution"] == modern.data["execution"] and m.data["roster"] == modern.data["roster"]
    server.install_pinned(m, "M1")

    def no_smoke(phase: str) -> str:
        return (f"no passing smoke of {m.phase_entry(phase)['model']} with its pinned digest is recorded: run "
                f"smoke --phase {phase} first")

    pf = launcher.preflight(m, None, check_code=False, phase="M1")
    assert pf.problems == [no_smoke("M1") + " (4 tasks x 1 repetition in a scratch database)"]
    with running_app(m.db_path(), declared_factory()) as (_app, api):
        with pytest.raises(CampaignStop, match=re.escape(no_smoke("M1"))):
            launch(m, api, "M1")
        assert api.posts == []
    assert not m.ledger_path().exists()  # a refused launch leaves nothing behind

    # recorded smokes that are NOT a passing smoke of the pinned target never unlock it
    for fields in ({"phase": "M1", "operational_ok": False, "digest": pin(m, "M1")},  # failed
                   {"phase": "M1", "operational_ok": True, "digest": STALE},  # other weights
                   {"phase": "M1", "operational_ok": True, "digest": None},  # identity unknown
                   {"phase": "M1", "operational_ok": True, "digest": sorted([pin(m, "M1"), STALE])},  # mixed
                   {"phase": "M2", "operational_ok": True, "digest": pin(m, "M2")}):  # another model
        record_smoke(m, **fields)
        problems = launcher.preflight(m, None, ledger=load_ledger(m), check_code=False, phase="M1").problems
        assert any(no_smoke("M1") in p for p in problems), fields

    # a real smoke that fails is recorded and unlocks nothing; a passing one unlocks its own model only
    started: list[ThreadedApp] = []

    def start_app(db_path, port, _log_path):
        app = ThreadedApp(Path(db_path), port, declared_factory())
        started.append(app)
        return app

    server.remove(M1)  # the smoke's own launch halts in preflight: its target is not installed
    # each smoke gets its own scratch folder (named by a second-resolution UTC stamp)
    freeze_lifecycle_clock(monkeypatch, datetime.datetime(2026, 9, 28, 12, 0, 1, tzinfo=datetime.timezone.utc),
                           datetime.datetime(2026, 9, 28, 12, 0, 2, tzinfo=datetime.timezone.utc))
    try:
        failed = run_smoke(m, "M1", port=free_port(), tasks=[TASK], start_app=start_app, log=lambda _m: None)
        server.install_pinned(m, "M1")
        passed = run_smoke(m, "M1", port=free_port(), tasks=[TASK], start_app=start_app, log=lambda _m: None)
    finally:
        for app in started:
            app.stop()
    assert (failed["outcome"], failed["operational_ok"], failed["digest"]) == ("halted", False, None)
    assert "target qwen3.5:9b (M1) is not installed" in failed["failure"]
    assert failed["ollama_version"] == PINNED_VERSION and failed["finished_at"]
    assert (passed["outcome"], passed["operational_ok"], passed["digest"]) == ("ok", True, pin(m, "M1"))
    ledger = load_ledger(m)
    assert ledger.data["smokes"][-2:] == [failed, passed]
    assert ledger.entries == [] and ledger.data["launches"] == [] and evaluation_ids(m) == set()  # never evidence
    pf = launcher.preflight(m, None, ledger=ledger, check_code=False, phase="M1")
    assert pf.ok, pf.problems
    assert any(no_smoke("M3") in p for p in launcher.preflight(m, None, ledger=ledger, check_code=False,
                                                               phase="M3").problems)
    # the observed digest is normalized before it is compared with the pin
    record_smoke(m, phase="M4", operational_ok=True, digest="sha256:" + pin(m, "M4"))
    assert not any(no_smoke("M4") in p for p in launcher.preflight(m, None, ledger=load_ledger(m), check_code=False,
                                                                   phase="M4").problems)
    with running_app(m.db_path(), declared_factory()) as (_app, api):
        result = launch(m, api, "M1", max_evaluations=1)
        assert result["submitted"] == 1 and result["paused"] is True
        assert [p["name"] for p in api.posts] == [m.evaluation_name(m.cells("M1")[0])]
    entry = load_ledger(m).active_entry(m.cells("M1")[0].key)
    assert entry["state"] == SUCCEEDED and entry["expected_runs"] == 5


def test_one_model_at_a_time_a_phase_starts_only_after_the_previous_one_is_finished(modern, tmp_path, server):
    m = make_modern(modern, tmp_path, server, reps=1)
    server.install_pinned(m, "M1")
    server.install_pinned(m, "M2")  # installed by hand: only preflight decides what runs
    one_at_a_time = ("one model at a time: phase(s) ['M1'] have campaign evaluations but no frozen receipt and no "
                     "classification")

    def problems(phase: str) -> list[str]:
        return launcher.preflight(m, None, ledger=load_ledger(m), check_code=False, phase=phase).problems

    with running_app(m.db_path(), declared_factory()) as (_app, api):
        assert launch(m, api, "M1", max_evaluations=1)["paused"] is True
        assert len(problems("M2")) == 1 and problems("M2")[0].startswith(one_at_a_time)
        assert problems("M1") == []  # its own phase continues
        with pytest.raises(CampaignStop, match=re.escape(one_at_a_time)):
            launch(m, api, "M2")
        assert launch(m, api, "M1")["submitted"] == 1  # M1 completes ...
        assert validate_mod.validate_campaign(m, phase="M1")["complete"] is True
        with pytest.raises(CampaignStop, match=re.escape(one_at_a_time)):
            launch(m, api, "M2")  # ... but complete is not finished: its receipt is not frozen
        assert [p["model"] for p in api.posts] == [M1, M1]
        model_receipt(m, "M1")
        assert problems("M2") == []
        assert launch(m, api, "M2")["submitted"] == 2
        # and now M1, with its receipt, is not blocked by the finished M2 either (a no-op launch)
        model_receipt(m, "M2")
        assert launch(m, api, "M1") == {"submitted": 0, "paused": False, "drained": 0, "skipped": 2, "succeeded": 0}
    assert [p["model"] for p in api.posts] == [M1, M1, M2, M2]
    assert [e["type"] for e in load_ledger(m).data["events"]].count("preflight_failed") == 2


def test_a_live_smoke_app_blocks_preflight_removal_and_another_smoke(modern, tmp_path, server):
    m = make_modern(modern, tmp_path, server)
    server.install_pinned(m, "M1")
    server.install(OTHER, "1" * 64)

    def no_app(*_args):
        raise AssertionError("no second smoke app beside a live one")

    with live_smoke_app(m) as proc:
        assert lifecycle.live_smoke_apps(m) == [proc.pid]
        running = f"a smoke app is still running (process groups [{proc.pid}])"
        pf = launcher.preflight(m, None, check_code=False, phase="M1")
        assert pf.problems == [f"{running}; it would share the model server with the campaign - stop it first"]
        with running_app(m.db_path(), declared_factory()) as (_app, api):
            with pytest.raises(CampaignStop, match=re.escape(running)):
                launch(m, api, "M1")
            assert api.posts == []
        with pytest.raises(CampaignStop, match=re.escape(f"{running}; never remove a model then")):
            remove_model(m, OTHER, "free space")
        with pytest.raises(CampaignStop, match=re.escape(f"a smoke app is still running ([{proc.pid}]); stop it")):
            run_smoke(m, "M1", port=free_port(), tasks=[TASK], start_app=no_app)
        assert OTHER in server.models and server.deletes == [] and proc.poll() is None  # never signalled
        assert not m.ledger_path().exists() and storage_log_lines(m) == []
        assert [p.name for p in m.runtime_subdir("smoke_dir").iterdir()] == ["M1-20260928T000000Z"]
    # a pidfile whose process group is gone (a crashed smoke) blocks nothing
    assert lifecycle.live_smoke_apps(m) == []
    assert launcher.preflight(m, None, check_code=False, phase="M1").ok
    pidfile = m.runtime_subdir("smoke_dir") / "M1-20260928T000000Z" / "app.pgid"
    for content in ("", "not-a-pid", "None"):
        pidfile.write_text(content)
        assert lifecycle.live_smoke_apps(m) == [], content
    assert remove_model(m, OTHER, "free space")["outcome"] == "removed"


def test_a_pull_is_refused_while_a_smoke_app_is_alive(modern, tmp_path, server):
    m = make_modern(modern, tmp_path, server)
    server.serve(m, "M1")
    with live_smoke_app(m) as proc:
        try:
            pull_model(m, "M1")
        except CampaignStop as exc:
            refusal = str(exc)
        else:
            refusal = None
        assert proc.poll() is None
    assert refusal is not None and "smoke app is still running" in refusal, f"pulled {server.pulls} beside a smoke"
    assert server.pulls == []


def test_classifying_a_model_with_accepted_results_needs_after_results_and_is_disclosed(modern, tmp_path, server,
                                                                                         capsys):
    m = make_modern(modern, tmp_path, server, minimum_ranked=1)
    server.install_pinned(m, "M1")
    with running_app(m.db_path(), declared_factory()) as (_app, api):
        assert launch(m, api, "M1", max_evaluations=1)["paused"] is True
    first = load_ledger(m).active_entry(m.cells("M1")[0].key)["evaluation_id"]
    after_results = r"qwen3.5:9b \(M1\) already has 1 accepted cell\(s\): classifying it now excludes evidence " \
                    r"after results were visible. Pass --after-results"
    with pytest.raises(CampaignStop, match=after_results):
        classify_model(m, "M1", "LOCAL_RESOURCE_LIMIT", "swaps heavily", "smoke memory pressure")
    run_cli = cli_runner(m, tmp_path, capsys)
    argv = ("classify-model", "--phase", "M1", "--status", "LOCAL_RESOURCE_LIMIT", "--reason", "swaps heavily",
            "--evidence", "smoke memory pressure")
    rc, _, err = run_cli(*argv)
    assert rc == 3 and err.startswith("refused:") and "--after-results" in err
    assert not load_ledger(m).data.get("model_status")
    rc, out, _ = run_cli(*argv, "--after-results")
    assert rc == 0 and "classified qwen3.5:9b (M1) LOCAL_RESOURCE_LIMIT: swaps heavily" in out
    record = load_ledger(m).data["model_status"]["M1"]
    assert (record["accepted_cells_at_classification"], record["accepted_runs_at_classification"]) == (1, 2)
    assert (record["status"], record["reason"], record["evidence"]) == (
        "LOCAL_RESOURCE_LIMIT", "swaps heavily", "smoke memory pressure")
    receipt = validate_mod.validate_campaign(m)
    info = receipt["cohort"]["models"]["M1"]
    assert (info["state"], info["accepted_cells"], info["accepted_runs"], info["ranked"]) == (
        "LOCAL_RESOURCE_LIMIT", 1, 2, False)
    assert receipt["expected"]["cells"] == 2 and receipt["present"]["runs"] == 0  # M1 left the expected cohort
    # the classified model is finished: the next one starts; it is never launched again
    server.install_pinned(m, "M2")
    with running_app(m.db_path(), declared_factory()) as (_app, api):
        with pytest.raises(CampaignStop, match="is classified LOCAL_RESOURCE_LIMIT"):
            launch(m, api, "M1")
        assert launch(m, api, "M2")["submitted"] == 2
    board = analysis.official_baseline(m)
    assert board["official"] is True and [e["agent"] for e in board["leaderboard"]] == [M2]
    assert first not in board["evidence"]["evaluation_ids"] and len(board["evidence"]["evaluation_ids"]) == 2
    assert all(row["cells"][M1] == {"evidence": None, "note": "not ranked (LOCAL_RESOURCE_LIMIT)"}
               for row in board["task_matrix"])
    assert "| M1 | qwen3.5:9b | Qwen 3.5 9B | LOCAL_RESOURCE_LIMIT | 2 | swaps heavily |" in \
        analysis.render_official_baseline(board)


def test_a_failed_cell_of_a_classified_model_is_never_resumed(modern, tmp_path, server):
    m = make_modern(modern, tmp_path, server, models=(M1,), tasks=(TASK,), reps=1)
    server.install_pinned(m, "M1")
    key = m.cells("M1")[0].key
    with running_app(m.db_path(), failing_factory) as (app, api):
        with pytest.raises(CampaignStop, match="resume it under the same id"):
            launch(m, api, "M1")
        entry = load_ledger(m).active_entry(key)
        assert entry["state"] == FAILED
        classify_model(m, "M1", "LOCAL_RUNTIME_UNSUPPORTED", "the runner fails to load it", "evaluation report")
        app.state.agent_factory = declared_factory()  # even if the backend works now
        with pytest.raises(CampaignStop, match=r"its model \(M1\) is classified LOCAL_RUNTIME_UNSUPPORTED; it is not "
                                               r"benchmarked, so it is never resumed"):
            launcher.resume_cell(m, api, key, check_code=False)
        assert api.get_job(entry["evaluation_id"])["status"] == "failed"
    ledger = load_ledger(m)
    assert (ledger.active_entry(key)["state"], ledger.active_entry(key)["evaluation_id"]) == (
        FAILED, entry["evaluation_id"])
    assert not any(e["type"] == "resumed" for e in ledger.data["events"])


def test_a_frozen_receipt_is_reissued_only_on_request_and_the_previous_version_is_kept(modern, tmp_path, server,
                                                                                        monkeypatch, capsys):
    m = make_modern(modern, tmp_path, server, tasks=(TASK,), reps=1)
    complete(m, server, "M1")
    _first, target = model_receipt(m, "M1")
    frozen, frozen_md = target.read_bytes(), target.with_suffix(".md").read_bytes()
    record = copy.deepcopy(load_ledger(m).data["receipts"]["M1"])
    with pytest.raises(CampaignStop, match=r"M1-qwen3.5-9b.json is already frozen; pass --reissue"):
        model_receipt(m, "M1")
    run_cli = cli_runner(m, tmp_path, capsys)
    rc, _, err = run_cli("model-receipt", "--phase", "M1")
    assert rc == 3 and "--reissue" in err
    assert target.read_bytes() == frozen and target.with_suffix(".md").read_bytes() == frozen_md
    assert load_ledger(m).data["receipts"]["M1"] == record
    assert sorted(p.name for p in target.parent.iterdir()) == ["M1-qwen3.5-9b.json", "M1-qwen3.5-9b.md"]

    freeze_lifecycle_clock(monkeypatch, datetime.datetime(2026, 9, 28, 12, 0, 1, tzinfo=datetime.timezone.utc),
                           datetime.datetime(2026, 9, 28, 12, 0, 2, tzinfo=datetime.timezone.utc))
    second, again = model_receipt(m, "M1", reissue=True)
    superseded = {**record, "superseded_path": str(target.parent / "M1-qwen3.5-9b.superseded-20260928T120001Z.json"),
                  "superseded_sha256": hashlib.sha256(frozen).hexdigest()}
    assert again == target and second["supersedes"] == superseded
    old_json = target.parent / "M1-qwen3.5-9b.superseded-20260928T120001Z.json"
    old_md = target.parent / "M1-qwen3.5-9b.superseded-20260928T120001Z.md"
    assert old_json.read_bytes() == frozen and old_md.read_bytes() == frozen_md
    assert json.loads(target.read_text())["supersedes"] == superseded
    assert load_ledger(m).data["receipts"]["M1"]["history"] == [superseded]
    ledger = load_ledger(m)
    assert ledger.data["receipts"]["M1"]["sha256"] == file_sha256(target) != record["sha256"]
    assert lifecycle.phase_finished(m, ledger, "M1")  # the new version still finishes the phase
    reissued = target.read_bytes()
    rc, out, _ = run_cli("model-receipt", "--phase", "M1", "--reissue")
    assert rc == 0 and "1/1 accepted" in out
    assert (target.parent / "M1-qwen3.5-9b.superseded-20260928T120002Z.json").read_bytes() == reissued
    assert old_json.read_bytes() == frozen  # every earlier version is still there
    assert len(list(target.parent.glob("*.json"))) == 3
    assert [e["type"] for e in load_ledger(m).data["events"]].count("model_receipt") == 3


def test_two_reissues_within_one_second_never_destroy_a_frozen_receipt(modern, tmp_path, server, monkeypatch):
    m = make_modern(modern, tmp_path, server, tasks=(TASK,), reps=1)
    complete(m, server, "M1")
    _first, target = model_receipt(m, "M1")
    frozen = target.read_bytes()
    freeze_lifecycle_clock(monkeypatch, datetime.datetime(2026, 9, 28, 12, 0, 0, tzinfo=datetime.timezone.utc))
    model_receipt(m, "M1", reissue=True)
    model_receipt(m, "M1", reissue=True)  # the same second
    kept = [p.read_bytes() for p in target.parent.glob("*.json")]
    assert frozen in kept, "the originally frozen receipt was overwritten"


def test_a_receipt_naming_other_evaluations_than_the_ledger_does_not_finish_its_phase(modern, tmp_path, server):
    m = make_modern(modern, tmp_path, server, tasks=(TASK,), reps=1)
    complete(m, server, "M1")
    result, target = model_receipt(m, "M1")
    frozen = target.read_bytes()
    assert lifecycle.phase_finished(m, load_ledger(m), "M1")
    active = [load_ledger(m).active_entry(c.key)["evaluation_id"] for c in m.cells("M1")]
    assert result["evaluation_ids"] == active

    def forge(evaluation_ids) -> None:
        """A receipt file whose recorded sha256 matches, but that names other evaluations."""
        target.write_text(json.dumps({**result, "evaluation_ids": evaluation_ids}, indent=2) + "\n")
        ledger = load_ledger(m)
        ledger.data["receipts"]["M1"]["sha256"] = file_sha256(target)
        ledger.save()

    server.serve(m, "M2")
    for forged in (["e-not-the-ledgers"], [], active + ["e-extra"]):
        forge(forged)
        ledger = load_ledger(m)
        assert validate_mod.validate_campaign(m, phase="M1")["complete"] is True  # the evidence itself is fine
        assert lifecycle.phase_finished(m, ledger, "M1") is None, forged
        with pytest.raises(CampaignStop, match="evidence is not frozen yet"):
            remove_model(m, M1, "free space")
        with pytest.raises(CampaignStop, match="one target at a time: qwen3.5:9b"):
            pull_model(m, "M2")
        assert any(p.startswith("one model at a time: phase(s) ['M1']")
                   for p in launcher.preflight(m, None, ledger=ledger, check_code=False, phase="M2").problems)
    assert server.deletes == [] and server.pulls == [] and M1 in server.models
    target.write_bytes(frozen)
    ledger = load_ledger(m)
    ledger.data["receipts"]["M1"]["sha256"] = file_sha256(target)
    ledger.save()
    assert lifecycle.phase_finished(m, load_ledger(m), "M1")
    assert pull_model(m, "M2")["outcome"] == "pulled"


def test_observed_digests_are_normalized_before_they_are_compared_with_the_pins(modern, tmp_path, server):
    m = make_modern(modern, tmp_path, server, tasks=(TASK,), reps=1)
    server.install_pinned(m, "M1", digest="sha256:" + pin(m, "M1"))  # Ollama spelling with the algorithm
    pf = launcher.preflight(m, None, check_code=False, phase="M1")
    assert pf.ok, pf.problems
    record = pull_model(m, "M1", pull=_never_pull)
    assert record["outcome"] == "reused" and record["digest"] == pin(m, "M1")
    server.serve(m, "M2")
    with pytest.raises(CampaignStop, match="one target at a time: qwen3.5:9b"):  # the pinned, unfinished target
        pull_model(m, "M2")
    with pytest.raises(CampaignStop, match="its evidence is not frozen yet"):  # never 'non-pinned weights'
        remove_model(m, M1, "free space")
    with running_app(m.db_path(), declared_factory()) as (_app, api):
        assert launch(m, api, "M1")["succeeded"] == 1
    receipt = validate_mod.validate_campaign(m, phase="M1")
    assert receipt["complete"] is True, receipt["problems"]
    result, _ = model_receipt(m, "M1")
    assert result["observed_identity"]["digest_matches_pin"] is True
    assert result["observed_identity"]["digests"] == [pin(m, "M1")]
    assert remove_model(m, M1, "finished")["outcome"] == "removed"


@pytest.mark.parametrize("signum", [signal.SIGTERM, signal.SIGHUP], ids=["SIGTERM", "SIGHUP"])
def test_a_smoke_stopped_by_a_signal_stops_its_app_and_is_recorded(modern, tmp_path, server, monkeypatch, signum):
    m = make_modern(modern, tmp_path, server)
    server.install_pinned(m, "M1")
    apps: list[subprocess.Popen] = []
    seen: dict = {}
    received: list[int] = []

    def start_app(_db_path, _port, _log_path):
        apps.append(sleeper())  # a real child process group, as the real app would be
        return apps[-1]

    def wait_healthy(_base, _limit):
        seen["alive"] = lifecycle.live_smoke_apps(m)
        seen["problems"] = launcher.preflight(m, None, check_code=False, phase="M1").problems
        signal.raise_signal(signum)  # the operator's kill / a closed terminal
        raise AssertionError("the signal did not interrupt the smoke")

    monkeypatch.setattr(lifecycle, "_wait_healthy", wait_healthy)
    saved = {sig: signal.getsignal(sig) for sig in (signal.SIGTERM, signal.SIGHUP)}

    def recorder(sig, _frame):  # stands in for the default action (which would end the test run)
        received.append(sig)

    try:
        for sig in saved:
            signal.signal(sig, recorder)
        with pytest.raises(KeyboardInterrupt, match=f"smoke interrupted by signal {int(signum)}"):
            run_smoke(m, "M1", port=free_port(), tasks=[TASK], start_app=start_app)
        restored = {sig: signal.getsignal(sig) for sig in saved}
    finally:
        for sig, handler in saved.items():
            signal.signal(sig, handler)
        for proc in apps:
            reap(proc)
    assert received == []  # the smoke's own handler took the signal
    assert restored == {sig: recorder for sig in saved}  # and the previous handlers are back
    assert len(apps) == 1 and apps[0].returncode == -signal.SIGTERM  # its app's process group was stopped
    assert seen["alive"] == [apps[0].pid]
    assert any(p.startswith(f"a smoke app is still running (process groups [{apps[0].pid}])")
               for p in seen["problems"])
    folder = next(m.runtime_subdir("smoke_dir").glob("M1-*"))
    assert not (folder / "app.pgid").exists() and lifecycle.live_smoke_apps(m) == []
    [record] = load_ledger(m).data["smokes"]
    assert (record["phase"], record["outcome"], record["operational_ok"]) == ("M1", "error", False)
    assert record["failure"] == f"KeyboardInterrupt: smoke interrupted by signal {int(signum)}"
    assert record["finished_at"] and record["ollama_version"] == PINNED_VERSION


@pytest.mark.parametrize("error", [ollama.OllamaError("GET /api/tags: connection refused"),
                                   urllib.error.URLError("connection reset by peer")],
                         ids=["OllamaError", "URLError"])
def test_the_cli_turns_model_server_errors_into_refusals(modern, tmp_path, server, monkeypatch, capsys, error):
    m = make_modern(modern, tmp_path, server)
    run_cli = cli_runner(m, tmp_path, capsys)

    def failing(*_args, **_kwargs):
        raise error

    for name in ("pull_model", "remove_model", "storage_inventory"):
        monkeypatch.setattr(lifecycle, name, failing)
    for argv in (("pull-model", "--phase", "M1", "--api", closed_api()),
                 ("remove-model", "--model", OTHER, "--reason", "r", "--confirm", m.campaign_id, "--api", closed_api()),
                 ("storage-inventory", "--label", "x")):
        rc, _, err = run_cli(*argv)
        assert rc == 3 and err.startswith("refused:") and str(error.args[0]) in err, (argv, err)


# =========================================================================== #
# 12. the historical plan is unchanged
# =========================================================================== #


def test_the_historical_plan_still_behaves_as_before(base, tmp_path, monkeypatch):
    assert base.kind == KIND_HISTORICAL and not base.is_sequential and base.phases == ["A", "B"]
    assert base.pinned_digests() == {} and "roster" not in base.data and "kind" not in base.data
    assert base.data["expected"] == base.expected
    assert set(base.expected) == {"models", "tasks", "cells", "runs_per_cell", "runs_per_model", "total_runs",
                                  "phase_A_cells", "phase_A_runs", "phase_B_cells", "phase_B_runs"}
    model = "qwen2.5-coder:3b"
    m = make_campaign(base, tmp_path, [model], [TASK], 1)
    assert [c.phase for c in m.cells()] == ["A"] and "receipts" not in m.data["runtime"]
    fake = FakeOllama(m.models).install(monkeypatch)
    with running_app(m.db_path(), declared_factory()) as (_app, api):
        assert make_launcher(m, api).run("A", check_code=True) == {
            "submitted": 1, "paused": False, "drained": 0, "skipped": 0, "succeeded": 1}
    ledger = load_ledger(m)
    assert "model" not in ledger.data["launches"][0]
    entry = ledger.active_entry(m.cells()[0].key)
    assert entry["logical_name"] == model and entry["model_digest_at_submit"] == fake.digests[model]
    assert launcher.reference_digests(ledger, m) == launcher.reference_digests(ledger) == {model: fake.digests[model]}
    receipt = validate_mod.validate_campaign(m)
    assert receipt["complete"] is True and "cohort" not in receipt
    assert "models" not in status_mod.campaign_status(m)
    board = analysis.official_baseline(m)
    assert board["report"] == "post-phase0-baseline" and "model_states" not in board
    # model files are only ever managed under a sequential-local plan (the historical plan has no roster)
    for what, action in (("pull-model", lambda: pull_model(m, "A")),
                         ("classify-model", lambda: classify_model(m, "A", "NOT_BENCHMARKED", "r", "e")),
                         ("remove-model", lambda: remove_model(m, model, "free space")),
                         ("smoke", lambda: run_smoke(m, "A", port=free_port(), tasks=[TASK]))):
        with pytest.raises(CampaignStop, match=rf"^{what} applies only to a sequential-local campaign plan .*this "
                                               "plan is historical-replication$"):
            action()
    assert lifecycle.live_smoke_apps(m) == [] and "smoke_dir" not in m.data["runtime"]
    assert "model_status" not in load_ledger(m).data or not load_ledger(m).data["model_status"]


# =========================================================================== #
# final review (RT-1, RT-2, RT-3, RT-8)
# =========================================================================== #


def test_a_derived_plan_that_does_not_own_the_model_files_never_manages_them(modern, tmp_path, server):
    # RT-1: a rehearsal plan derived with the CLI's `derive` names only some campaign
    # targets; it must never pull, remove, classify or smoke (nor remove weights)
    m = make_modern(modern, tmp_path, server)
    data = dict(m.data)
    data.pop("model_files_owner")
    rehearsal = Manifest(data)
    server.install_pinned(m, "M2")
    for action in (lambda: remove_model(rehearsal, M2, "free space"), lambda: pull_model(rehearsal, "M1"),
                   lambda: classify_model(rehearsal, "M2", "LOCAL_RESOURCE_LIMIT", "r", "e"),
                   lambda: lifecycle.remove_weights(rehearsal, str(tmp_path), "r")):
        with pytest.raises(CampaignStop, match="this plan is a derived plan"):
            action()
    assert server.deletes == [] and server.pulls == []


def _weights_dir(home: Path, *parts: str, files: dict) -> Path:
    folder = home.joinpath(*parts)
    for rel, size in files.items():
        target = folder / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(b"\0" * size)
    return folder


def test_remove_weights_never_removes_user_files_beside_or_disguised_as_weights(modern, tmp_path, server, monkeypatch):
    # RT-2: only weight files (by suffix, or large Hugging Face hub blobs) plus model
    # metadata; a 'blobs' folder name or a small non-weight file is never enough
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    m = make_modern(modern, tmp_path, server)
    spoof = _weights_dir(home, ".lmstudio", "models", "me", "project",
                         files={"blobs/notes.txt": 10_000_000, "blobs/dataset.csv": 90_000_000})
    mixed = _weights_dir(home, ".cache", "huggingface", "hub", "models--me--finetune",
                         files={"model.safetensors": 95_000_000, "my-thesis.docx": 5_000_000})
    for path in (spoof, mixed):
        with pytest.raises(CampaignStop, match="neither model weights nor model metadata"):
            lifecycle.remove_weights(m, str(path), "free space")
        assert path.exists()
    ok = _weights_dir(home, ".cache", "huggingface", "hub", "models--acme--m",
                      files={"blobs/0123abcd": 80 * 1024 * 1024, "refs/main": 40, "snapshots/x/config.json": 500})
    record = lifecycle.remove_weights(m, str(ok), "free space")
    assert record["outcome"] == "removed" and not ok.exists() and spoof.exists() and mixed.exists()


def test_remove_weights_refuses_during_campaign_evaluations_unless_a_disk_emergency(modern, tmp_path, server,
                                                                                     monkeypatch):
    # RT-3: never beside a running campaign evaluation, except --during-batch, which
    # records the overlap
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    m = make_modern(modern, tmp_path, server)
    add_in_flight(m, m.cells("M1")[0])
    first = _weights_dir(home, ".lmstudio", "models", "pub", "a", files={"a.gguf": 1_000_000})
    with pytest.raises(CampaignStop, match="--during-batch"):
        lifecycle.remove_weights(m, str(first), "free space")
    assert first.exists()
    record = lifecycle.remove_weights(m, str(first), "disk emergency", during_batch=True)
    assert record["outcome"] == "removed" and record["active_evaluations_during_removal"]
    log = [json.loads(line) for line in (m.runtime_subdir("inventories") / "storage-log.jsonl").read_text().splitlines()]
    assert log[0]["action"] == "remove-weights" and log[0]["active_evaluations_during_removal"]


def test_the_leaderboard_shows_each_models_timeouts_and_agent_errors(modern, tmp_path, server):
    # RT-8: the official leaderboard discloses what drives low scores
    m = make_modern(modern, tmp_path, server, minimum_ranked=1)
    complete(m, server, "M1")
    classify_model(m, "M2", "NOT_BENCHMARKED", "optional in this test", "none")
    board = analysis.official_baseline(m)
    row = next(e for e in board["leaderboard"] if e["agent"] == M1)
    assert {"timeouts", "request_timeout_hits", "agent_errors"} <= set(row)
    assert "timeouts (full request)" in analysis.render_official_baseline(board)
    assert board["provenance"]["model_identity"]["source"].startswith("pinned registry digests")


def test_remove_weights_copies_its_record_into_the_ledger_when_no_launcher_holds_it(modern, tmp_path, server,
                                                                                    monkeypatch):
    # the record carries a 'kind' (weight format) that must not collide with the
    # ledger event's own type argument
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    m = make_modern(modern, tmp_path, server)
    Ledger.open_or_create(m.ledger_path(), campaign_id=m.campaign_id, manifest_sha256=m.sha256,
                          manifest_path="").save()
    folder = _weights_dir(home, ".lmstudio", "models", "pub", "b", files={"b.gguf": 1_000_000})
    lifecycle.remove_weights(m, str(folder), "free space")
    ledger = json.loads(m.ledger_path().read_text())
    assert ledger["model_deletions"][-1]["runtime"] == "lm-studio" and ledger["model_deletions"][-1]["kind"]
    assert ledger["events"][-1]["type"] == "model_deletion"
