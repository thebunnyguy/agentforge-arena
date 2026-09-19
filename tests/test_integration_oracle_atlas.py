"""Cross-system integration tests: ORACLE (benchmark integrity, task versions)
x ATLAS (evaluation integrity, durable identity).

Neither branch can prove these alone. ORACLE hardened 18 tasks and bumped their
versions; ATLAS snapshots task version + digest into every evaluation, keeps
raw evidence, and refuses to reuse or pool across versions. These tests pin how
the two behave together:

* an ATLAS evaluation snapshots the CURRENT ORACLE version and digest, and the
  version lineage survives raw run -> trial -> results -> report.json/report.md;
* historical evidence at the OLD version is never restamped, never appears in a
  new evaluation, and is machine-distinguishable from current evidence;
* reuse across a version/digest change fails closed;
* ATLAS's global mixed-version guard is preserved (not weakened);
* ORACLE's controls still grade correctly through the merged runner;
* the remediation manifest still matches the untouched historical evidence.

The historical DB is copied, never opened writable; a module-scoped guard
asserts its bytes are unchanged by this whole module.
"""
from __future__ import annotations

import contextlib
import dataclasses
import hashlib
import json
import shutil
import subprocess
import time
import urllib.parse
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import afa_runner as afa
from afa_api import db, jobs, worker
from afa_api.main import create_app
from afa_api.schemas import JobParams
from afa_integrity.checks.controls_check import run_controls_check
from afa_integrity.model import ControlKind
from afa_runner import pipeline

REPO = Path(__file__).resolve().parents[1]
MANIFEST = json.loads((REPO / "integrity/pack-audit/remediation-manifest.json").read_text())
BUMPED: dict[str, dict] = {t["task_id"]: t for t in MANIFEST["tasks"]}
FORMERLY_INVALID = ["sanitize-filename", "toposort", "validate-redirect-url"]
TERMINAL = {"succeeded", "failed", "canceled"}


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _digest_of(task_dir: Path, rel_paths) -> str:
    h = hashlib.sha256()
    for rel in sorted(rel_paths):  # Path ordering, matching the ATLAS contract
        h.update(rel.as_posix().encode("utf-8"))
        h.update(b"\0")
        h.update((task_dir / rel).read_bytes())
        h.update(b"\0")
    return "sha256:" + h.hexdigest()


def _committed_task_digest(task_id: str) -> str:
    """Digest of the task's COMMITTED files only (git ls-files), independent of
    afa_api.jobs. Committed content is what "current task contents" means; it
    must not depend on which untracked caches a given checkout happens to hold."""
    task_rel = f"tasks/{task_id}"
    try:
        out = subprocess.run(
            ["git", "ls-files", "-z", "--", task_rel],
            cwd=REPO, capture_output=True, check=True,
        ).stdout.decode()
    except (OSError, subprocess.CalledProcessError):
        out = ""
    tracked = [Path(x).relative_to(task_rel) for x in out.split("\0") if x]
    if not tracked:
        pytest.skip("not a git checkout: cannot derive the committed task content")
    return _digest_of(REPO / task_rel, tracked)


def _legacy_all_files_digest(task_dir: Path) -> str:
    """The pre-fix ATLAS algorithm (every regular file). Used only to show the
    fix is byte-identical to it on a tree without bytecode."""
    return _digest_of(task_dir, [p.relative_to(task_dir) for p in task_dir.rglob("*") if p.is_file()])


def _enc(value: str) -> str:
    return urllib.parse.quote(value, safe="")


def _wait_terminal(client: TestClient, evaluation_id: str, timeout: float = 90.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        body = client.get(f"/api/v1/jobs/{evaluation_id}").json()
        if body["status"] in TERMINAL:
            return body
        time.sleep(0.02)
    raise AssertionError(f"evaluation {evaluation_id} did not reach a terminal state")


def _create(client: TestClient, model: str, task: str, *, mode: str = "fresh",
            source: str | None = None, repeats: int = 1):
    body = {"model": model, "backend": {"kind": "mock"}, "tasks": [task],
            "repeats": repeats, "mode": mode}
    if source is not None:
        body["source_evaluation_id"] = source
    return client.post("/api/v1/jobs", json=body)


def _fresh_model() -> str:
    return f"integ-{uuid.uuid4().hex[:10]}"


def _counts(path: Path) -> tuple[int, int]:
    conn = db.connect_readonly(path)
    try:
        return (
            conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0],
            conn.execute("SELECT COUNT(*) FROM evaluation_jobs").fetchone()[0],
        )
    finally:
        conn.close()


@contextlib.contextmanager
def _tasks_rooted_at(root: Path):
    """Point both the control plane (db.ROOT) and the worker at a private task
    root, exactly like tests/test_a2_boundaries.py does for drift tests."""
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(db, "ROOT", root)
        mp.setattr(worker, "TASKS_DIR", root / "tasks")
        yield


def _private_task_root(tmp_path: Path, task_id: str, name: str) -> Path:
    root = tmp_path / name
    shutil.copytree(
        REPO / "tasks" / task_id,
        root / "tasks" / task_id,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store"),
    )
    return root


def _set_version(root: Path, task_id: str, version: str) -> None:
    spec_path = root / "tasks" / task_id / "task.json"
    spec = json.loads(spec_path.read_text())
    spec["version"] = version
    spec_path.write_text(json.dumps(spec, indent=2) + "\n")


@pytest.fixture(scope="module", autouse=True)
def _historical_db_is_byte_identical_across_this_module():
    before = _sha256(db.EVIDENCE_DB_PATH)
    yield
    assert _sha256(db.EVIDENCE_DB_PATH) == before, "historical evidence DB changed"


@pytest.fixture()
def working_db(tmp_path: Path) -> Path:
    path = tmp_path / "integration.sqlite"
    shutil.copy(db.EVIDENCE_DB_PATH, path)
    return path


@pytest.fixture()
def client(working_db: Path):
    app = create_app()
    app.state.db_path = working_db
    app.state.agent_factory = worker.mock_agent_factory
    with TestClient(app) as c:
        yield c


# --------------------------------------------------------------------------- #
# 1. ATLAS snapshots the CURRENT ORACLE version + digest
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("task_id", sorted(BUMPED))
def test_snapshot_records_current_oracle_version_and_content_digest(task_id: str):
    entry = BUMPED[task_id]
    task_dir = REPO / "tasks" / task_id
    spec = json.loads((task_dir / "task.json").read_text())

    snap = jobs.task_snapshot(task_id)

    assert snap["task_id"] == task_id
    assert snap["task_version"] == spec["version"] == entry["new_version"]
    assert snap["task_version"] != entry["old_version"]
    assert snap["task_digest"] == _committed_task_digest(task_id)
    assert snap["task_digest"].startswith("sha256:")


ALL_TASKS = sorted(p.name for p in (REPO / "tasks").iterdir() if p.is_dir())


@pytest.mark.parametrize("task_id", ALL_TASKS)
def test_task_digest_is_a_function_of_committed_content_only(task_id: str):
    """Regression for checkout-dependent digests: identical committed content
    must produce the identical digest whether or not the checkout holds
    untracked bytecode caches (__pycache__/*.pyc), which the grader never reads.

    Intentionally checkout-sensitive in one direction: if an untracked
    NON-bytecode file (for example a macOS .DS_Store) sits inside tasks/<id>/,
    the digest really does differ from the committed content and this test
    fails on purpose. Clean the checkout; do not weaken the test."""
    assert jobs.task_snapshot(task_id)["task_digest"] == _committed_task_digest(task_id)


def test_task_digest_ignores_bytecode_the_grader_ignores_but_nothing_else(tmp_path: Path):
    task_id = "sanitize-filename"
    root = _private_task_root(tmp_path, task_id, "bytecode_root")
    task_dir = root / "tasks" / task_id
    with _tasks_rooted_at(root):
        base = jobs.task_snapshot(task_id)
        stale = {"tasks": [base]}
        # backward compatible: on a tree without bytecode the digest is exactly
        # what the pre-fix algorithm produced.
        assert base["task_digest"] == _legacy_all_files_digest(task_dir)

        (task_dir / "grading" / "__pycache__").mkdir()
        (task_dir / "grading" / "__pycache__" / "test_hidden.cpython-313-pytest-9.0.2.pyc").write_bytes(b"\x00stale")
        (task_dir / "snapshot" / "stray.pyc").write_bytes(b"\x01")
        (task_dir / "reference" / "old.pyo").write_bytes(b"\x02")
        assert jobs.task_snapshot(task_id) == base
        jobs.validate_snapshot_tasks(stale)  # bytecode never causes false drift

        # anything that is real content still changes the digest
        for rel in ("integrity/added.txt", "grading/conftest.py", "snapshot/notes.txt"):
            extra = task_dir / rel
            extra.write_text("x")
            assert jobs.task_snapshot(task_id)["task_digest"] != base["task_digest"], rel
            extra.unlink()
        assert jobs.task_snapshot(task_id) == base


# --------------------------------------------------------------------------- #
# 2. version lineage survives raw run -> trial -> results -> report.json / .md
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("task_id", FORMERLY_INVALID)
def test_mock_evaluation_of_remediated_task_preserves_version_lineage(
    client: TestClient, working_db: Path, task_id: str
):
    entry = BUMPED[task_id]
    current = jobs.task_snapshot(task_id)
    assert current["task_version"] == entry["new_version"]

    conn = db.connect_readonly(working_db)
    try:
        historical_ids = {
            r["id"] for r in conn.execute("SELECT id FROM runs WHERE task_id=?", (task_id,))
        }
    finally:
        conn.close()
    assert len(historical_ids) == 30  # 6 models x 5 reps, all at the OLD version

    created = _create(client, _fresh_model(), task_id)
    assert created.status_code == 200, created.text
    evaluation_id = created.json()["id"]
    assert created.json()["snapshot"]["tasks"] == [current]
    assert _wait_terminal(client, evaluation_id)["status"] == "succeeded"

    report = client.get(f"/api/v1/jobs/{evaluation_id}/report.json").json()
    markdown = client.get(f"/api/v1/jobs/{evaluation_id}/report.md").text
    results = client.get(f"/api/v1/jobs/{evaluation_id}/results").json()

    # evaluation snapshot == current ORACLE task
    assert report["task_snapshots"] == [current]
    assert results["snapshot"]["tasks"] == [current]

    # trial + outcome: the hardened ORACLE hidden suite accepts the reference
    # solution when driven through ATLAS's worker path.
    (trial,) = report["trials"]
    assert trial["task_version"] == entry["new_version"]
    assert trial["task_digest"] == current["task_digest"]
    assert trial["evidence_state"] == "fresh"
    assert trial["comparability"] == "comparable"
    assert trial["outcome"]["functional_pass"] is True
    assert trial["outcome"]["final_score"] == 1.0
    assert trial["run_id"] not in historical_ids

    # /results trial rows agree (the digest is carried by results["snapshot"],
    # asserted above; trial rows expose the version and the exact run id)
    (rtrial,) = results["trials"]
    assert rtrial["run_id"] == trial["run_id"]
    assert rtrial["task_version"] == entry["new_version"]
    assert rtrial["evidence_state"] == "fresh"

    # exact raw run carries the same version and belongs to this evaluation
    run = client.get(f"/api/v1/runs/{trial['run_id']}").json()
    assert run["found"] is True
    assert run["task_version"] == entry["new_version"]
    assert run["job_id"] == evaluation_id

    # markdown mirrors the JSON version lineage and never mentions the old one
    assert (
        f"- `{task_id}` @ `{entry['new_version']}` (`{current['task_digest']}`)" in markdown
    )
    assert f"### `{task_id}` @ `{entry['new_version']}` — trial 0" in markdown
    assert f"@ `{entry['old_version']}`" not in markdown


# --------------------------------------------------------------------------- #
# 3. old evidence is not current evidence
# --------------------------------------------------------------------------- #


def test_api_version_signal_flags_exactly_the_oracle_remediated_tasks(client: TestClient):
    meta = client.get("/api/v1/meta").json()
    by_task = {t["task_id"]: t for t in meta["tasks"]}
    assert len(by_task) == 24

    mismatched = {
        tid for tid, t in by_task.items() if t["evaluated_versions"] != [t["current_version"]]
    }
    assert mismatched == set(BUMPED)
    for tid, entry in BUMPED.items():
        assert by_task[tid]["current_version"] == entry["new_version"]
        assert by_task[tid]["evaluated_versions"] == [entry["old_version"]]


def test_historical_old_version_evidence_is_never_restamped_or_pooled_into_new_evidence(
    client: TestClient, working_db: Path
):
    task_id = "sanitize-filename"
    entry = BUMPED[task_id]
    historical_model = entry["known_affected_runs"]["models"][0]
    conn = db.connect_readonly(working_db)
    try:
        hist_run_id = conn.execute(
            "SELECT id FROM runs WHERE task_id=? AND agent=? ORDER BY id LIMIT 1",
            (task_id, historical_model),
        ).fetchone()["id"]
    finally:
        conn.close()

    # BEFORE any new evaluation: historical cell is explicitly at the old version.
    cell = client.get(f"/api/v1/cell/{_enc(historical_model)}/{task_id}").json()
    assert cell["current_version"] == entry["new_version"]
    assert cell["task_versions"] == [entry["old_version"]]
    assert client.get(f"/api/v1/runs/{hist_run_id}").json()["task_version"] == entry["old_version"]

    # A NEW model evaluated on the bumped task.
    new_model = _fresh_model()
    created = _create(client, new_model, task_id)
    assert created.status_code == 200, created.text
    evaluation_id = created.json()["id"]
    assert _wait_terminal(client, evaluation_id)["status"] == "succeeded"

    report = client.get(f"/api/v1/jobs/{evaluation_id}/report.json").json()
    results = client.get(f"/api/v1/jobs/{evaluation_id}/results").json()
    evaluation_runs = {t["run_id"] for t in report["trials"]}
    assert hist_run_id not in evaluation_runs
    assert {t["run_id"] for t in results["trials"]} == evaluation_runs
    assert {t["task_version"] for t in report["trials"]} == {entry["new_version"]}

    # AFTER: versions stay per-cell and honest. New evidence is new-version only,
    # old evidence is untouched and still old-version only.
    new_cell = client.get(f"/api/v1/cell/{_enc(new_model)}/{task_id}").json()
    assert new_cell["task_versions"] == [entry["new_version"]]
    old_cell = client.get(f"/api/v1/cell/{_enc(historical_model)}/{task_id}").json()
    assert old_cell["task_versions"] == [entry["old_version"]]
    assert client.get(f"/api/v1/runs/{hist_run_id}").json()["task_version"] == entry["old_version"]


def test_reevaluating_a_historical_model_on_a_bumped_task_no_longer_collapses_the_projections(
    client: TestClient, tmp_path: Path, monkeypatch
):
    """Superseded release behaviour (was: trips the global mixed-version guard).

    Persisting a new-version run for a model that already has old-version rows
    for the same task used to make every aggregate projection 503 and report
    regeneration 409. Versions are now SEPARATED instead of refused: the default
    views represent the current benchmark, the old rows stay preserved and
    inspectable, nothing is pooled, and the campaign can proceed in one DB.
    """
    import report_combined

    monkeypatch.setattr(report_combined, "OUTPUT", tmp_path / "leaderboard.html", raising=False)
    task_id = "sanitize-filename"
    entry = BUMPED[task_id]
    historical_model = entry["known_affected_runs"]["models"][0]
    hm = _enc(historical_model)

    assert client.get("/api/v1/overview").status_code == 200  # healthy before

    created = _create(client, historical_model, task_id)
    assert created.status_code == 200, created.text
    evaluation_id = created.json()["id"]
    assert _wait_terminal(client, evaluation_id)["status"] == "succeeded"

    # No projection collapses (this was a global 503 / 409 before).
    for path in ("/api/v1/overview", "/api/v1/leaderboard", "/api/v1/meta", "/api/v1/export"):
        assert client.get(path).status_code == 200, path
    assert client.get("/api/v1/healthz").json()["status"] == "ok"
    assert client.post("/api/v1/reports/regenerate").status_code == 200

    # The re-evaluation used the MOCK backend, so it is synthetic evidence: the
    # default benchmark view excludes it (reported) and the old rows stay old.
    default_cell = client.get(f"/api/v1/cell/{hm}/{task_id}").json()
    assert default_cell["state"] == "historical_only"
    assert default_cell["historical_versions"] == [entry["old_version"]]
    assert default_cell["excluded"]["synthetic_runs"] == 1
    assert client.get("/api/v1/overview").json()["excluded"]["synthetic_models"] == [historical_model]

    # The explicit synthetic/all views show the NEW-version run, and the two
    # versions are listed and aggregated separately (never pooled).
    all_cell = client.get(f"/api/v1/cell/{hm}/{task_id}?evidence=all").json()
    assert all_cell["state"] == "captured"
    assert all_cell["selected_version"] == entry["new_version"]
    assert [(v["version"], v["status"], v["n_runs"]) for v in all_cell["versions"]] == [
        (entry["new_version"], "current", 1),
        (entry["old_version"], "historical", 5),
    ]
    assert all_cell["aggregate"]["n_valid"] == 1  # the 5 old-version rows are NOT pooled in
    assert all_cell["task_versions"] == [entry["old_version"], entry["new_version"]]

    # evaluation-scoped + exact-run surfaces are unaffected
    report = client.get(f"/api/v1/jobs/{evaluation_id}/report.json")
    assert report.status_code == 200
    (trial,) = report.json()["trials"]
    assert trial["task_version"] == entry["new_version"]
    assert trial["backend_kind"] == "mock" and trial["provenance"] == "consistent"
    assert client.get(f"/api/v1/runs/{trial['run_id']}").status_code == 200
    assert client.get(f"/api/v1/jobs/{evaluation_id}/results").status_code == 200


# --------------------------------------------------------------------------- #
# 4. reuse across an ORACLE version/digest change fails closed
# --------------------------------------------------------------------------- #


def test_reuse_within_an_unchanged_task_snapshot_is_allowed_and_creates_no_raw_evidence(
    client: TestClient, working_db: Path
):
    """Positive control: the negative cases below are refused because of the
    snapshot change, not for an unrelated reason."""
    task_id, model = "sanitize-filename", _fresh_model()
    a = _create(client, model, task_id)
    assert a.status_code == 200, a.text
    assert _wait_terminal(client, a.json()["id"])["status"] == "succeeded"
    runs_before, jobs_before = _counts(working_db)

    reused = _create(client, model, task_id, mode="reuse", source=a.json()["id"])
    assert reused.status_code == 200, reused.text
    report = client.get(f"/api/v1/jobs/{reused.json()['id']}/report.json").json()
    (trial,) = report["trials"]
    assert trial["evidence_state"] == "reused"
    assert trial["comparability"] == "provisional"
    assert trial["source_evaluation_id"] == a.json()["id"]
    assert trial["origin_evaluation_id"] == a.json()["id"]

    runs_after, jobs_after = _counts(working_db)
    assert runs_after == runs_before
    assert jobs_after == jobs_before + 1


@pytest.mark.parametrize("case", ["pre_remediation_version", "same_version_changed_oracle"])
def test_reuse_across_incompatible_oracle_task_snapshots_fails_closed(
    client: TestClient, working_db: Path, tmp_path: Path, case: str
):
    task_id = "sanitize-filename"
    entry = BUMPED[task_id]
    model = _fresh_model()

    # Evaluation A runs against a private copy of the task shaped like an
    # earlier benchmark state.
    old_root = _private_task_root(tmp_path, task_id, "old_root")
    if case == "pre_remediation_version":
        _set_version(old_root, task_id, entry["old_version"])
    else:
        hidden = old_root / "tasks" / task_id / "grading" / "test_hidden.py"
        hidden.write_text(hidden.read_text() + "\n# earlier oracle state\n")
    with _tasks_rooted_at(old_root):
        source_snapshot = jobs.task_snapshot(task_id)
        a = _create(client, model, task_id)
        assert a.status_code == 200, a.text
        assert _wait_terminal(client, a.json()["id"])["status"] == "succeeded"

    current = jobs.task_snapshot(task_id)  # real, current ORACLE task
    assert source_snapshot["task_digest"] != current["task_digest"]
    if case == "pre_remediation_version":
        assert source_snapshot["task_version"] == entry["old_version"] != current["task_version"]
    else:
        assert source_snapshot["task_version"] == current["task_version"]  # version alone is NOT enough

    runs_before, jobs_before = _counts(working_db)
    response = _create(client, model, task_id, mode="reuse", source=a.json()["id"])

    assert response.status_code == 409, response.text
    assert "incompatible" in response.text
    # atomic: no evaluation row, no raw evidence, no laundering
    assert _counts(working_db) == (runs_before, jobs_before)


def test_reuse_of_legacy_historical_evidence_is_refused(client: TestClient, working_db: Path):
    """Pre-ATLAS runs (all 720 historical rows) belong to no evaluation, so
    they cannot be laundered into a current evaluation by reuse."""
    conn = db.connect_readonly(working_db)
    try:
        legacy_runs = conn.execute("SELECT COUNT(*) FROM runs WHERE job_id IS NULL").fetchone()[0]
    finally:
        conn.close()
    assert legacy_runs == 720

    runs_before, jobs_before = _counts(working_db)
    response = _create(client, _fresh_model(), "sanitize-filename", mode="reuse",
                       source="does-not-exist")
    assert response.status_code == 409, response.text
    assert _counts(working_db) == (runs_before, jobs_before)


# --------------------------------------------------------------------------- #
# 5. task digest scope: ORACLE's integrity/ subtree x ATLAS drift protection
# --------------------------------------------------------------------------- #


def test_digest_covers_integrity_subtree_and_grading_but_execution_never_reads_integrity(
    client: TestClient, tmp_path: Path
):
    """Characterization test (documented limitation, see the integration report).

    ATLAS hashes EVERY file under tasks/<id>/, so editing ORACLE's integrity/
    controls or integrity.json changes the digest and makes older snapshots
    refuse to resume/reuse (fail-closed, spurious for grading). Execution and
    grading never read integrity/: the task still runs and scores identically
    with the subtree removed.
    """
    task_id = "sanitize-filename"
    root = _private_task_root(tmp_path, task_id, "digest_root")
    task_dir = root / "tasks" / task_id
    assert (task_dir / "integrity").is_dir()

    with _tasks_rooted_at(root):
        base = jobs.task_snapshot(task_id)
        assert jobs.task_snapshot(task_id) == base  # deterministic
        stale = {"tasks": [base]}
        jobs.validate_snapshot_tasks(stale)  # unchanged pack -> no drift

        control_json = next((task_dir / "integrity").rglob("control.json"))
        original = control_json.read_text()

        control_json.write_text(original + "\n")
        touched = jobs.task_snapshot(task_id)
        assert touched["task_version"] == base["task_version"]
        assert touched["task_digest"] != base["task_digest"]
        with pytest.raises(jobs.JobStateError, match="changed since evaluation creation"):
            jobs.validate_snapshot_tasks(stale)

        control_json.write_text(original)  # byte-exact restore -> digest returns
        assert jobs.task_snapshot(task_id) == base
        jobs.validate_snapshot_tasks(stale)

        added = task_dir / "integrity" / "new_note.txt"
        added.write_text("x")
        assert jobs.task_snapshot(task_id)["task_digest"] != base["task_digest"]
        added.unlink()

        hidden = task_dir / "grading" / "test_hidden.py"
        hidden_original = hidden.read_text()
        hidden.write_text(hidden_original + "\n# edit\n")
        assert jobs.task_snapshot(task_id)["task_digest"] != base["task_digest"]
        hidden.write_text(hidden_original)

        _set_version(root, task_id, "9.9.9")
        bumped = jobs.task_snapshot(task_id)
        assert bumped["task_version"] == "9.9.9" and bumped["task_digest"] != base["task_digest"]
        _set_version(root, task_id, base["task_version"])

        # execution never needs integrity/: drop it and the task still passes.
        shutil.rmtree(task_dir / "integrity")
        without = jobs.task_snapshot(task_id)
        assert without["task_digest"] != base["task_digest"]
        created = _create(client, _fresh_model(), task_id)
        assert created.status_code == 200, created.text
        assert _wait_terminal(client, created.json()["id"])["status"] == "succeeded"
        report = client.get(f"/api/v1/jobs/{created.json()['id']}/report.json").json()
        (trial,) = report["trials"]
        assert trial["outcome"]["functional_pass"] is True
        assert trial["outcome"]["final_score"] == 1.0
        assert trial["task_digest"] == without["task_digest"]


# --------------------------------------------------------------------------- #
# 6. ORACLE controls + overlay primitive through the merged runner
# --------------------------------------------------------------------------- #


def test_runrecord_and_overlay_primitives_coexist_in_the_merged_pipeline():
    fields = [f.name for f in dataclasses.fields(pipeline.RunRecord)]
    assert "run_id" in fields and "grade_report" in fields  # ATLAS persistence identity
    assert fields.index("run_id") < fields.index("grade_report")
    (run_id_field,) = [f for f in dataclasses.fields(pipeline.RunRecord) if f.name == "run_id"]
    assert run_id_field.default is None

    assert callable(pipeline.overlay_diff) and pipeline.overlay_diff is afa.overlay_diff  # ORACLE

    task = afa.load_task(REPO / "tasks" / "sanitize-filename")
    via_reference = pipeline._reference_diff(task)
    via_overlay = pipeline.overlay_diff(task, task.reference_dir)
    assert via_reference == via_overlay  # _reference_diff delegates to overlay_diff

    # ATLAS's mock agent writes the same reference files ORACLE overlays.
    agent = worker.mock_agent_factory("integ-mock", task, JobParams())
    record = afa.run_once(agent, task, sandbox=afa.LocalSandbox(), idx=0)
    assert record.run_id is None  # absent before save
    assert record.score.functional_pass is True and record.score.final_score == 1.0
    assert record.files_changed == via_overlay.files_changed
    assert (record.lines_added, record.lines_removed) == (
        via_overlay.lines_added, via_overlay.lines_removed)
    assert record.grade_report is not None  # retained for atomic persistence


@pytest.mark.parametrize("task_id", ["sanitize-filename", "validate-redirect-url"])
def test_oracle_declared_controls_grade_correctly_through_the_merged_runner(task_id: str):
    task = afa.load_task(REPO / "tasks" / task_id)
    check, results = run_controls_check(task, afa.LocalSandbox())

    assert results, "no controls were discovered"
    assert {r.kind for r in results} == set(ControlKind)  # known-bad, mutant, alternative
    unmatched = [(r.name, r.verdict.value) for r in results if not r.matched_expectation]
    assert unmatched == []
    assert all(r.expected_accept for r in results if r.kind == ControlKind.ALTERNATIVE)
    assert not any(r.expected_accept for r in results if r.kind != ControlKind.ALTERNATIVE)
    assert check.status.value == "pass"


# --------------------------------------------------------------------------- #
# 7. the remediation manifest still describes the untouched historical evidence
# --------------------------------------------------------------------------- #


def test_remediation_manifest_matches_the_historical_db_and_current_task_versions():
    assert MANIFEST["summary"] == {
        "tasks_with_version_change": 18,
        "total_historical_runs_affected": 540,
        "model_task_cells_with_a_prior_pass_needing_verification": 51,
    }
    conn = db.connect_readonly(db.EVIDENCE_DB_PATH)
    try:
        total_runs = 0
        prior_pass_cells = 0
        for task_id, entry in BUMPED.items():
            rows = conn.execute(
                "SELECT r.agent, r.task_version, s.functional_pass FROM runs r "
                "JOIN run_scores s ON s.run_id=r.id WHERE r.task_id=?",
                (task_id,),
            ).fetchall()
            assert {r["task_version"] for r in rows} == {entry["old_version"]}, task_id
            assert len(rows) == entry["known_affected_runs"]["total"], task_id
            passers = sorted({r["agent"] for r in rows if r["functional_pass"]})
            assert passers == sorted(entry["known_affected_runs"]["models_with_a_prior_pass"]), task_id
            total_runs += len(rows)
            prior_pass_cells += len(passers)

            spec = json.loads((REPO / "tasks" / task_id / "task.json").read_text())
            assert spec["version"] == entry["new_version"], task_id
        assert (len(BUMPED), total_runs, prior_pass_cells) == (18, 540, 51)
    finally:
        conn.close()
