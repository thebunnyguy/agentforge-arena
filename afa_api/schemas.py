"""Pydantic request/response models for the JOBS control plane (Phase 4-6).

These are projection/transport models only — no scoring or statistics live here
(that all stays in the frozen kernel/runner). A job's parameters are stored in
``evaluation_jobs.params_json`` and round-trip through :class:`JobParams`.

Secrets discipline: the OpenAI-compatible local agent does not send an
Authorization header (plan Phase 7), so an ``api_key`` is never used for
generation. If one is ever supplied it is REDACTED on the way out
(:func:`redact_settings`) and never echoed back.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

# Job lifecycle states (worker state machine). queued -> running -> terminal.
JobStatus = Literal["queued", "running", "succeeded", "failed", "canceled"]
TERMINAL_STATES: frozenset[str] = frozenset({"succeeded", "failed", "canceled"})

# Backend kinds we support locally. Default is the deterministic offline mock.
BackendKind = Literal["mock", "ollama", "openai_compat"]


# --------------------------------------------------------------------------- #
# Job creation / params
# --------------------------------------------------------------------------- #

class Backend(BaseModel):
    """Which local engine drives the agent. Local-only by design; no hosted
    paid APIs. ``mock`` needs no server."""

    kind: BackendKind = "mock"
    base_url: str | None = None


class JobParams(BaseModel):
    """Parameters of an evaluation job. Persisted verbatim as ``params_json``.

    A job is one model evaluated over ``tasks`` x ``repeats`` units. ``model``
    is the agent name stamped onto ``runs.agent``.
    """

    backend: Backend = Field(default_factory=Backend)
    model: str = "mock"
    name: str | None = None
    tasks: list[str] = Field(default_factory=list)
    repeats: int = Field(default=1, ge=1)
    base_seed: int = 1000
    temperature: float = 0.6
    request_timeout_s: int = Field(default=180, ge=1)


class JobCreate(JobParams):
    """POST /api/v1/jobs body. Same shape as JobParams (flat, matches the plan
    example payload)."""


# --------------------------------------------------------------------------- #
# Job + event responses
# --------------------------------------------------------------------------- #

class JobCounters(BaseModel):
    total_runs: int = 0
    completed_runs: int = 0
    passed_runs: int = 0
    voided_runs: int = 0
    failed_runs: int = 0
    reused_runs: int = 0  # units skipped because a prior run already existed


class Job(BaseModel):
    """A job row projected to JSON. ``params`` is the parsed JobParams."""

    id: str
    status: JobStatus
    cancel_requested: bool = False
    params: JobParams
    counters: JobCounters
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    error_message: str | None = None


class JobList(BaseModel):
    jobs: list[Job]


class JobEvent(BaseModel):
    """One row of ``job_events``. ``seq`` is monotonic per job (the SSE id)."""

    job_id: str
    seq: int
    ts: str
    type: str
    payload: dict[str, Any] | None = None


class JobEventList(BaseModel):
    job_id: str
    events: list[JobEvent]


# --------------------------------------------------------------------------- #
# Settings
# --------------------------------------------------------------------------- #

# Keys whose values must never be echoed back to the client.
SECRET_KEYS: frozenset[str] = frozenset({"api_key", "apikey", "token", "secret"})


class Settings(BaseModel):
    """App settings blob (stored as ``app_settings.settings_json``).

    Free-form by intent (the UI evolves), with a few well-known fields. Secret
    fields are redacted on read (see :func:`redact_settings`).
    """

    ollama_base_url: str = "http://localhost:11434"
    openai_base_url: str | None = None
    default_backend: BackendKind = "mock"
    default_temperature: float = 0.6
    default_repeats: int = Field(default=1, ge=1)
    default_request_timeout_s: int = Field(default=180, ge=1)
    extra: dict[str, Any] = Field(default_factory=dict)


def redact_settings(data: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of a settings dict with any secret-looking field redacted.

    Recurses one level into ``extra``. The presence of a secret is signalled
    (``"***"``) but the value never leaves the server.
    """
    out: dict[str, Any] = {}
    for key, value in data.items():
        if key.lower() in SECRET_KEYS and value not in (None, ""):
            out[key] = "***"
        elif key == "extra" and isinstance(value, dict):
            out[key] = redact_settings(value)
        else:
            out[key] = value
    return out


# --------------------------------------------------------------------------- #
# Backend verification
# --------------------------------------------------------------------------- #

class BackendVerifyRequest(BaseModel):
    kind: BackendKind = "mock"
    base_url: str | None = None


class BackendVerifyResponse(BaseModel):
    kind: BackendKind
    ok: bool
    detail: str
    models: list[str] = Field(default_factory=list)
