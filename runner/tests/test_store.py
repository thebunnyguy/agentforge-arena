"""Tests for afa_runner.store.SqliteRunStore (framework §10 raw layer).

These build RunRecord / RunScore (and a GradeReport) directly, so they do not
depend on the pipeline or grader being implemented — only on the dataclass
contracts. Expected behavior is reasoned from the storage spec, not echoed from
the implementation.
"""

from __future__ import annotations

import pytest

from afa_kernel.types import (
    Gates,
    QualityInputs,
    RunInput,
    RunScore,
    RunStatus,
    TestResult,
)
from afa_runner.diffing import Diff
from afa_runner.grader import GradeReport, SuiteOutcome
from afa_runner.pipeline import RunRecord
from afa_runner.store import SqliteRunStore


# --------------------------------------------------------------------------- #
# Builders (independent of pipeline/grader implementations)
# --------------------------------------------------------------------------- #

def make_score(
    *,
    status: RunStatus = RunStatus.VALID,
    gate_product: int = 1,
    t_hidden: float = 1.0,
    q: float = 1.0,
    final_score: float = 1.0,
    functional_pass: bool = True,
    voided: bool = False,
) -> RunScore:
    return RunScore(
        status=status,
        gate_product=gate_product,
        t_hidden=t_hidden,
        q=q,
        q_components={"lint": 0.9, "security": 1.0},  # NOT persisted in v0.1
        final_score=final_score,
        functional_pass=functional_pass,
        voided=voided,
    )


def make_record(
    *,
    task_id: str = "fix-list-dedup",
    task_version: str = "1.0.0",
    agent: str = "ref-agent",
    idx: int = 0,
    status: RunStatus = RunStatus.VALID,
    score: RunScore | None = None,
    files_changed: int = 1,
    lines_added: int = 3,
    lines_removed: int = 2,
    transcript_hash: str = "sha256:deadbeef",
    duration_ms: int = 1234,
) -> RunRecord:
    return RunRecord(
        task_id=task_id,
        task_version=task_version,
        agent=agent,
        idx=idx,
        status=status,
        score=score if score is not None else make_score(),
        files_changed=files_changed,
        lines_added=lines_added,
        lines_removed=lines_removed,
        transcript_hash=transcript_hash,
        duration_ms=duration_ms,
    )


def make_report(
    *,
    touched_protected: bool = False,
    patch_text: str = "--- a/listkit/dedup.py\n+++ b/listkit/dedup.py\n",
    hidden: tuple[TestResult, ...] = (
        TestResult("test_preserves_order", True, 1.0),
        TestResult("test_basic", True, 1.0),
    ),
    regression: tuple[TestResult, ...] = (TestResult("test_smoke", True, 1.0),),
) -> GradeReport:
    diff = Diff(
        changed={"listkit/dedup.py": "code"},
        deleted=(),
        files_changed=1,
        lines_added=3,
        lines_removed=2,
        touched_protected=touched_protected,
        patch_text=patch_text,
    )
    gates = Gates(
        setup_ok=True,
        diff_exists=True,
        scope_ok=not touched_protected,
        regression_pass=True,
        no_timeout=True,
    )
    run_input = RunInput(
        status=RunStatus.VALID,
        gates=gates,
        hidden=hidden,
        quality=QualityInputs(),
    )
    return GradeReport(
        run_input=run_input,
        status=RunStatus.VALID,
        diff=diff,
        hidden=SuiteOutcome(results=hidden, all_passed=all(t.passed for t in hidden), errored=False),
        regression=SuiteOutcome(
            results=regression,
            all_passed=all(t.passed for t in regression),
            errored=False,
        ),
        setup_ok=True,
        timed_out=False,
        notes="",
    )


# --------------------------------------------------------------------------- #
# Round-trip
# --------------------------------------------------------------------------- #

def test_save_then_load_roundtrip_preserves_everything():
    store = SqliteRunStore(":memory:")
    try:
        score = make_score(
            status=RunStatus.VALID,
            gate_product=1,
            t_hidden=0.75,
            q=0.8,
            final_score=0.735,
            functional_pass=False,
            voided=False,
        )
        rec = make_record(
            score=score,
            files_changed=2,
            lines_added=7,
            lines_removed=4,
            transcript_hash="sha256:abc123",
            duration_ms=999,
            idx=3,
        )
        new_id = store.save_run(rec)
        assert isinstance(new_id, int)
        assert new_id >= 1

        loaded = store.load_runs()
        assert len(loaded) == 1
        got = loaded[0]

        # Provenance preserved.
        assert got.task_id == rec.task_id
        assert got.task_version == rec.task_version
        assert got.agent == rec.agent
        assert got.idx == 3
        assert got.status == RunStatus.VALID
        assert got.transcript_hash == "sha256:abc123"
        assert got.duration_ms == 999

        # Diff stats preserved.
        assert got.files_changed == 2
        assert got.lines_added == 7
        assert got.lines_removed == 4

        # Score reconstructed faithfully (q_components dropped -> {}).
        assert got.score.status == RunStatus.VALID
        assert got.score.gate_product == 1
        assert got.score.t_hidden == pytest.approx(0.75)
        assert got.score.q == pytest.approx(0.8)
        assert got.score.final_score == pytest.approx(0.735)
        assert got.score.functional_pass is False
        assert got.score.voided is False
        assert got.score.q_components == {}
    finally:
        store.close()


def test_save_returns_distinct_increasing_ids():
    store = SqliteRunStore(":memory:")
    try:
        id1 = store.save_run(make_record(idx=0))
        id2 = store.save_run(make_record(idx=1))
        assert id2 != id1
        assert id2 > id1
        assert len(store.load_runs()) == 2
    finally:
        store.close()


# --------------------------------------------------------------------------- #
# Filtering & ordering
# --------------------------------------------------------------------------- #

def test_filter_by_task_id_and_agent_and_ordering():
    store = SqliteRunStore(":memory:")
    try:
        # Two agents across two tasks, out-of-order idx to test ORDER BY.
        store.save_run(make_record(agent="zebra", task_id="task-b", idx=1))
        store.save_run(make_record(agent="zebra", task_id="task-b", idx=0))
        store.save_run(make_record(agent="alpha", task_id="task-a", idx=0))
        store.save_run(make_record(agent="alpha", task_id="task-b", idx=0))

        # Filter by agent only.
        zebra = store.load_runs(agent="zebra")
        assert len(zebra) == 2
        assert {r.agent for r in zebra} == {"zebra"}
        # Ordered by (agent, task_id, idx) -> idx 0 before idx 1.
        assert [r.idx for r in zebra] == [0, 1]

        # Filter by task_id only.
        task_b = store.load_runs(task_id="task-b")
        assert len(task_b) == 3
        assert {r.task_id for r in task_b} == {"task-b"}
        # alpha sorts before zebra.
        assert [r.agent for r in task_b] == ["alpha", "zebra", "zebra"]

        # Filter by both.
        both = store.load_runs(task_id="task-a", agent="alpha")
        assert len(both) == 1
        assert both[0].task_id == "task-a"
        assert both[0].agent == "alpha"

        # No filter returns everything.
        assert len(store.load_runs()) == 4

        # Non-matching filter returns empty.
        assert store.load_runs(agent="nobody") == []
    finally:
        store.close()


def test_agents_and_task_ids_distinct_sorted():
    store = SqliteRunStore(":memory:")
    try:
        store.save_run(make_record(agent="charlie", task_id="t3", idx=0))
        store.save_run(make_record(agent="alpha", task_id="t1", idx=0))
        store.save_run(make_record(agent="alpha", task_id="t1", idx=1))
        store.save_run(make_record(agent="bravo", task_id="t2", idx=0))

        assert store.agents() == ["alpha", "bravo", "charlie"]
        assert store.task_ids() == ["t1", "t2", "t3"]
    finally:
        store.close()


def test_summary_reports_time_window_and_artifact_coverage():
    store = SqliteRunStore(":memory:")
    try:
        with_report = store.save_run(
            make_record(agent="alpha", idx=0),
            report=make_report(),
        )
        store.save_run(make_record(agent="alpha", idx=1))
        store.save_run(make_record(agent="beta", idx=0))
        store._conn.execute(
            "UPDATE runs SET created_at = ? WHERE id = ?", ("2026-01-01 00:00:00", with_report)
        )
        store._conn.commit()

        overall = store.summary()
        assert overall.total_runs == 3
        assert overall.first_created_at == "2026-01-01 00:00:00"
        assert overall.last_created_at is not None
        assert overall.runs_with_patch == 1
        assert overall.runs_with_test_results == 1
        assert overall.test_result_rows == 3

        alpha = store.summary("alpha")
        assert alpha.total_runs == 2
        assert alpha.runs_with_patch == 1
        assert alpha.runs_with_test_results == 1

        missing = store.summary("missing")
        assert missing.total_runs == 0
        assert missing.first_created_at is None
        assert missing.last_created_at is None
    finally:
        store.close()


# --------------------------------------------------------------------------- #
# Voided / status round-trip
# --------------------------------------------------------------------------- #

def test_voided_infra_failure_roundtrips():
    store = SqliteRunStore(":memory:")
    try:
        score = make_score(
            status=RunStatus.INFRA_FAILURE,
            gate_product=0,
            t_hidden=0.0,
            q=1.0,
            final_score=0.0,
            functional_pass=False,
            voided=True,
        )
        rec = make_record(status=RunStatus.INFRA_FAILURE, score=score)
        store.save_run(rec)

        got = store.load_runs()[0]
        assert got.status == RunStatus.INFRA_FAILURE
        assert got.score.status == RunStatus.INFRA_FAILURE
        assert got.score.voided is True
        assert got.score.gate_product == 0
        assert got.score.final_score == pytest.approx(0.0)
    finally:
        store.close()


def test_all_run_statuses_roundtrip():
    store = SqliteRunStore(":memory:")
    try:
        for i, st in enumerate(RunStatus):
            store.save_run(
                make_record(idx=i, status=st, score=make_score(status=st))
            )
        loaded = store.load_runs()
        assert {r.status for r in loaded} == set(RunStatus)
        # Enum identity, not just value equality.
        for r in loaded:
            assert isinstance(r.status, RunStatus)
    finally:
        store.close()


# --------------------------------------------------------------------------- #
# test_results persistence (with a GradeReport)
# --------------------------------------------------------------------------- #

def test_test_results_persisted_when_report_supplied():
    store = SqliteRunStore(":memory:")
    try:
        report = make_report(
            hidden=(
                TestResult("test_preserves_order", True, 2.0),
                TestResult("test_dupes_removed", False, 1.0),
            ),
            regression=(TestResult("test_smoke", True, 1.0),),
        )
        run_id = store.save_run(make_record(), report=report)

        # Inspect the raw test_results table directly: the store does not expose
        # a reader for it, but the spec says results are persisted from report.
        rows = _query_test_results(store, run_id)
        # 2 hidden + 1 regression.
        assert len(rows) == 3
        by_name = {r["test_name"]: r for r in rows}

        assert by_name["test_preserves_order"]["suite"] == "hidden"
        assert by_name["test_preserves_order"]["passed"] == 1
        assert by_name["test_preserves_order"]["weight"] == pytest.approx(2.0)

        assert by_name["test_dupes_removed"]["suite"] == "hidden"
        assert by_name["test_dupes_removed"]["passed"] == 0

        assert by_name["test_smoke"]["suite"] == "regression"
        assert by_name["test_smoke"]["passed"] == 1
    finally:
        store.close()


def test_patch_text_persisted_from_report():
    store = SqliteRunStore(":memory:")
    try:
        report = make_report(patch_text="UNIQUE-PATCH-MARKER-42")
        run_id = store.save_run(make_record(), report=report)
        row = store._conn.execute(
            "SELECT patch_text, touched_protected FROM diffs WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        assert row["patch_text"] == "UNIQUE-PATCH-MARKER-42"
        assert row["touched_protected"] == 0
    finally:
        store.close()


def test_pipeline_grade_report_is_persisted_without_parallel_argument():
    store = SqliteRunStore(":memory:")
    try:
        report = make_report(patch_text="EMBEDDED-PIPELINE-PATCH")
        record = make_record()
        record = RunRecord(
            task_id=record.task_id,
            task_version=record.task_version,
            agent=record.agent,
            idx=record.idx,
            status=record.status,
            score=record.score,
            files_changed=record.files_changed,
            lines_added=record.lines_added,
            lines_removed=record.lines_removed,
            transcript_hash=record.transcript_hash,
            duration_ms=record.duration_ms,
            grade_report=report,
        )

        run_id = store.save_run(record)

        diff = store._conn.execute(
            "SELECT patch_text FROM diffs WHERE run_id = ?", (run_id,)
        ).fetchone()
        assert diff["patch_text"] == "EMBEDDED-PIPELINE-PATCH"
        assert len(_query_test_results(store, run_id)) == 3
    finally:
        store.close()


def test_no_test_results_without_report():
    store = SqliteRunStore(":memory:")
    try:
        run_id = store.save_run(make_record())  # no report
        rows = _query_test_results(store, run_id)
        assert rows == []
        # Diff row still written from the record's own stats; patch_text NULL.
        row = store._conn.execute(
            "SELECT files_changed, patch_text FROM diffs WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        assert row["files_changed"] == 1
        assert row["patch_text"] is None
    finally:
        store.close()


def test_touched_protected_recorded_from_report():
    store = SqliteRunStore(":memory:")
    try:
        report = make_report(touched_protected=True)
        run_id = store.save_run(make_record(), report=report)
        row = store._conn.execute(
            "SELECT touched_protected FROM diffs WHERE run_id = ?", (run_id,)
        ).fetchone()
        assert row["touched_protected"] == 1
    finally:
        store.close()


# --------------------------------------------------------------------------- #
# Persistence to disk
# --------------------------------------------------------------------------- #

def test_on_disk_db_persists_across_connections(tmp_path):
    db_path = tmp_path / "runs.db"
    store = SqliteRunStore(db_path)
    try:
        store.save_run(make_record(agent="persisted-agent", task_id="kept"))
    finally:
        store.close()

    # Reopen the same file in a fresh store: data is still there.
    store2 = SqliteRunStore(db_path)
    try:
        loaded = store2.load_runs()
        assert len(loaded) == 1
        assert loaded[0].agent == "persisted-agent"
        assert store2.agents() == ["persisted-agent"]
        assert store2.task_ids() == ["kept"]
    finally:
        store2.close()


def test_empty_store_returns_empty():
    store = SqliteRunStore(":memory:")
    try:
        assert store.load_runs() == []
        assert store.agents() == []
        assert store.task_ids() == []
    finally:
        store.close()


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _query_test_results(store: SqliteRunStore, run_id: int) -> list[dict]:
    cur = store._conn.execute(
        "SELECT suite, test_name, passed, weight FROM test_results "
        "WHERE run_id = ? ORDER BY suite, test_name",
        (run_id,),
    )
    return [dict(row) for row in cur.fetchall()]
