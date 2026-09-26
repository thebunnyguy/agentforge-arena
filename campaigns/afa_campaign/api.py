"""Minimal client for the running AgentForge app's Jobs API (stdlib only).

Campaign evaluations are created ONLY through ``POST /api/v1/jobs`` so every run
goes through the ATLAS lifecycle: evaluation identity + creation snapshot ->
evaluation trials -> worker -> raw runs -> reports.
"""

from __future__ import annotations

import http.client
import json
import urllib.error
import urllib.request
from typing import Any


class ApiError(RuntimeError):
    def __init__(self, message: str, *, status: int | None = None, body: Any = None) -> None:
        super().__init__(message)
        self.status = status
        self.body = body


class ApiUnreachable(ApiError):
    """Transport-level failure: the outcome of a mutating call is UNKNOWN."""


class ApiNotSent(ApiUnreachable):
    """The connection was refused: the request never reached the app, so a
    mutating call definitely did NOT happen."""


class AgentForgeApi:
    def __init__(self, base_url: str, *, timeout: float = 30.0) -> None:
        self.base = base_url.rstrip("/") + "/api/v1"
        self.timeout = timeout

    def _call(self, method: str, path: str, body: Any = None) -> Any:
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = urllib.request.Request(
            self.base + path, method=method, data=data,
            headers={"content-type": "application/json", "accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            payload: Any
            try:
                payload = json.loads(exc.read() or b"null")
            except ValueError:
                payload = None
            raise ApiError(f"{method} {path} -> HTTP {exc.code}: {payload}", status=exc.code, body=payload) from None
        except (urllib.error.URLError, OSError, TimeoutError, http.client.HTTPException) as exc:
            reason = exc.reason if isinstance(exc, urllib.error.URLError) else exc
            if isinstance(reason, ConnectionRefusedError):
                raise ApiNotSent(f"{method} {path}: {exc}") from None
            # includes a response cut off mid-body (IncompleteRead): outcome unknown
            raise ApiUnreachable(f"{method} {path}: {exc}") from None
        try:
            return json.loads(raw or b"null")
        except ValueError as exc:
            raise ApiError(f"{method} {path}: non-JSON response") from exc

    def health(self) -> dict:
        return self._call("GET", "/healthz")

    def create_job(self, body: dict) -> dict:
        return self._call("POST", "/jobs", body)

    def get_job(self, evaluation_id: str) -> dict:
        return self._call("GET", f"/jobs/{evaluation_id}")

    def list_jobs(self) -> list[dict]:
        return (self._call("GET", "/jobs") or {}).get("jobs", [])

    def report(self, evaluation_id: str) -> dict:
        return self._call("GET", f"/jobs/{evaluation_id}/report.json")

    def report_markdown_url(self, evaluation_id: str) -> str:
        return f"{self.base}/jobs/{evaluation_id}/report.md"

    def resume(self, evaluation_id: str) -> dict:
        return self._call("POST", f"/jobs/{evaluation_id}/resume")
