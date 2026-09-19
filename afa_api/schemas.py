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
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .evidence import RESERVED_AGENT_NAMES

# Job lifecycle states (worker state machine). queued -> running -> terminal.
JobStatus = Literal["queued", "running", "succeeded", "failed", "canceled"]
TERMINAL_STATES: frozenset[str] = frozenset({"succeeded", "failed", "canceled"})

# Backend kinds we support locally. Default is the deterministic offline mock.
BackendKind = Literal["mock", "ollama", "openai_compat"]
EvaluationMode = Literal["fresh", "reuse"]
JobMode = Literal["fresh", "reuse", "legacy"]

DEFAULT_BACKEND_URLS: dict[str, str] = {
    "ollama": "http://localhost:11434",
    "openai_compat": "http://localhost:1234",
}


# --------------------------------------------------------------------------- #
# Job creation / params
# --------------------------------------------------------------------------- #

class Backend(BaseModel):
    """Which local engine drives the agent. Local-only by design; no hosted
    paid APIs. ``mock`` needs no server.

    Credential-bearing URLs are rejected rather than persisted. The local
    adapters intentionally do not accept an API-key field.
    """

    model_config = ConfigDict(extra="forbid")

    kind: BackendKind = "mock"
    base_url: str | None = None

    @field_validator("base_url")
    @classmethod
    def reject_credentials(cls, value: str | None) -> str | None:
        if value is None:
            return value
        parsed = urlsplit(value)
        if parsed.username or parsed.password:
            raise ValueError("backend base_url must not contain credentials")
        if parsed.query or parsed.fragment:
            raise ValueError(
                "backend base_url must not contain query or fragment secrets"
            )
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ValueError("backend base_url must be an absolute http(s) URL")
        return value.rstrip("/")


class JobParams(BaseModel):
    """Parameters of an evaluation job, persisted in ``params_json``.

    A new job is fresh by default. Reuse is explicit and names its source
    evaluation; resume is an operation on an existing job, never a new-job
    flag.
    """

    backend: Backend = Field(default_factory=Backend)
    model: str = "mock"
    name: str | None = None
    tasks: list[str] = Field(default_factory=list)
    repeats: int = Field(default=1, ge=1)
    base_seed: int = 1000
    temperature: float = 0.6
    request_timeout_s: int = Field(default=180, ge=1)
    mode: EvaluationMode = "fresh"
    source_evaluation_id: str | None = None

    @field_validator("model")
    @classmethod
    def reject_reserved_model_name(cls, value: str) -> str:
        # The synthetic oracle/noop baselines own these names; a real evaluation
        # persisted under one would blend into (and corrupt) the bookends.
        if value in RESERVED_AGENT_NAMES:
            raise ValueError("model name is reserved for a synthetic baseline")
        return value


class JobCreate(JobParams):
    """POST /api/v1/jobs body. Same shape as JobParams (flat, matches the plan
    example payload)."""

    model_config = ConfigDict(extra="forbid")


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
    """A durable evaluation/job row projected to JSON."""

    id: str
    status: JobStatus
    mode: JobMode = "fresh"
    source_evaluation_id: str | None = None
    snapshot: dict[str, Any] | None = None
    cancel_requested: bool = False
    # None (with params_status "unverifiable") when the persisted parameters are
    # malformed: a malformed row is listable but its parameters are never
    # replaced by defaults, and it is never executable.
    params: JobParams | None = None
    params_status: Literal["available", "unverifiable"] = "available"
    params_error: str | None = None
    # What the evaluation snapshot recorded as its backend (None if unknown) and
    # the evidence class that implies: mock runs are synthetic dev/test evidence
    # and are excluded from the default benchmark aggregates.
    backend_kind: Literal["mock", "ollama", "openai_compat"] | None = None
    evidence_class: Literal["real", "synthetic", "unknown"] = "unknown"
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

    @field_validator("ollama_base_url", "openai_base_url")
    @classmethod
    def reject_url_secrets(cls, value: str | None) -> str | None:
        if value is None:
            return value
        parsed = urlsplit(value)
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("backend settings URL must not contain credentials or secrets")
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ValueError("backend settings URL must be an absolute http(s) URL")
        return value.rstrip("/")


def reject_secret_fields(data: Any, *, path: str = "settings") -> None:
    """Reject secret-shaped settings instead of persisting then redacting them."""
    if isinstance(data, dict):
        for key, value in data.items():
            if key.lower() in SECRET_KEYS and value not in (None, "", "***"):
                raise ValueError(f"unsupported credential-bearing field: {path}.{key}")
            reject_secret_fields(value, path=f"{path}.{key}")
    elif isinstance(data, list):
        for index, value in enumerate(data):
            reject_secret_fields(value, path=f"{path}[{index}]")


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

class BackendVerifyRequest(Backend):
    """Local transport probe request with the same secret/URL discipline."""


class BackendVerifyResponse(BaseModel):
    kind: BackendKind
    ok: bool
    detail: str
    models: list[str] = Field(default_factory=list)
