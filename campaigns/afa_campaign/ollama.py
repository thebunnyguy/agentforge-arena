"""External Ollama model inventory and model warm-up (stdlib only).

AgentForge persists the BACKEND KIND of every run (``runs.backend_kind``) but not
the identity of the served weights. The campaign therefore snapshots Ollama's
own inventory (name, digest, size, modified time, details) before each launch
and refuses to continue if a roster model's digest changes mid-campaign. This is
an EXTERNAL snapshot, reported separately from AgentForge's persisted
provenance; nothing here is invented - fields Ollama does not return are
recorded as absent.
"""

from __future__ import annotations

import http.client
import json
import urllib.error
import urllib.request
from typing import Any

from .ledger import utc_now


class OllamaError(RuntimeError):
    pass


def _call(base_url: str, method: str, path: str, body: Any = None, timeout: float = 30.0) -> Any:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request = urllib.request.Request(
        base_url.rstrip("/") + path, method=method, data=data,
        headers={"content-type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read() or b"null")
    except urllib.error.HTTPError as exc:
        raise OllamaError(f"{method} {path} -> HTTP {exc.code}") from None
    except (urllib.error.URLError, OSError, TimeoutError, ValueError, http.client.HTTPException) as exc:
        raise OllamaError(f"{method} {path}: {exc}") from None


_SHOW_FIELDS = ("modified_at", "details", "capabilities")


def inventory(base_url: str, models: list[str]) -> dict:
    """Snapshot what Ollama reports for each roster model (exact names only)."""
    version = _call(base_url, "GET", "/api/version") or {}
    tags = (_call(base_url, "GET", "/api/tags") or {}).get("models", [])
    by_name = {m.get("name"): m for m in tags if isinstance(m, dict)}
    out: dict[str, dict] = {}
    for model in models:
        tag = by_name.get(model)
        if tag is None:
            out[model] = {"present": False}
            continue
        entry = {
            "present": True,
            "name": tag.get("name"),
            "model": tag.get("model"),
            "digest": tag.get("digest"),
            "size": tag.get("size"),
            "modified_at": tag.get("modified_at"),
            "details": tag.get("details"),
        }
        try:
            show = _call(base_url, "POST", "/api/show", {"model": model}) or {}
        except OllamaError as exc:
            entry["show_error"] = str(exc)
        else:
            entry["show"] = {k: show.get(k) for k in _SHOW_FIELDS if k in show}
            info = show.get("model_info")
            if isinstance(info, dict):
                entry["show"]["model_info"] = {
                    k: v for k, v in info.items()
                    if isinstance(v, (str, int, float, bool)) and "." in k and not k.startswith("tokenizer")
                }
        out[model] = entry
    return {
        "captured_at": utc_now(),
        "source": "external Ollama inventory snapshot (not AgentForge-persisted provenance)",
        "base_url": base_url,
        "ollama_version": version.get("version"),
        "models": out,
        "missing": [m for m in models if not out[m]["present"]],
        "unrequested_local_models": sorted(n for n in by_name if n and n not in models),
    }


def digests(snapshot: dict) -> dict[str, str | None]:
    return {name: entry.get("digest") for name, entry in snapshot.get("models", {}).items()}


def warm_up(base_url: str, model: str, *, keep_alive: str = "30m", timeout: float = 600.0) -> None:
    """Load a model into memory before its first campaign trial.

    Loading counts toward a trial's wall-clock budget (tasks allow 20-120 s), so
    a cold load inside a trial could be scored as a TIMEOUT that says nothing
    about the model. An empty-prompt generate loads the model and returns
    without sampling; it creates no AgentForge evidence.
    """
    _call(base_url, "POST", "/api/generate",
          {"model": model, "prompt": "", "keep_alive": keep_alive, "stream": False}, timeout=timeout)


def probe(base_url: str, model: str | None = None, *, timeout: float = 60.0) -> None:
    """Is the server answering AND generating? /api/version and /api/ps can keep
    answering while generation is stuck, so when a model is given this also asks
    it for a single token (after trials that ran the full request timeout, a
    stalled server and a slow model look alike in the run record)."""
    _call(base_url, "GET", "/api/version", timeout=15.0)
    _call(base_url, "GET", "/api/ps", timeout=15.0)
    if model:
        _call(base_url, "POST", "/api/generate",
              {"model": model, "prompt": "Reply with OK.", "stream": False, "keep_alive": "30m",
               "options": {"num_predict": 1}}, timeout=timeout)
