"""Offline tests for OpenAICompatAgent (LM Studio / llama.cpp / vLLM / Ollama
/v1). The HTTP call is injected, so no server is needed; these confirm the
agent reuses OllamaAgent's parsing and infra-failure handling, and that the
shared /v1/chat/completions payload is well-formed."""

from __future__ import annotations

import json
import shutil
import urllib.error
from pathlib import Path

import pytest

from afa_runner import OpenAICompatAgent, load_task, openai_chat_generate
from afa_runner.diffing import capture_diff

_ROOT = Path(__file__).resolve().parent.parent.parent


@pytest.fixture
def task():
    return load_task(_ROOT / "tasks" / "fix-list-dedup")


@pytest.fixture
def workspace(task, tmp_path):
    ws = tmp_path / "w"
    shutil.copytree(task.snapshot_dir, ws)
    return ws


def test_default_base_url_is_lm_studio():
    agent = OpenAICompatAgent(name="lmstudio", model="some-model")
    assert agent.base_url == "http://localhost:1234"


def test_writes_parsed_code_via_injected_generate(task, workspace):
    # Reuses OllamaAgent's parsing: a "# FILE:" marker inside a fenced block.
    fixed = (
        "# FILE: listkit/dedup.py\n```python\n"
        "def dedup(items):\n"
        "    seen = set(); out = []\n"
        "    for x in items:\n"
        "        if x not in seen:\n"
        "            seen.add(x); out.append(x)\n"
        "    return out\n```\n"
    )
    agent = OpenAICompatAgent(name="lmstudio", model="m", generate=lambda p, s: fixed)
    outcome = agent.act(workspace, task, None)
    assert outcome.errored is False and outcome.infra_failed is False
    diff = capture_diff(task.snapshot_dir, workspace, task.protected_paths, task.editable_paths)
    assert "listkit/dedup.py" in diff.changed
    assert "list(set(items))" not in diff.changed["listkit/dedup.py"]


def test_transport_error_is_infra_not_agent_loss(task, workspace):
    def down(prompt, seed):
        raise urllib.error.URLError("connection refused")

    agent = OpenAICompatAgent(name="lmstudio", model="m", generate=down)
    outcome = agent.act(workspace, task, None)
    assert outcome.infra_failed is True and outcome.errored is False


def test_openai_payload_shape_and_response_parsing(monkeypatch):
    """openai_chat_generate posts the chat schema and reads choices[].message.content."""
    captured = {}

    class _Resp:
        def __init__(self, data):
            self._data = data
        def read(self):
            return self._data
        def __enter__(self):
            return self
        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["body"] = json.loads(req.data.decode())
        return _Resp(json.dumps(
            {"choices": [{"message": {"role": "assistant", "content": "HELLO"}}]}
        ).encode())

    monkeypatch.setattr("afa_runner.agents_openai.urllib.request.urlopen", fake_urlopen)
    out = openai_chat_generate(
        "hi", 7, model="m", base_url="http://localhost:1234", temperature=0.5, timeout=5
    )
    assert out == "HELLO"
    assert captured["url"].endswith("/v1/chat/completions")
    assert captured["body"]["messages"][0]["content"] == "hi"
    assert captured["body"]["model"] == "m"
    assert captured["body"]["seed"] == 7
