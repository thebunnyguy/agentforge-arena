"""Execution sandbox (framework §9).

A Sandbox runs a command in an isolated, fresh workspace with a wall-clock
timeout and resource discipline. v0.1 ships LocalSandbox (subprocess + temp
dir): real per-run workspace isolation and timeouts, but NOT security isolation.
That is sufficient for trusted local agents (Mock/Script/local CLI). A
DockerSandbox implementing the same Protocol is the drop-in for untrusted agents
(deferred). Everything here is stdlib-only and offline.
"""

from __future__ import annotations

import os
import signal
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class CommandResult:
    """Result of one command execution."""

    cmd: str
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int
    timed_out: bool


@runtime_checkable
class Sandbox(Protocol):
    def run(
        self,
        cmd: str | list[str],
        cwd: Path,
        timeout_s: int,
        env: dict[str, str] | None = None,
    ) -> CommandResult:
        ...


class LocalSandbox:
    """Subprocess-backed sandbox. Each run executes in the given cwd.

    Reproducibility env defaults (framework §9): PYTHONHASHSEED=0, TZ=UTC,
    LANG/LC_ALL=C.UTF-8, PYTHONDONTWRITEBYTECODE=1, applied on top of a minimal
    inherited environment; caller-supplied env overrides these.
    """

    #: Deterministic environment overlay applied to every command.
    BASE_ENV: dict[str, str] = {
        "PYTHONHASHSEED": "0",
        "TZ": "UTC",
        "LANG": "C.UTF-8",
        "LC_ALL": "C.UTF-8",
        "PYTHONDONTWRITEBYTECODE": "1",
    }

    def __init__(self, inherit_path: bool = True) -> None:
        """inherit_path: keep the host PATH (needed to find python/pytest)."""
        self.inherit_path = inherit_path

    def run(
        self,
        cmd: str | list[str],
        cwd: Path,
        timeout_s: int,
        env: dict[str, str] | None = None,
    ) -> CommandResult:
        """Run cmd in cwd with a timeout.

        - A string cmd runs through the shell (shell=True); a list runs directly.
        - Build the environment from BASE_ENV (+ PATH if inherit_path) then apply
          caller env. Do NOT leak the full host environment by default.
        - Enforce timeout_s with subprocess timeout; on expiry kill the process
          group, return exit_code=-1, timed_out=True, partial stdout/stderr.
        - Capture stdout/stderr as text (utf-8, errors="replace").
        - duration_ms is wall-clock for the call.
        Implements framework §9 (agent execution / command logs).
        """
        run_env = self._build_env(env)

        # A string cmd goes through the shell; a list runs the program directly.
        shell = isinstance(cmd, str)
        # Label for the result. For a list cmd we join with spaces purely for the
        # human-readable record; the actual invocation is argv-direct (no shell).
        cmd_label = cmd if isinstance(cmd, str) else " ".join(cmd)

        start = time.monotonic()
        # start_new_session=True puts the child in its own process group/session so
        # that on timeout we can SIGKILL the whole tree (the child plus anything it
        # spawned), not just the immediate process — see framework §9 (SIGKILL).
        proc = subprocess.Popen(
            cmd,
            cwd=str(cwd),
            env=run_env,
            shell=shell,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            start_new_session=True,
        )

        timed_out = False
        try:
            stdout, stderr = proc.communicate(timeout=timeout_s)
            exit_code = proc.returncode
        except subprocess.TimeoutExpired:
            timed_out = True
            self._kill_process_group(proc)
            # Reap and collect whatever partial output was buffered. The pipes are
            # still open after the kill; a second communicate() drains them and
            # waits for the now-dead process so no zombie/leaked fd remains.
            try:
                stdout, stderr = proc.communicate()
            except Exception:
                stdout, stderr = "", ""
            exit_code = -1

        duration_ms = int((time.monotonic() - start) * 1000)

        return CommandResult(
            cmd=cmd_label,
            exit_code=exit_code,
            stdout=stdout or "",
            stderr=stderr or "",
            duration_ms=duration_ms,
            timed_out=timed_out,
        )

    def _build_env(self, env: dict[str, str] | None) -> dict[str, str]:
        """Compose the child environment.

        Order (later wins): BASE_ENV overlay, then host PATH if inherit_path,
        then caller-supplied env. The full host environment is never inherited
        wholesale, so runs stay deterministic and isolated.
        """
        run_env: dict[str, str] = dict(self.BASE_ENV)
        if self.inherit_path:
            host_path = os.environ.get("PATH")
            if host_path is not None:
                run_env["PATH"] = host_path
        if env:
            run_env.update(env)
        return run_env

    @staticmethod
    def _kill_process_group(proc: "subprocess.Popen") -> None:
        """SIGKILL the child's process group, falling back to the process itself.

        The child was started with start_new_session=True, so its PID is the
        process-group leader; killing the group reaps grandchildren too.
        """
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            # Group already gone, or we cannot signal it; kill the leader directly.
            try:
                proc.kill()
            except ProcessLookupError:
                pass
