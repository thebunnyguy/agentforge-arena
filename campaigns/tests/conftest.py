"""Campaign tooling tests: every database is a scratch copy or a fresh file; the
committed evidence DB is only ever read, and a session guard proves it. No test
may reach a real model server or a real app: the HTTP clients refuse the real
services' ports (a real Ollama and a real dry run may be live on this machine)."""

from __future__ import annotations

import hashlib
import urllib.request
from urllib.parse import urlsplit

import pytest

from afa_campaign import api as api_mod
from afa_campaign import lifecycle, ollama, paths

# Ollama's port and the app ports a real campaign / dry run / smoke uses (manifest
# default 8000, runbook rehearsal 8790, a live rehearsal on 8791, smoke app 8792).
REAL_SERVICE_PORTS = {11434, 8000, 8790, 8791, 8792}


@pytest.fixture(scope="session", autouse=True)
def _historical_evidence_is_byte_identical():
    before = hashlib.sha256(paths.EVIDENCE_DB.read_bytes()).hexdigest()
    yield
    assert hashlib.sha256(paths.EVIDENCE_DB.read_bytes()).hexdigest() == before


def _refuse_real_services(url: str) -> None:
    port = urlsplit(url).port
    if port in REAL_SERVICE_PORTS:
        raise AssertionError(f"a test tried to contact a real service at {url}; fake it")


@pytest.fixture(autouse=True)
def _no_real_model_server_or_app(monkeypatch):
    real_ollama_call = ollama._call
    real_api_call = api_mod.AgentForgeApi._call

    def ollama_call(base_url, *args, **kwargs):
        _refuse_real_services(base_url)
        return real_ollama_call(base_url, *args, **kwargs)

    def api_call(self, *args, **kwargs):
        _refuse_real_services(self.base)
        return real_api_call(self, *args, **kwargs)

    monkeypatch.setattr(ollama, "_call", ollama_call)
    monkeypatch.setattr(api_mod.AgentForgeApi, "_call", api_call)

    # every other HTTP path (the model-lifecycle helpers: pull, delete, tags, ps,
    # health polls) goes through urllib.request.urlopen: refuse the real ports there too
    real_urlopen = urllib.request.urlopen

    def urlopen(url, *args, **kwargs):
        _refuse_real_services(url.full_url if isinstance(url, urllib.request.Request) else str(url))
        return real_urlopen(url, *args, **kwargs)

    monkeypatch.setattr(urllib.request, "urlopen", urlopen)

    def no_real_app(*_args, **_kwargs):
        raise AssertionError("a test tried to start the real afa_app.py; pass start_app= a fake")

    monkeypatch.setattr(lifecycle, "_start_app", no_real_app)
