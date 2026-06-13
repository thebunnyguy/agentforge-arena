"""End-to-end runner tests (framework §1, §2, §6, §8, §9, §10).

These drive the WHOLE pipeline against the real ``fix-list-dedup`` benchmark
task: the three demo agents through ``run_group`` + a SQLite store + the report
layer, plus the §8 task-validity gate and direct clean-room integrity checks.

Expected values are reasoned from the scoring spec, not echoed from the
implementation:
  * good : reference dedup        -> 5/5 functional passes, every S == 1.0.
  * bad  : sorted(set(items))     -> 0 functional passes, but gates hold so
                                     0 < S < 1 on every run (2/5 hidden pass).
  * seq  : good,good,wrong,good,wrong -> exactly 3/5 functional passes.
The leaderboard must rank bad last and give good a strictly larger Wilson LCB
than seq.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from afa_kernel.types import RunStatus
from afa_runner import (
    LocalSandbox,
    MockAgent,
    SequenceAgent,
    SqliteRunStore,
    aggregate_group,
    leaderboard,
    load_task,
    run_group,
    run_once,
    task_aggregate,
    validate_task,
)

# This file lives at <root>/runner/tests/test_end_to_end.py.
ROOT = Path(__file__).resolve().parents[2]
TASK_DIR = ROOT / "tasks" / "fix-list-dedup"

N_RUNS = 5
BUGGY_DEDUP = "def dedup(items):\n    return sorted(set(items))\n"


# --------------------------------------------------------------------------- #
# Fixtures / builders
# --------------------------------------------------------------------------- #

@pytest.fixture(scope="module")
def task():
    return load_task(TASK_DIR)


@pytest.fixture(scope="module")
def sandbox():
    return LocalSandbox()


@pytest.fixture(scope="module")
def reference_text(task):
    return (task.reference_dir / "listkit" / "dedup.py").read_text(encoding="utf-8")


def _good_agent(reference_text):
    return MockAgent(name="good", writes={"listkit/dedup.py": reference_text})


def _bad_agent():
    return MockAgent(name="bad", writes={"listkit/dedup.py": BUGGY_DEDUP})


def _seq_agent(reference_text):
    good_member = MockAgent(name="good", writes={"listkit/dedup.py": reference_text})
    wrong_member = MockAgent(name="wrong", writes={"listkit/dedup.py": BUGGY_DEDUP})
    # good, good, wrong, good, wrong -> 3 passes out of 5.
    return SequenceAgent(
        name="seq",
        members=[good_member, good_member, wrong_member, good_member, wrong_member],
    )


@pytest.fixture(scope="module")
def populated_store(task, sandbox, reference_text):
    """Run the three demo agents through run_group and persist every run."""
    store = SqliteRunStore(":memory:")
    agents = [
        _good_agent(reference_text),
        _bad_agent(),
        _seq_agent(reference_text),
    ]
    for agent in agents:
        for record in run_group(agent, task, N_RUNS, sandbox=sandbox):
            store.save_run(record)
    yield store
    store.close()


# --------------------------------------------------------------------------- #
# Per-agent scoring through the full pipeline.
# --------------------------------------------------------------------------- #

def test_good_agent_all_pass_perfect_score(task, sandbox, reference_text):
    records = run_group(_good_agent(reference_text), task, N_RUNS, sandbox=sandbox)

    assert len(records) == N_RUNS
    assert [r.idx for r in records] == list(range(N_RUNS))
    for r in records:
        assert r.status is RunStatus.VALID
        assert r.score.gate_product == 1
        assert r.score.functional_pass is True
        assert r.score.final_score == 1.0
        assert r.files_changed == 1  # only listkit/dedup.py

    agg = aggregate_group(records)
    assert agg.n_valid == 5
    assert agg.n_pass == 5
    assert agg.pass_rate == 1.0
    assert agg.mean_s == 1.0
    # Identical reference diff every run -> deterministic by transcript hash.
    assert agg.deterministic is True


def test_bad_agent_no_functional_pass_but_gates_hold(task, sandbox):
    records = run_group(_bad_agent(), task, N_RUNS, sandbox=sandbox)

    for r in records:
        assert r.status is RunStatus.VALID
        # sorted(set(...)) still removes duplicates -> regression passes; diff
        # exists and touches no protected path -> all gates hold (G=1).
        assert r.score.gate_product == 1
        # But order tests in the hidden suite fail -> not a functional pass.
        assert r.score.functional_pass is False
        # G=1 with some (but not all) hidden tests passing -> 0 < S < 1.
        assert 0.0 < r.score.final_score < 1.0

    agg = aggregate_group(records)
    assert agg.n_pass == 0
    assert agg.pass_rate == 0.0
    assert 0.0 < agg.mean_s < 1.0


def test_seq_agent_scores_exactly_three_of_five(task, sandbox, reference_text):
    records = run_group(_seq_agent(reference_text), task, N_RUNS, sandbox=sandbox)

    passes = [r for r in records if r.score.functional_pass]
    assert len(passes) == 3
    for r in passes:
        assert r.score.final_score == 1.0
    # The two failing runs are the still-buggy member: G=1 but partial hidden.
    fails = [r for r in records if not r.score.functional_pass]
    assert len(fails) == 2
    for r in fails:
        assert r.score.gate_product == 1
        assert 0.0 < r.score.final_score < 1.0

    agg = aggregate_group(records)
    assert agg.n_valid == 5
    assert agg.n_pass == 3
    assert agg.pass_rate == pytest.approx(0.6)
    # Mixed good/bad outputs across runs -> not deterministic.
    assert agg.deterministic is False


# --------------------------------------------------------------------------- #
# Store round-trip + report aggregates.
# --------------------------------------------------------------------------- #

def test_store_persists_all_runs(populated_store):
    store = populated_store
    assert set(store.agents()) == {"good", "bad", "seq"}
    assert store.task_ids() == ["fix-list-dedup"]
    # 3 agents x 5 runs = 15 persisted runs.
    all_runs = store.load_runs()
    assert len(all_runs) == 15


def test_report_aggregates_match_expectations(populated_store):
    store = populated_store
    good = task_aggregate(store, "good", "fix-list-dedup")
    bad = task_aggregate(store, "bad", "fix-list-dedup")
    seq = task_aggregate(store, "seq", "fix-list-dedup")

    assert (good.n_pass, good.n_valid) == (5, 5)
    assert good.mean_s == 1.0

    assert (bad.n_pass, bad.n_valid) == (0, 5)
    assert 0.0 < bad.mean_s < 1.0

    assert (seq.n_pass, seq.n_valid) == (3, 5)


# --------------------------------------------------------------------------- #
# Leaderboard ranking (framework §6).
# --------------------------------------------------------------------------- #

def test_leaderboard_ranks_bad_last_and_good_above_seq(populated_store):
    store = populated_store
    entries = leaderboard(store, task_id="fix-list-dedup")
    by_agent = {e.agent: e for e in entries}

    assert set(by_agent) == {"good", "bad", "seq"}

    # bad has zero passes -> ranked strictly last.
    bad = by_agent["bad"]
    other_ranks = [
        by_agent["good"].rank_low,
        by_agent["seq"].rank_low,
    ]
    assert bad.rank_low == max(e.rank_high for e in entries if e.rank_high is not None)
    assert all(bad.rank_low > r for r in other_ranks)

    # good has a strictly larger Wilson lower bound than seq (5/5 vs 3/5).
    assert by_agent["good"].wilson_low > by_agent["seq"].wilson_low
    # and both strictly outrank bad on LCB.
    assert by_agent["good"].wilson_low > bad.wilson_low
    assert by_agent["seq"].wilson_low > bad.wilson_low


# --------------------------------------------------------------------------- #
# §8 task validity (benchmark CI) on the real task.
# --------------------------------------------------------------------------- #

def test_validate_task_passes_on_real_task(task, sandbox):
    result = validate_task(task, sandbox)
    assert result["valid"] is True

    # Empty diff: regression passes, hidden does not fully pass, scores 0.
    assert result["empty"]["regression_all_passed"] is True
    assert result["empty"]["hidden_all_passed"] is False
    assert result["empty"]["final_score"] == 0.0
    assert result["empty"]["functional_pass"] is False

    # Reference overlay: S=1.0, X=True, reproduced identically 3x.
    assert result["reference"]["final_score"] == 1.0
    assert result["reference"]["functional_pass"] is True
    assert result["reference"]["reproduced_identically_3x"] is True


# --------------------------------------------------------------------------- #
# Clean-room integrity (framework §9): the agent workspace is torn down and the
# grading suite never wrote hidden/regression files into the agent's workspace.
# --------------------------------------------------------------------------- #

class _WorkspaceProbe:
    """A MockAgent-like agent that fixes the bug AND records the workspace path
    plus the file set present when it ran, so the test can assert clean-room
    isolation after the run completes."""

    name = "probe"

    def __init__(self, reference_text: str) -> None:
        self.reference_text = reference_text
        self.workspace: Path | None = None
        self.seen_files: set[str] = set()

    def act(self, workspace: Path, task, sandbox):
        from afa_runner import AgentOutcome  # local import: avoid cycle at top

        self.workspace = Path(workspace)
        # Record every file the agent could see in its workspace at edit time.
        self.seen_files = {
            p.relative_to(workspace).as_posix()
            for p in Path(workspace).rglob("*")
            if p.is_file()
        }
        target = Path(workspace) / "listkit" / "dedup.py"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(self.reference_text, encoding="utf-8")
        return AgentOutcome(transcript="probe wrote listkit/dedup.py")


def test_clean_room_workspace_isolation(task, sandbox, reference_text):
    probe = _WorkspaceProbe(reference_text)
    record = run_once(probe, task, sandbox=sandbox)

    # The run still graded correctly (the probe applied the real fix).
    assert record.score.functional_pass is True
    assert record.score.final_score == 1.0

    # The agent workspace temp dir was torn down after the run (framework §9).
    assert probe.workspace is not None
    assert not probe.workspace.exists()

    # Grading never injected the hidden/regression suites into the AGENT's
    # workspace: the probe only ever saw the snapshot (no test_hidden.py /
    # test_regression.py), which live in the task grading/ dir.
    hidden_files = set(task.hidden.paths)
    regression_files = set(task.regression.paths)
    assert not (hidden_files & probe.seen_files), (
        f"hidden suite leaked into agent workspace: {hidden_files & probe.seen_files}"
    )
    assert not (regression_files & probe.seen_files), (
        f"regression suite leaked into agent workspace: "
        f"{regression_files & probe.seen_files}"
    )
    # The agent did see the visible (feedback) tests and the source package.
    assert "tests_visible/test_visible.py" in probe.seen_files
    assert "listkit/dedup.py" in probe.seen_files


def test_grading_does_not_write_into_agent_workspace(task, sandbox, reference_text):
    """A stronger isolation check: after grading, no JUnit report or grading
    test file exists anywhere the agent could have written, and the agent
    workspace path is gone. Uses run_once end to end."""
    probe = _WorkspaceProbe(reference_text)
    run_once(probe, task, sandbox=sandbox)

    assert probe.workspace is not None
    # Nothing remains on disk under the (now-removed) agent workspace root.
    assert not probe.workspace.exists()
    parent = probe.workspace.parent
    # The whole temp tree (parent prefix afa_agent_) was removed too.
    if parent.exists():
        leftovers = list(parent.rglob("*"))
        assert leftovers == [], f"agent temp tree not cleaned: {leftovers}"


# --------------------------------------------------------------------------- #
# Clean-room integrity exploits (framework §8/§9): an agent must not be able to
# win by injecting code the grading interpreter auto-executes, nor by smuggling
# files outside its editable remit. These drive the PUBLIC run_once API.
# --------------------------------------------------------------------------- #

# A buggy dedup that loses order (regression still passes, hidden order tests
# fail). Used as the "did NOT actually fix the bug" payload.
_BUGGY_SET_DEDUP = "def dedup(items):\n    return list(set(items))\n"

# A conftest.py that, if pytest auto-imported it in the clean room, would rebind
# listkit.dedup to a correct implementation — turning failing hidden tests green
# WITHOUT the agent ever fixing the source.
_CHEAT_CONFTEST = (
    "import listkit\n"
    "listkit.dedup = lambda items: list(dict.fromkeys(items))\n"
)


def test_conftest_injection_cannot_win_without_fixing_bug(task, sandbox):
    """Regression for the clean-room integrity break: an agent that leaves the
    buggy source but drops a root conftest.py (which monkeypatches the function
    under test) must NOT score a functional pass. The conftest is a scope
    violation (auto-executed file), so the run fails its gate."""
    cheater = MockAgent(
        name="cheater",
        writes={"conftest.py": _CHEAT_CONFTEST, "listkit/dedup.py": _BUGGY_SET_DEDUP},
    )
    rec = run_once(cheater, task, sandbox=sandbox)

    # The cheat must be caught: scope gate fails -> G=0 -> S=0, not a pass.
    assert rec.score.functional_pass is False
    assert rec.score.gate_product == 0
    assert rec.score.final_score == 0.0


def test_conftest_injection_distinguishable_from_honest_buggy(task, sandbox, reference_text):
    """The cheater (conftest + buggy) and an honest still-buggy attempt must NOT
    be indistinguishable, and neither may match the honest correct fix. The
    cheater is strictly worse than even the honest buggy attempt (scope fail)."""
    cheater = MockAgent(
        name="cheater",
        writes={"conftest.py": _CHEAT_CONFTEST, "listkit/dedup.py": _BUGGY_SET_DEDUP},
    )
    honest_buggy = MockAgent(name="hb", writes={"listkit/dedup.py": _BUGGY_SET_DEDUP})
    honest_good = MockAgent(name="hg", writes={"listkit/dedup.py": reference_text})

    rc = run_once(cheater, task, sandbox=sandbox).score
    rb = run_once(honest_buggy, task, sandbox=sandbox).score
    rg = run_once(honest_good, task, sandbox=sandbox).score

    # Honest correct fix wins; honest buggy gets partial credit with gates held;
    # the cheater is gated out entirely.
    assert (rg.functional_pass, rg.final_score) == (True, 1.0)
    assert rb.functional_pass is False and rb.gate_product == 1 and 0.0 < rb.final_score < 1.0
    assert rc.functional_pass is False and rc.gate_product == 0 and rc.final_score == 0.0
    # The cheater is NOT indistinguishable from the honest correct fix.
    assert rc.final_score != rg.final_score


def test_extra_file_outside_editable_allowlist_is_scope_violation(task, sandbox, reference_text):
    """Even a correct source fix is gated out if the agent also adds a file
    outside the task's editable allow-list (listkit/**)."""
    agent = MockAgent(
        name="smuggler",
        writes={"listkit/dedup.py": reference_text, "smuggled.py": "x = 1\n"},
    )
    rec = run_once(agent, task, sandbox=sandbox)
    assert rec.score.gate_product == 0
    assert rec.score.functional_pass is False
    assert rec.score.final_score == 0.0
