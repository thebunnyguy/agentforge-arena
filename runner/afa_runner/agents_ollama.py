"""A real, offline coding agent backed by a locally-served open-weights model
via Ollama (no paid APIs).

OllamaAgent is a single-shot file-edit agent: it reads the task's editable
source files, prompts a local model (e.g. llama3.2) to return corrected file
contents, parses the fenced code blocks, and writes them back into its
workspace. The clean-room grader and the scope gate judge the result — this
adapter only ever writes inside its own workspace (path-traversal is refused);
it does NOT silently sanitize out-of-scope edits, so a model that tries to touch
a protected file is honestly penalized by the scope gate.

The HTTP call is injectable (`generate=`) so the unit tests run fully offline
and deterministically without Ollama.
"""

from __future__ import annotations

import http.client
import json
import re
import socket
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Callable

from .agents import AgentOutcome

# Transport-level failures that mean the model SERVER could not be reached or
# did not respond — infrastructure, not the agent getting the answer wrong.
# These map to RunStatus.INFRA_FAILURE (voided), never an agent loss (§1).
_INFRA_ERRORS: tuple[type[BaseException], ...] = (
    urllib.error.URLError,        # incl. ConnectionRefusedError (server down)
    ConnectionError,
    TimeoutError,
    socket.timeout,
    http.client.HTTPException,
)
from .diffing import (
    _glob_matches,
    path_is_always_protected,
    path_is_protected,
    snapshot_tree,
)

if TYPE_CHECKING:
    from .sandbox import Sandbox
    from .task import Task

# A fenced code block, optionally tagged ```python / ```py.
_CODE_BLOCK_RE = re.compile(r"```(?:[a-zA-Z0-9_+-]*)\s*\n(.*?)```", re.DOTALL)
# A file path token ending in .py (the model labels blocks with these).
_PATH_RE = re.compile(r"([A-Za-z0-9_][A-Za-z0-9_./-]*\.py)")

#: Generate signature: (prompt, seed) -> model response text.
GenerateFn = Callable[[str, int], str]


def ollama_generate(
    prompt: str,
    seed: int,
    *,
    model: str,
    base_url: str,
    temperature: float,
    timeout: float,
) -> str:
    """Call Ollama's /api/generate (stdlib urllib, offline). Returns the
    completion text. Raises urllib.error.URLError if Ollama is unreachable."""
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": temperature, "seed": seed},
    }
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        base_url.rstrip("/") + "/api/generate",
        data=data,
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    return body.get("response", "")


@dataclass
class OllamaAgent:
    """A local-LLM coding agent. Implements the Agent protocol.

    The sampling seed varies per call (base_seed + call index) so repeated runs
    in a group produce genuinely different attempts — the variance the Wilson
    interval / stability / pass@k were built to measure — while staying
    reproducible given base_seed (each seed is recorded in the transcript).
    """

    name: str
    model: str = "llama3.2:latest"
    base_url: str = "http://localhost:11434"
    temperature: float = 0.6
    base_seed: int = 1000
    request_timeout: float = 180.0
    generate: GenerateFn | None = None   # injected in tests; default hits Ollama
    _call: int = 0

    def act(self, workspace: Path, task: "Task", sandbox: "Sandbox") -> AgentOutcome:
        workspace = Path(workspace)
        targets = self._editable_files(workspace, task)
        prompt = self._build_prompt(task, targets)

        seed = self.base_seed + self._call
        self._call += 1

        gen = self.generate or self._default_generate
        try:
            response = gen(prompt, seed)
        except _INFRA_ERRORS as exc:
            # The model server is unreachable / timed out / dropped the
            # connection. This is INFRASTRUCTURE, not the agent getting the
            # answer wrong: signal infra_failed so the run is VOIDED (excluded
            # from n), never counted as a functional failure (framework §1).
            return AgentOutcome(
                transcript=f"OllamaAgent INFRA seed={seed}: {type(exc).__name__}: {exc}",
                infra_failed=True,
            )
        except Exception as exc:  # genuine agent-side failure
            return AgentOutcome(
                transcript=f"OllamaAgent ERROR seed={seed}: {type(exc).__name__}: {exc}",
                errored=True,
            )

        written = self._apply(response, workspace, targets)
        transcript = (
            f"OllamaAgent model={self.model} seed={seed} temp={self.temperature}\n"
            f"WROTE={sorted(written)}\n--- RESPONSE ---\n{response}"
        )
        # No code parsed => no edit => empty diff (the diff_exists gate fails).
        return AgentOutcome(transcript=transcript, errored=False)

    # -- internals ---------------------------------------------------------- #

    def _default_generate(self, prompt: str, seed: int) -> str:
        return ollama_generate(
            prompt,
            seed,
            model=self.model,
            base_url=self.base_url,
            temperature=self.temperature,
            timeout=self.request_timeout,
        )

    def _editable_files(self, workspace: Path, task: "Task") -> dict[str, str]:
        """Source files the agent is allowed to change (within editable_paths,
        not protected, not auto-executed). Shown to the model as context."""
        out: dict[str, str] = {}
        for rel, content in snapshot_tree(workspace).items():
            if path_is_always_protected(rel):
                continue
            if path_is_protected(rel, task.protected_paths):
                continue
            if task.editable_paths and not any(
                _glob_matches(rel, g) for g in task.editable_paths
            ):
                continue
            out[rel] = content
        return dict(sorted(out.items()))

    def _build_prompt(self, task: "Task", targets: dict[str, str]) -> str:
        files = "\n".join(
            f"--- FILE: {rel} ---\n{content}" for rel, content in targets.items()
        )
        return (
            "You are an autonomous coding agent fixing a bug in a Python package.\n\n"
            f"TASK: {task.description}\n\n"
            "EDITABLE FILES (current contents):\n\n"
            f"{files}\n\n"
            "INSTRUCTIONS: For EACH file you change, output a line exactly\n"
            "'# FILE: <path>' followed immediately by a fenced ```python code "
            "block containing the COMPLETE corrected file. Only include files you "
            "actually change. Do not modify test files. Output nothing else."
        )

    def _apply(self, response: str, workspace: Path, targets: dict[str, str]) -> list[str]:
        """Parse fenced code blocks, map each to a file path, and write it inside
        the workspace. Path traversal is refused; everything else (including
        out-of-scope edits) is written so the scope gate can judge it."""
        blocks: list[tuple[str | None, str]] = []
        for m in _CODE_BLOCK_RE.finditer(response):
            code = m.group(1)
            # The path marker may sit BEFORE the fence (in the prose) or as the
            # first line INSIDE the block (the model often writes
            # "# FILE: path" as the first code line). Try both.
            path = self._path_from_context(response[: m.start()], targets)
            if path is None:
                path, code = self._path_from_block_header(code, targets)
            blocks.append((path, code))

        # Single unlabeled block + single editable target -> assign it there.
        if len(blocks) == 1 and blocks[0][0] is None and len(targets) == 1:
            blocks = [(next(iter(targets)), blocks[0][1])]

        written: list[str] = []
        ws = workspace.resolve()
        for path, code in blocks:
            if path is None:
                continue
            dest = (workspace / path).resolve()
            if not dest.is_relative_to(ws):
                continue  # path traversal: never write outside the workspace
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(code if code.endswith("\n") else code + "\n")
            written.append(dest.relative_to(ws).as_posix())
        return written

    @staticmethod
    def _path_from_block_header(
        code: str, targets: dict[str, str]
    ) -> tuple[str | None, str]:
        """Detect a path marker on the first line(s) inside a code block (e.g.
        '# FILE: listkit/dedup.py'), return (path, code_without_the_marker).

        Only a comment/marker line is consumed — a real first line of code that
        merely mentions a *.py string is left intact."""
        lines = code.splitlines()
        drop = 0
        for i, ln in enumerate(lines[:3]):
            if not ln.strip():
                drop = i + 1
                continue
            found = _PATH_RE.findall(ln)
            is_marker = bool(found) and (
                "FILE:" in ln.upper() or ln.lstrip().startswith("#")
            )
            if is_marker:
                raw = found[-1].lstrip("./")
                name = Path(raw).name
                path = raw
                for t in targets:
                    if t == raw or t.endswith("/" + raw) or Path(t).name == name:
                        path = t
                        break
                cleaned = "\n".join(lines[i + 1 :])
                if cleaned and not cleaned.endswith("\n"):
                    cleaned += "\n"
                return path, cleaned
            # First real code line and no marker: nothing to strip.
            break
        return None, code

    @staticmethod
    def _path_from_context(pre: str, targets: dict[str, str]) -> str | None:
        """Find the file path labeling the code block that follows `pre`.

        Scans the last few non-empty lines before the block for a *.py token,
        preferring a match against a known editable target (by relpath or
        basename); falls back to the raw token (lets the scope gate judge it)."""
        lines = [ln for ln in pre.splitlines() if ln.strip()][-5:]
        cands: list[str] = []
        for ln in reversed(lines):
            found = _PATH_RE.findall(ln)
            if found:
                cands = found
                break
        if not cands:
            return None
        raw = cands[-1].lstrip("./")
        raw_name = Path(raw).name
        for t in targets:
            if t == raw or t.endswith("/" + raw) or Path(t).name == raw_name:
                return t
        return raw
