"""Offline unit tests for OllamaAgent (runner/afa_runner/agents_ollama.py).

OllamaAgent is a REAL single-shot file-edit coding agent backed by a locally
served open-weights model via Ollama HTTP. To stay fully offline and
deterministic, every test injects a fake `generate` callable
(``generate=fake`` where ``fake(prompt: str, seed: int) -> str``) so the real
Ollama HTTP path (``ollama_generate``) is NEVER exercised. No network, no
Ollama, no sleeps.

The agent's contract (see the module docstring + project clean-room invariants):
  * It parses fenced code blocks from the model response and maps each to a file
    path either from a "# FILE: <path>" marker INSIDE the block (stripped before
    writing) or from a path token in the prose BEFORE the fence.
  * It writes ONLY inside its own workspace; path traversal that resolves above
    the workspace is REFUSED (nothing written).
  * It does NOT silently sanitize out-of-scope edits: a faithful edit to a
    protected/test file is written INTO THE WORKSPACE so the downstream scope
    gate (capture_diff -> touched_protected) can honestly penalize it.
  * The sampling seed increments per act() call (base_seed, base_seed+1, ...).
  * A generate() that raises -> AgentOutcome.errored is True (nothing crashes).
  * No code block in the response -> nothing written, errored=False.
"""

from __future__ import annotations

import shutil
from dataclasses import replace
from pathlib import Path

import pytest

from afa_runner import OllamaAgent, capture_diff, load_task

# This file lives at <root>/runner/tests/test_agents_ollama.py.
ROOT = Path(__file__).resolve().parents[2]
TASK_DIR = ROOT / "tasks" / "fix-list-dedup"

# A correct, order-preserving dedup body (the "fix" the model is meant to emit).
FIXED_DEDUP = "def dedup(items):\n    return list(dict.fromkeys(items))\n"


# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #

@pytest.fixture(scope="module")
def task():
    return load_task(TASK_DIR)


@pytest.fixture
def workspace(task, tmp_path):
    """A fresh writable workspace: a copytree of the real task snapshot.

    Returned as the workspace root the agent edits in place. Lives under
    tmp_path so parent-traversal targets (../evil.py) land in pytest's tmp tree,
    which we then assert was NOT written to.
    """
    ws = tmp_path / "ws"
    shutil.copytree(task.snapshot_dir, ws)
    return ws


def _fake(response: str, seen_seeds: list[int] | None = None):
    """Build an injectable generate fake returning a fixed response.

    If ``seen_seeds`` is given, each call appends its seed so the test can assert
    the per-call seed schedule.
    """

    def gen(prompt: str, seed: int) -> str:
        if seen_seeds is not None:
            seen_seeds.append(seed)
        return response

    return gen


# --------------------------------------------------------------------------- #
# (1) Happy path: marker INSIDE the fenced block is stripped; file is written.
# --------------------------------------------------------------------------- #

def test_marker_inside_block_is_stripped_and_file_written(task, workspace):
    response = (
        "Here is the corrected file:\n\n"
        "```python\n"
        "# FILE: listkit/dedup.py\n"
        "def dedup(items):\n"
        "    return list(dict.fromkeys(items))\n"
        "```\n"
    )
    agent = OllamaAgent(name="ollama", generate=_fake(response))
    outcome = agent.act(workspace, task, None)

    assert outcome.errored is False
    written = (workspace / "listkit" / "dedup.py").read_text()
    # The "# FILE: ..." marker line must NOT survive into the written file.
    assert "# FILE:" not in written
    assert written.splitlines()[0] == "def dedup(items):"
    assert "return list(dict.fromkeys(items))" in written
    assert written.endswith("\n")
    # The transcript records that exactly dedup.py was written.
    assert "listkit/dedup.py" in outcome.transcript


# --------------------------------------------------------------------------- #
# (2) Marker BEFORE the fence (in the prose) maps correctly.
# --------------------------------------------------------------------------- #

def test_marker_before_fence_maps_correctly(task, workspace):
    response = (
        "# FILE: listkit/dedup.py\n"
        "```python\n"
        "def dedup(items):\n"
        "    seen = set()\n"
        "    out = []\n"
        "    for x in items:\n"
        "        if x not in seen:\n"
        "            seen.add(x)\n"
        "            out.append(x)\n"
        "    return out\n"
        "```\n"
    )
    agent = OllamaAgent(name="ollama", generate=_fake(response))
    outcome = agent.act(workspace, task, None)

    assert outcome.errored is False
    written = (workspace / "listkit" / "dedup.py").read_text()
    # The prose marker is consumed as context only; the body is written intact,
    # not corrupted by the marker line.
    assert "# FILE:" not in written
    assert written.splitlines()[0] == "def dedup(items):"
    assert "for x in items:" in written


# --------------------------------------------------------------------------- #
# (3a) Single unlabeled block + a SINGLE editable target -> assigned to it.
# --------------------------------------------------------------------------- #

def test_single_unlabeled_block_assigned_to_sole_editable_target(task, workspace):
    """With exactly one editable target, an unlabeled block is unambiguous and is
    written to that file. We narrow the real task's editable allow-list to a
    single file so only listkit/dedup.py is a target."""
    solo_task = replace(task, editable_paths=("listkit/dedup.py",))
    agent = OllamaAgent(name="ollama")
    targets = agent._editable_files(workspace, solo_task)
    assert sorted(targets) == ["listkit/dedup.py"], "precondition: one target"

    response = (
        "```python\n"
        "def dedup(items):\n"
        "    return list(dict.fromkeys(items))\n"
        "```\n"
    )
    agent.generate = _fake(response)
    outcome = agent.act(workspace, solo_task, None)

    assert outcome.errored is False
    written = (workspace / "listkit" / "dedup.py").read_text()
    assert "return list(dict.fromkeys(items))" in written
    assert "listkit/dedup.py" in outcome.transcript


# --------------------------------------------------------------------------- #
# (3b) Single unlabeled block + the REAL 3-file task -> NOT misassigned.
# --------------------------------------------------------------------------- #

def test_single_unlabeled_block_real_task_is_not_misassigned(task, workspace):
    """The real task has THREE editable files (listkit/__init__.py, dedup.py,
    flatten.py). An unlabeled block is ambiguous, so the agent must refuse to
    guess: nothing is written, and the diff stays empty."""
    agent = OllamaAgent(name="ollama")
    targets = agent._editable_files(workspace, task)
    assert len(targets) == 3, "precondition: ambiguous, three editable files"

    before = {
        rel: (workspace / rel).read_text()
        for rel in ("listkit/__init__.py", "listkit/dedup.py", "listkit/flatten.py")
    }
    response = (
        "```python\n"
        "def dedup(items):\n"
        "    return list(dict.fromkeys(items))\n"
        "```\n"
    )
    agent.generate = _fake(response)
    outcome = agent.act(workspace, task, None)

    assert outcome.errored is False
    # No editable source file changed -> the unlabeled block was NOT assigned.
    for rel, text in before.items():
        assert (workspace / rel).read_text() == text, f"{rel} was misassigned"
    diff = capture_diff(
        task.snapshot_dir, workspace, task.protected_paths, task.editable_paths
    )
    assert diff.exists() is False
    assert "WROTE=[]" in outcome.transcript


# --------------------------------------------------------------------------- #
# (4) No code block in the response -> nothing written, empty diff, no error.
# --------------------------------------------------------------------------- #

def test_no_code_block_writes_nothing_and_does_not_error(task, workspace):
    response = "I'm sorry, I can't help with that. There is no code to provide."
    agent = OllamaAgent(name="ollama", generate=_fake(response))
    outcome = agent.act(workspace, task, None)

    assert outcome.errored is False
    diff = capture_diff(
        task.snapshot_dir, workspace, task.protected_paths, task.editable_paths
    )
    assert diff.exists() is False  # empty diff -> diff_exists gate will fail
    assert "WROTE=[]" in outcome.transcript


# --------------------------------------------------------------------------- #
# (5) generate() raising -> AgentOutcome.errored is True; nothing crashes.
# --------------------------------------------------------------------------- #

def test_generate_raising_sets_errored_and_does_not_crash(task, workspace):
    def boom(prompt: str, seed: int) -> str:
        raise RuntimeError("ollama unreachable")

    agent = OllamaAgent(name="ollama", generate=boom)
    outcome = agent.act(workspace, task, None)

    # A genuine agent-side failure: errored (AGENT_ERROR), NOT infra.
    assert outcome.errored is True
    assert outcome.infra_failed is False
    # The error transcript names the failure, but no source file was written.
    assert "RuntimeError" in outcome.transcript
    diff = capture_diff(
        task.snapshot_dir, workspace, task.protected_paths, task.editable_paths
    )
    assert diff.exists() is False


def test_generate_url_error_is_infra_not_agent_error(task, workspace):
    """A transport failure (Ollama down) is INFRASTRUCTURE, not an agent loss:
    infra_failed=True, errored=False (framework §1 — never counts against the
    agent)."""
    import urllib.error

    def down(prompt: str, seed: int) -> str:
        raise urllib.error.URLError("connection refused")

    agent = OllamaAgent(name="ollama", generate=down)
    outcome = agent.act(workspace, task, None)
    assert outcome.infra_failed is True
    assert outcome.errored is False
    assert "INFRA" in outcome.transcript


def test_infra_failure_voids_the_run_and_is_excluded_from_n(task):
    """run_once on a down model yields INFRA_FAILURE (voided); the kernel
    excludes it from n, so it never lowers the pass rate."""
    import urllib.error

    from afa_runner import LocalSandbox, aggregate_group, run_group
    from afa_kernel.types import RunStatus

    def down(prompt: str, seed: int) -> str:
        raise urllib.error.URLError("connection refused")

    agent = OllamaAgent(name="ollama-down", generate=down)
    records = run_group(agent, task, 3, sandbox=LocalSandbox())
    assert all(r.status is RunStatus.INFRA_FAILURE for r in records)
    assert all(r.score.voided for r in records)
    agg = aggregate_group(records)
    assert agg.n_valid == 0          # voided runs excluded from n
    assert agg.infra_void_rate == 1.0


# --------------------------------------------------------------------------- #
# (6) Seed increments per act() call: base_seed, base_seed+1, ...
# --------------------------------------------------------------------------- #

def test_seed_increments_per_act_call(task, workspace):
    seen: list[int] = []
    response = (
        "```python\n# FILE: listkit/dedup.py\n" + FIXED_DEDUP + "```\n"
    )
    agent = OllamaAgent(name="ollama", base_seed=4242, generate=_fake(response, seen))

    agent.act(workspace, task, None)
    agent.act(workspace, task, None)
    agent.act(workspace, task, None)

    # base_seed, base_seed+1, base_seed+2 — reproducible yet varying per attempt.
    assert seen == [4242, 4243, 4244]


def test_seed_recorded_in_transcript(task, workspace):
    seen: list[int] = []
    response = "no code here"
    agent = OllamaAgent(name="ollama", base_seed=7000, generate=_fake(response, seen))
    outcome = agent.act(workspace, task, None)
    assert seen == [7000]
    assert "seed=7000" in outcome.transcript


# --------------------------------------------------------------------------- #
# (7) Path traversal: a "# FILE: ../evil.py" block writes NOTHING outside the ws.
# --------------------------------------------------------------------------- #

def test_path_traversal_leading_dotdot_writes_nothing_outside_workspace(
    task, workspace, tmp_path
):
    """A '# FILE: ../evil.py' marker must never create a file above the
    workspace. (The leading "../" is normalized away by the adapter, so it lands
    safely inside the workspace at worst; the hard invariant is that NOTHING is
    created in the parent tree.)"""
    response = (
        "```python\n"
        "# FILE: ../evil.py\n"
        "import os\n"
        "os.system('rm -rf /')\n"
        "```\n"
    )
    agent = OllamaAgent(name="ollama", generate=_fake(response))
    outcome = agent.act(workspace, task, None)

    assert outcome.errored is False
    # The escape target above the workspace must not exist anywhere up the tree.
    assert not (workspace.parent / "evil.py").exists()
    assert not (tmp_path / "evil.py").exists()
    assert not (tmp_path.parent / "evil.py").exists()


def test_path_traversal_embedded_dotdot_is_refused_entirely(
    task, workspace, tmp_path
):
    """A traversal that survives normalization (e.g. 'listkit/../../evil.py'
    resolves above the workspace) is REFUSED outright by the is_relative_to
    guard: nothing is written anywhere — not inside the workspace, not above."""
    response = (
        "```python\n"
        "# FILE: listkit/../../evil.py\n"
        "MALICIOUS = True\n"
        "```\n"
    )
    agent = OllamaAgent(name="ollama", generate=_fake(response))
    outcome = agent.act(workspace, task, None)

    assert outcome.errored is False
    # Refused completely: no evil.py inside the workspace nor anywhere above it.
    assert not (workspace / "evil.py").exists()
    assert not (workspace.parent / "evil.py").exists()
    assert not (tmp_path / "evil.py").exists()
    assert not (tmp_path.parent / "evil.py").exists()
    # And no editable source was disturbed.
    diff = capture_diff(
        task.snapshot_dir, workspace, task.protected_paths, task.editable_paths
    )
    assert diff.exists() is False


# --------------------------------------------------------------------------- #
# (8) Faithful out-of-scope write: a "# FILE: tests_visible/test_visible.py"
#     block IS written INTO the workspace, so the scope gate can catch it.
# --------------------------------------------------------------------------- #

def test_out_of_scope_edit_is_faithfully_written_into_workspace(task, workspace):
    """The adapter does NOT silently sanitize out-of-scope edits. A model edit to
    a protected test file is written INTO the workspace; the downstream scope
    gate (capture_diff -> touched_protected) is what honestly penalizes it."""
    protected_rel = "tests_visible/test_visible.py"
    before = (workspace / protected_rel).read_text()

    response = (
        "```python\n"
        f"# FILE: {protected_rel}\n"
        "def test_visible():\n"
        "    assert True  # neutered by the model\n"
        "```\n"
    )
    agent = OllamaAgent(name="ollama", generate=_fake(response))
    outcome = agent.act(workspace, task, None)

    assert outcome.errored is False
    after = (workspace / protected_rel).read_text()
    # The out-of-scope file WAS changed in the workspace (not sanitized away).
    assert after != before
    assert "neutered by the model" in after
    assert protected_rel in outcome.transcript

    # The scope gate now flags the violation: touched_protected -> True so the
    # downstream pipeline collapses the gate product (and the score) to zero.
    diff = capture_diff(
        task.snapshot_dir, workspace, task.protected_paths, task.editable_paths
    )
    assert diff.exists() is True
    assert diff.touched_protected is True


# --------------------------------------------------------------------------- #
# Bonus: the default generate path never fires when a fake is injected (offline
# guarantee), and ollama_generate is importable but not called by these tests.
# --------------------------------------------------------------------------- #

def test_injected_generate_is_used_not_the_default_http_path(task, workspace):
    """Sentinel: if the real ollama_generate were called it would attempt an HTTP
    request and (offline) error. Injecting a fake must short-circuit that, so the
    run completes without error and uses our response."""
    marker_response = (
        "```python\n# FILE: listkit/dedup.py\n" + FIXED_DEDUP + "```\n"
    )
    called = {"n": 0}

    def gen(prompt: str, seed: int) -> str:
        called["n"] += 1
        return marker_response

    # base_url points at a black hole; it must never be dialed because of `gen`.
    agent = OllamaAgent(
        name="ollama",
        base_url="http://127.0.0.1:1",  # would refuse if ever used
        generate=gen,
    )
    outcome = agent.act(workspace, task, None)
    assert called["n"] == 1
    assert outcome.errored is False
    assert "return list(dict.fromkeys(items))" in (
        workspace / "listkit" / "dedup.py"
    ).read_text()
