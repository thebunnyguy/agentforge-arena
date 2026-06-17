"""Agents (framework: MockAgent, ScriptAgent, ... — no paid APIs).

An agent mutates a workspace (a writable copy of the task snapshot) to attempt
the task. It must touch only allowed paths; scope violations are caught later by
the diff/scope gate, not here. Agents return an AgentOutcome whose transcript is
hashed for determinism detection.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from .sandbox import Sandbox
    from .task import Task


@dataclass
class AgentOutcome:
    """What an agent run produced, for status + determinism tracking.

    transcript    : a stable textual record of what the agent did (commands /
                    file writes). Hashed to detect deterministic agents.
    errored       : True if the agent itself failed to produce a usable attempt
                    (maps to RunStatus.AGENT_ERROR — counts against the agent).
    infra_failed  : True if an INFRASTRUCTURE failure prevented the attempt
                    (e.g. the model server is unreachable). Maps to
                    RunStatus.INFRA_FAILURE — VOIDED, excluded from n, never
                    held against the agent (framework §1). Takes precedence over
                    `errored` when both are set.
    """

    transcript: str = ""
    errored: bool = False
    infra_failed: bool = False


@runtime_checkable
class Agent(Protocol):
    """Anything that can attempt a task by editing a workspace in place."""

    name: str

    def act(self, workspace: Path, task: "Task", sandbox: "Sandbox") -> AgentOutcome:
        ...


@dataclass
class MockAgent:
    """Deterministic canned agent: writes/deletes a fixed set of files.

    writes  : {relative_path: file_text} written into the workspace.
    deletes : relative paths removed from the workspace.
    """

    name: str
    writes: dict[str, str] = field(default_factory=dict)
    deletes: tuple[str, ...] = ()

    def act(self, workspace: Path, task: "Task", sandbox: "Sandbox") -> AgentOutcome:
        for rel, text in self.writes.items():
            target = workspace / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text)
        for rel in self.deletes:
            target = workspace / rel
            if target.exists():
                target.unlink()
        transcript = "MockAgent\n" + "\n".join(
            f"write {rel}\n{text}" for rel, text in sorted(self.writes.items())
        ) + "".join(f"\ndelete {rel}" for rel in self.deletes)
        return AgentOutcome(transcript=transcript)


@dataclass
class SequenceAgent:
    """Cycles through member agents across successive runs (for variance demos).

    The i-th call to act() delegates to members[i % len(members)]. Stateful by
    design: pass the SAME instance to run_group so its outputs vary run to run.
    """

    name: str
    members: list[Agent]
    _i: int = 0

    def act(self, workspace: Path, task: "Task", sandbox: "Sandbox") -> AgentOutcome:
        member = self.members[self._i % len(self.members)]
        self._i += 1
        out = member.act(workspace, task, sandbox)
        return AgentOutcome(transcript=f"[{member.name}] {out.transcript}", errored=out.errored)


@dataclass
class ScriptAgent:
    """Runs a fixed list of shell commands in the workspace via the sandbox.

    Each command runs with cwd=workspace under the sandbox's isolation and
    timeout. A non-zero exit on any command sets errored=True.
    """

    name: str
    commands: list[str]

    def act(self, workspace: Path, task: "Task", sandbox: "Sandbox") -> AgentOutcome:
        lines: list[str] = ["ScriptAgent"]
        errored = False
        for cmd in self.commands:
            res = sandbox.run(cmd, cwd=workspace, timeout_s=task.timeout_s)
            lines.append(f"$ {cmd} -> exit {res.exit_code}")
            if res.exit_code != 0:
                errored = True
                break
        return AgentOutcome(transcript="\n".join(lines), errored=errored)
