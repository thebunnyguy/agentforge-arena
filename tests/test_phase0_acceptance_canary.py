"""One coherent offline API canary for the Phase 0 acceptance boundary."""
from __future__ import annotations

import hashlib
import json
import shutil
import threading
import time
import uuid

from fastapi.testclient import TestClient

from afa_api import db, worker
from afa_api.main import create_app

TASK = "fix-binary-search"
TERMINAL = {"succeeded", "failed", "canceled"}


class ControlledInterruption(BaseException):
    """Test-only interruption that escapes run_once before raw publication."""


def _sha256(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _wait_terminal(client: TestClient, evaluation_id: str, timeout: float = 15.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        response = client.get(f"/api/v1/jobs/{evaluation_id}")
        assert response.status_code == 200
        body = response.json()
        if body["status"] in TERMINAL:
            return body
        time.sleep(0.01)
    raise AssertionError(f"evaluation {evaluation_id} did not reach a terminal state")


def _wait_until(predicate, timeout: float = 15.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.01)
    raise AssertionError("bounded canary observer timed out")


def _join_threads(records, timeout: float = 5.0) -> None:
    for _, thread in records:
        thread.join(timeout=timeout)
    assert all(not thread.is_alive() for _, thread in records)


def _create(client: TestClient, model: str, *, mode: str = "fresh", source: str | None = None):
    body = {
        "model": model,
        "backend": {"kind": "mock"},
        "tasks": [TASK],
        "repeats": 2,
        "mode": mode,
    }
    if source is not None:
        body["source_evaluation_id"] = source
    response = client.post("/api/v1/jobs", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def _report_pair(client: TestClient, evaluation_id: str) -> tuple[dict, str]:
    json_response = client.get(f"/api/v1/jobs/{evaluation_id}/report.json")
    markdown_response = client.get(f"/api/v1/jobs/{evaluation_id}/report.md")
    assert json_response.status_code == 200
    assert markdown_response.status_code == 200
    return json_response.json(), markdown_response.text


def _report_trial_block(markdown: str, trial: dict) -> str:
    marker = (
        f"### `{trial['task_id']}` @ `{trial['task_version']}` — trial {trial['idx']}"
    )
    start = markdown.index(marker)
    end = markdown.find("\n### ", start + len(marker))
    if end == -1:
        end = markdown.index("\n## Limitations", start)
    return markdown[start:end]


def _markdown_value(value) -> str:
    if value is None:
        return "unavailable"
    if isinstance(value, bool):
        return str(value).lower()
    return str(value)


def _assert_markdown_trial(markdown: str, trial: dict) -> None:
    block = _report_trial_block(markdown, trial)
    outcome = trial["outcome"]
    assert f"- Run ID: `{_markdown_value(trial['run_id'])}`" in block
    assert f"- Evidence: `{_markdown_value(trial['evidence_state'])}`" in block
    assert f"- Trial state: `{_markdown_value(trial['trial_state'])}`" in block
    assert f"- Outcome status: `{_markdown_value(outcome['status'])}`" in block
    assert f"- Functional pass: `{_markdown_value(outcome['functional_pass'])}`" in block
    assert f"- Voided: `{_markdown_value(outcome['voided'])}`" in block
    assert f"- Score: `{_markdown_value(outcome['final_score'])}`" in block
    assert f"- Artifacts: `{_markdown_value(trial['artifact_state'])}`" in block
    assert f"- Comparability: `{_markdown_value(trial['comparability'])}`" in block
    if outcome["voided"]:
        expected_result = f"VOIDED ({outcome['status']})"
    else:
        expected_result = "PASS" if outcome["functional_pass"] else "FAIL"
        if outcome["status"] != "valid":
            expected_result = f"{expected_result} ({outcome['status']})"
    assert f"- Result: `{expected_result}`" in block
    for label, key in (
        ("Source evaluation", "source_evaluation_id"),
        ("Source run ID", "source_run_id"),
        ("Origin evaluation", "origin_evaluation_id"),
    ):
        line = f"- {label}: `{_markdown_value(trial[key])}`"
        if trial[key] is None:
            assert line not in block
        else:
            assert line in block


def _trial_keys(payload: dict) -> set[tuple[str, str, int]]:
    return {
        (trial["task_id"], trial["task_version"], int(trial["idx"]))
        for trial in payload["trials"]
    }


def _trial_map(payload: dict) -> dict[tuple[str, str, int], dict]:
    trials = {
        (trial["task_id"], trial["task_version"], int(trial["idx"])): trial
        for trial in payload["trials"]
    }
    assert len(trials) == len(payload["trials"])
    return trials


def _assert_result_report_parity(results: dict, report: dict) -> None:
    result_trials = _trial_map(results)
    report_trials = _trial_map(report)
    assert result_trials.keys() == report_trials.keys()
    fields = (
        "run_id", "trial_state", "evidence_state", "source_evaluation_id",
        "source_run_id", "origin_evaluation_id", "error_message",
        "artifact_state", "comparability", "outcome",
    )
    for key, result_trial in result_trials.items():
        report_trial = report_trials[key]
        for field in fields:
            assert report_trial[field] == result_trial[field], (key, field)


def _assert_report_anchor(report: dict, creation: dict, model: str) -> None:
    snapshot = creation["snapshot"]
    assert report["model"] == model
    assert report["backend"] == snapshot["backend"]
    assert report["task_snapshots"] == snapshot["tasks"]
    assert report["generation"] == snapshot["generation"]
    assert report["evaluation_parameters"]["repeats"] == snapshot["repeats"]
    assert report["evaluation_parameters"]["model"] == model


def _assert_native_run(client: TestClient, run_id: int, evaluation_id: str, model: str, trial: dict) -> None:
    exact = client.get(f"/api/v1/runs/{run_id}")
    assert exact.status_code == 200
    exact_body = exact.json()
    assert exact_body["run_id"] == run_id
    assert exact_body["job_id"] == evaluation_id
    assert exact_body["agent"] == model
    assert exact_body["task_id"] == TASK
    assert exact_body["idx"] == trial["idx"]
    assert exact_body["task_version"] == trial["task_version"]
    assert exact_body["patch_available"] is True
    assert exact_body["test_results"]


def _assert_fresh_evaluation(
    client: TestClient,
    evaluation_id: str,
    creation: dict,
    report: dict,
    expected_runs: set[int],
    model: str,
) -> dict:
    results = client.get(f"/api/v1/jobs/{evaluation_id}/results").json()
    assert results["evaluation_id"] == evaluation_id
    assert results["status"] == "succeeded"
    assert results["counters"]["completed_runs"] == 2
    assert results["snapshot"]["tasks"] == report["task_snapshots"]
    assert results["snapshot"]["repeats"] == 2
    assert _trial_keys(results) == {
        (TASK, report["task_snapshots"][0]["task_version"], 0),
        (TASK, report["task_snapshots"][0]["task_version"], 1),
    }
    assert {trial["run_id"] for trial in results["trials"]} == expected_runs
    assert all(trial["evidence_state"] == "fresh" for trial in results["trials"])
    assert all(trial["source_evaluation_id"] is None for trial in results["trials"])
    assert all(trial["source_run_id"] is None for trial in results["trials"])
    assert all(trial["origin_evaluation_id"] == evaluation_id for trial in results["trials"])
    assert report["evaluation_id"] == evaluation_id
    assert report["mode"] == "fresh"
    assert report["counters"]["total"] == 2
    assert report["counters"]["completed"] == 2
    assert report["counters"]["reused"] == 0
    assert _trial_keys(report) == _trial_keys(results)
    assert {trial["run_id"] for trial in report["trials"]} == expected_runs
    assert all(trial["outcome"] is not None for trial in report["trials"])
    _assert_report_anchor(report, creation, model)
    _assert_result_report_parity(results, report)
    return results


def test_phase0_acceptance_canary_real_api_offline(tmp_path, monkeypatch):
    historical_before = _sha256(db.DB_PATH)
    working_db = tmp_path / "phase0-canary.sqlite"
    shutil.copy(db.DB_PATH, working_db)
    model = f"phase0-canary-{uuid.uuid4().hex}"

    interrupted = threading.Event()
    interrupted_attempts: list[dict] = []
    resumed_attempts: list[dict] = []
    recovery_attempts: list[dict] = []
    observed_threads: list[tuple[str, threading.Thread]] = []
    intentional_thread_errors: list[BaseException] = []
    unexpected_thread_errors: list[BaseException] = []
    original_thread_hook = threading.excepthook

    def canary_thread_hook(args):
        if isinstance(args.exc_value, ControlledInterruption):
            intentional_thread_errors.append(args.exc_value)
            return
        unexpected_thread_errors.append(args.exc_value)
        original_thread_hook(args)

    monkeypatch.setattr(threading, "excepthook", canary_thread_hook)
    real_dispatch = worker.dispatch_job

    def observed_dispatch(db_path, job_id, **kwargs):
        thread = real_dispatch(db_path, job_id, **kwargs)
        observed_threads.append((job_id, thread))
        return thread

    monkeypatch.setattr(worker, "dispatch_job", observed_dispatch)

    def interrupting_factory(name, task, params):
        base = worker.mock_agent_factory(name, task, params)
        current_seed = {"value": None}

        class InterruptingAgent:
            name = base.name

            def set_run_seed(self, seed):
                current_seed["value"] = seed
                setter = getattr(base, "set_run_seed", None)
                if callable(setter):
                    setter(seed)

            def act(self, workspace, task_obj, sandbox):
                seed = current_seed["value"]
                idx = seed - params.base_seed if isinstance(seed, int) else None
                interrupted_attempts.append({"idx": idx, "seed": seed})
                if idx == 1:
                    interrupted.set()
                    # The real worker does not catch BaseException here; its
                    # owner-finally releases the lock without publishing a row.
                    raise ControlledInterruption("controlled canary interruption")
                return base.act(workspace, task_obj, sandbox)

        return InterruptingAgent()

    def tracking_factory(name, task, params):
        base = worker.mock_agent_factory(name, task, params)
        current_seed = {"value": None}

        class TrackingAgent:
            name = base.name

            def set_run_seed(self, seed):
                current_seed["value"] = seed
                setter = getattr(base, "set_run_seed", None)
                if callable(setter):
                    setter(seed)

            def act(self, workspace, task_obj, sandbox):
                seed = current_seed["value"]
                resumed_attempts.append({
                    "idx": seed - params.base_seed if isinstance(seed, int) else None,
                    "seed": seed,
                })
                return base.act(workspace, task_obj, sandbox)

        return TrackingAgent()

    def recovery_tracking_factory(name, task, params):
        base = worker.mock_agent_factory(name, task, params)
        current_seed = {"value": None}

        class RecoveryTrackingAgent:
            name = base.name

            def set_run_seed(self, seed):
                current_seed["value"] = seed
                setter = getattr(base, "set_run_seed", None)
                if callable(setter):
                    setter(seed)

            def act(self, workspace, task_obj, sandbox):
                seed = current_seed["value"]
                recovery_attempts.append({
                    "idx": seed - params.base_seed if isinstance(seed, int) else None,
                    "seed": seed,
                })
                return base.act(workspace, task_obj, sandbox)

        return RecoveryTrackingAgent()

    app = create_app()
    app.state.db_path = working_db
    app.state.agent_factory = worker.mock_agent_factory

    try:
        with TestClient(app) as client:
            # A: real API creation, registered dispatch, fresh evidence, and exact
            # native-run forensics for two requested positions.
            evaluation_a = _create(client, model)
            a_id = evaluation_a["id"]
            assert a_id
            assert _wait_terminal(client, a_id)["status"] == "succeeded"
            a_report, a_markdown = _report_pair(client, a_id)
            a_results = _assert_fresh_evaluation(
                client, a_id, evaluation_a, a_report,
                {trial["run_id"] for trial in a_report["trials"]}, model,
            )
            a_runs = {trial["run_id"] for trial in a_report["trials"]}
            assert len(a_runs) == 2
            for run_id in a_runs:
                matching = next(trial for trial in a_report["trials"] if trial["run_id"] == run_id)
                _assert_native_run(client, run_id, a_id, model, matching)

            # Immediate live discovery without app restart/source roster edits.
            # The canary drives the mock backend, i.e. synthetic evidence: it is
            # EXCLUDED from the default benchmark view (reported, not hidden) and
            # discoverable through the explicit synthetic view.
            default_overview = client.get("/api/v1/overview").json()
            assert model not in default_overview["models"]
            assert model in default_overview["excluded"]["synthetic_models"]
            overview = client.get("/api/v1/overview?evidence=synthetic").json()
            assert model in overview["models"]
            assert overview["real_counts"][model]["n_runs"] >= 2
            assert overview["real_counts"][model]["n_tasks"] >= 1
            cell = client.get(f"/api/v1/cell/{model}/{TASK}?evidence=synthetic").json()
            assert cell["captured"] is True
            assert cell["state"] == "captured"
            assert set(cell["task_versions"]) == {a_report["task_snapshots"][0]["task_version"]}
            assert {run["idx"] for run in cell["runs"]} == {0, 1}
            assert cell["aggregate"]["n_valid"] >= 2
            domains = client.get(f"/api/v1/domains/{model}?evidence=synthetic").json()
            assert domains["captured"] is True
            assert domains["agent"] == model
            assert any(domain["n_runs"] >= 2 for domain in domains["domains"])

            # B: identical fresh request, with a different evaluation and disjoint
            # native evidence rather than the old global skip behavior.
            evaluation_b = _create(client, model)
            b_id = evaluation_b["id"]
            assert b_id != a_id
            assert _wait_terminal(client, b_id)["status"] == "succeeded"
            b_report, b_markdown = _report_pair(client, b_id)
            b_runs = {trial["run_id"] for trial in b_report["trials"]}
            b_results = _assert_fresh_evaluation(
                client, b_id, evaluation_b, b_report, b_runs, model
            )
            assert len(b_runs) == 2
            assert a_runs.isdisjoint(b_runs)
            assert a_report["task_snapshots"] == b_report["task_snapshots"]
            assert a_report["evaluation_parameters"] == b_report["evaluation_parameters"]
            assert a_report["counters"]["reused"] == 0
            assert b_report["counters"]["reused"] == 0
            assert a_id not in str(b_report) and f"Evaluation: `{a_id}`" not in b_markdown
            assert b_id not in str(a_report) and f"Evaluation: `{b_id}`" not in a_markdown
            assert {trial["run_id"] for trial in a_report["trials"]}.isdisjoint(
                {trial["run_id"] for trial in b_report["trials"]}
            )
            for trial in a_report["trials"]:
                _assert_markdown_trial(a_markdown, trial)
                block = _report_trial_block(a_markdown, trial)
                for other in b_runs:
                    assert f"- Run ID: `{other}`" not in block
            for trial in b_report["trials"]:
                _assert_markdown_trial(b_markdown, trial)
                block = _report_trial_block(b_markdown, trial)
                for other in a_runs:
                    assert f"- Run ID: `{other}`" not in block
            assert _trial_keys(a_results) == _trial_keys(b_results)
            for run_id in b_runs:
                matching = next(trial for trial in b_report["trials"] if trial["run_id"] == run_id)
                _assert_native_run(client, run_id, b_id, model, matching)

            # C: explicit reuse through the API; a read-only DB observer checks the
            # forbidden effect (new raw rows), while the API owns creation/reporting.
            conn = db.connect_readonly(working_db)
            try:
                raw_before_reuse = [row["id"] for row in conn.execute("SELECT id FROM runs ORDER BY id")]
            finally:
                conn.close()
            evaluation_c = _create(client, model, mode="reuse", source=a_id)
            c_id = evaluation_c["id"]
            assert c_id not in {a_id, b_id}
            assert _wait_terminal(client, c_id)["status"] == "succeeded"
            conn = db.connect_readonly(working_db)
            try:
                raw_after_reuse = [row["id"] for row in conn.execute("SELECT id FROM runs ORDER BY id")]
            finally:
                conn.close()
            assert raw_after_reuse == raw_before_reuse
            c_report, c_markdown = _report_pair(client, c_id)
            c_results = client.get(f"/api/v1/jobs/{c_id}/results").json()
            c_runs = {trial["run_id"] for trial in c_results["trials"]}
            assert len(c_runs) == 2
            assert None not in c_runs
            assert c_report["evaluation_id"] == c_id
            assert c_report["mode"] == "reuse"
            assert c_report["counters"]["completed"] == 2
            assert c_report["counters"]["reused"] == 2
            _assert_report_anchor(c_report, evaluation_c, model)
            _assert_result_report_parity(c_results, c_report)
            a_by_key = _trial_map(a_results)
            c_by_key = _trial_map(c_results)
            assert c_by_key.keys() == a_by_key.keys()
            for key, a_trial in a_by_key.items():
                c_trial = c_by_key[key]
                assert c_trial["run_id"] == a_trial["run_id"]
                assert c_trial["source_evaluation_id"] == a_id
                assert c_trial["source_run_id"] == a_trial["run_id"]
                assert c_trial["origin_evaluation_id"] == a_id
                assert c_trial["evidence_state"] == "reused"
                assert c_trial["comparability"] == "provisional"
                _assert_markdown_trial(c_markdown, c_trial)
                block = _report_trial_block(c_markdown, c_trial)
                assert f"- Run ID: `{a_trial['run_id']}`" in block
                assert f"- Source evaluation: `{a_id}`" in block
                assert f"- Source run ID: `{a_trial['run_id']}`" in block
                assert f"- Origin evaluation: `{a_id}`" in block
            assert c_runs == {trial["run_id"] for trial in c_report["trials"]}
            assert "not freshly executed" in c_markdown

            # D: install the observer before dispatch. The first position is a
            # real committed run; the second raises before raw persistence. The
            # API cancel plus registered-lifespan recovery preserves the hole,
            # then explicit same-ID API resume executes only the pending position.
            app.state.agent_factory = interrupting_factory
            d_dispatch_start = len(observed_threads)
            evaluation_d = _create(client, model)
            d_id = evaluation_d["id"]
            assert interrupted.wait(15.0)

            def interrupted_state():
                body = client.get(f"/api/v1/jobs/{d_id}").json()
                return body if body["counters"]["completed_runs"] == 1 and body["status"] == "running" else False

            interrupted_job = _wait_until(interrupted_state)
            d_initial_threads = [
                record for record in observed_threads[d_dispatch_start:] if record[0] == d_id
            ]
            assert len(d_initial_threads) == 1
            d_before = client.get(f"/api/v1/jobs/{d_id}/results").json()
            first_d_run = next(trial["run_id"] for trial in d_before["trials"] if trial["idx"] == 0)
            assert first_d_run is not None
            assert next(trial for trial in d_before["trials"] if trial["idx"] == 1)["run_id"] is None
            assert interrupted_job["id"] == d_id
            assert interrupted_attempts == [{"idx": 0, "seed": 1000}, {"idx": 1, "seed": 1001}]
            canceled = client.post(f"/api/v1/jobs/{d_id}/cancel")
            assert canceled.status_code == 200
            assert canceled.json()["cancel_requested"] is True
            _join_threads(d_initial_threads)
            assert len(intentional_thread_errors) == 1
            assert not unexpected_thread_errors

        # Close/recreate the registered app against the same DB. Startup recovery
        # observes the released lock and terminalizes the requested cancellation.
        recovery_start = len(observed_threads)
        recovery_app = create_app()
        recovery_app.state.db_path = working_db
        recovery_app.state.agent_factory = recovery_tracking_factory
        with TestClient(recovery_app) as client:
            def recovered_canceled_state():
                body = client.get(f"/api/v1/jobs/{d_id}").json()
                return body if body["status"] == "canceled" else False

            canceled_after_recovery = _wait_until(recovered_canceled_state)
            assert canceled_after_recovery["cancel_requested"] is True
            recovery_threads = [
                record for record in observed_threads[recovery_start:] if record[0] == d_id
            ]
            _join_threads(recovery_threads)
            assert recovery_attempts == []
            recovery_app.state.agent_factory = tracking_factory
            resumed = client.post(f"/api/v1/jobs/{d_id}/resume")
            assert resumed.status_code == 200
            assert resumed.json()["id"] == d_id
            done_d = _wait_terminal(client, d_id)
            assert done_d["id"] == d_id
            assert done_d["status"] == "succeeded"
            resume_threads = [
                record for record in observed_threads[recovery_start:] if record[0] == d_id
            ]
            _join_threads(resume_threads)
            assert resumed_attempts == [{"idx": 1, "seed": 1001}]
            d_after = client.get(f"/api/v1/jobs/{d_id}/results").json()
            assert next(trial["run_id"] for trial in d_after["trials"] if trial["idx"] == 0) == first_d_run
            d_runs = {trial["run_id"] for trial in d_after["trials"]}
            assert len(d_runs) == 2
            assert None not in d_runs
            d_report, d_markdown = _report_pair(client, d_id)
            assert d_report["evaluation_id"] == d_id
            assert d_report["counters"]["completed"] == 2
            assert d_report["counters"]["reused"] == 0
            _assert_result_report_parity(d_after, d_report)
            assert _trial_keys(d_after) == _trial_keys(d_report)
            assert {trial["run_id"] for trial in d_report["trials"]} == d_runs
            _assert_report_anchor(d_report, evaluation_d, model)
            for trial in d_report["trials"]:
                assert trial["source_evaluation_id"] is None
                assert trial["source_run_id"] is None
                assert trial["origin_evaluation_id"] == d_id
                _assert_markdown_trial(d_markdown, trial)
            conn = db.connect_readonly(working_db)
            try:
                raw_d = [
                    dict(row)
                    for row in conn.execute(
                        "SELECT id, task_id, idx, job_id FROM runs WHERE job_id=? ORDER BY id",
                        (d_id,),
                    )
                ]
            finally:
                conn.close()
            assert {row["id"] for row in raw_d} == d_runs
            assert {(row["task_id"], row["idx"]) for row in raw_d} == {(TASK, 0), (TASK, 1)}
            assert all(row["job_id"] == d_id for row in raw_d)

            # Capture exact API results, native forensics, and both report formats
            # for every evaluation before the final app recreation.
            evaluation_ids = (a_id, b_id, c_id, d_id)
            pre_results = {
                evaluation_id: client.get(f"/api/v1/jobs/{evaluation_id}/results").json()
                for evaluation_id in evaluation_ids
            }
            pre_reports = {
                evaluation_id: _report_pair(client, evaluation_id)
                for evaluation_id in evaluation_ids
            }
            native_ids = a_runs | b_runs | d_runs
            pre_native = {
                run_id: client.get(f"/api/v1/runs/{run_id}").json()
                for run_id in native_ids
            }

        # No worker from any phase may remain alive before the historical after-hash.
        _join_threads(observed_threads)
        assert not unexpected_thread_errors

        restarted = create_app()
        restarted.state.db_path = working_db
        restarted.state.agent_factory = worker.mock_agent_factory
        restart_result_matches = {}
        restart_report_matches = {}
        restart_native_matches = {}
        with TestClient(restarted) as client:
            for evaluation_id in (a_id, b_id, c_id, d_id):
                assert client.get(f"/api/v1/jobs/{evaluation_id}").status_code == 200
                actual_results = client.get(f"/api/v1/jobs/{evaluation_id}/results").json()
                restart_result_matches[evaluation_id] = actual_results == pre_results[evaluation_id]
                assert restart_result_matches[evaluation_id]
                report, markdown = _report_pair(client, evaluation_id)
                old_report, old_markdown = pre_reports[evaluation_id]
                restart_report_matches[evaluation_id] = (
                    report == old_report and markdown == old_markdown
                )
                assert restart_report_matches[evaluation_id]
                assert report["evaluation_id"] == evaluation_id
                assert f"Evaluation: `{evaluation_id}`" in markdown
            for run_id, expected in pre_native.items():
                actual_native = client.get(f"/api/v1/runs/{run_id}").json()
                restart_native_matches[run_id] = actual_native == expected
                assert restart_native_matches[run_id]
            overview = client.get("/api/v1/overview?evidence=synthetic").json()
            assert model in overview["models"]
            assert overview["real_counts"][model]["n_runs"] >= 6
            assert client.get(
                f"/api/v1/cell/{model}/{TASK}?evidence=synthetic"
            ).json()["captured"] is True

        _join_threads(observed_threads)
        assert len(intentional_thread_errors) == 1
        assert not unexpected_thread_errors
    finally:
        for _, thread in observed_threads:
            thread.join(timeout=5.0)
        assert all(not thread.is_alive() for _, thread in observed_threads)

    historical_after = _sha256(db.DB_PATH)
    assert historical_before == "42b6dad85ee662d6d5d7f75ffbda5a3b95d50837837f81c875730a8987838ced"
    assert historical_after == historical_before
    print(
        "PHASE0_CANARY_RECEIPT "
        + json.dumps(
            {
                "evaluations": {"A": a_id, "B": b_id, "C": c_id, "D": d_id},
                "raw_runs": {
                    "A": sorted(a_runs),
                    "B": sorted(b_runs),
                    "C": sorted(c_runs),
                    "D": sorted(d_runs),
                    "D_rows": raw_d,
                },
                "interrupted_attempts": interrupted_attempts,
                "resumed_attempts": resumed_attempts,
                "recovery_attempts": recovery_attempts,
                "intentional_thread_errors": len(intentional_thread_errors),
                "unexpected_thread_errors": len(unexpected_thread_errors),
                "restart_result_matches": restart_result_matches,
                "restart_report_matches": restart_report_matches,
                "restart_native_matches": restart_native_matches,
                "historical_before": historical_before,
                "historical_after": historical_after,
            },
            sort_keys=True,
        )
    )
