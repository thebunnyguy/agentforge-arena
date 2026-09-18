"""Evaluation-scoped report API tests over temporary deterministic databases."""
from __future__ import annotations

import json
import shutil
import time

import pytest
from fastapi.testclient import TestClient

from afa_api import db, jobs, worker
from afa_api.evaluation_report import build_evaluation_report
from afa_api.main import create_app

TASK = "fix-binary-search"
TERMINAL = {"succeeded", "failed", "canceled"}


@pytest.fixture()
def report_db(tmp_path):
    path = tmp_path / "reports.sqlite"
    shutil.copy(db.DB_PATH, path)
    conn = db.connect(path)
    try:
        db.migrate(conn)
    finally:
        conn.close()
    return path


@pytest.fixture()
def report_client(report_db):
    app = create_app()
    app.state.db_path = report_db
    app.state.agent_factory = worker.mock_agent_factory
    with TestClient(app) as client:
        yield client


def wait_terminal(client: TestClient, job_id: str) -> dict:
    for _ in range(500):
        body = client.get(f"/api/v1/jobs/{job_id}").json()
        if body.get("status") in TERMINAL:
            return body
        time.sleep(0.01)
    raise AssertionError(f"job {job_id} did not reach a terminal state")


def create_done(
    client: TestClient, model: str, repeats: int = 2, **overrides
) -> tuple[str, dict]:
    body = {
        "model": model,
        "backend": {"kind": "mock"},
        "tasks": [TASK],
        "repeats": repeats,
    }
    body.update(overrides)
    response = client.post("/api/v1/jobs", json=body)
    assert response.status_code == 200
    job_id = response.json()["id"]
    return job_id, wait_terminal(client, job_id)


def report_pair(client: TestClient, job_id: str) -> tuple[dict, str]:
    json_response = client.get(f"/api/v1/jobs/{job_id}/report.json")
    markdown_response = client.get(f"/api/v1/jobs/{job_id}/report.md")
    assert json_response.status_code == 200
    assert markdown_response.status_code == 200
    assert markdown_response.headers["content-type"].startswith("text/markdown")
    return json_response.json(), markdown_response.text


def markdown_trial_block(markdown: str, trial: dict) -> str:
    marker = (
        f"### `{trial['task_id']}` @ `{trial['task_version']}` — trial {trial['idx']}"
    )
    start = markdown.index(marker)
    end = markdown.find("\n### ", start + len(marker))
    if end == -1:
        end = markdown.index("\n## Limitations", start)
    return markdown[start:end]


def compact_json(value) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def assert_markdown_trial_fields(markdown: str, trial: dict) -> str:
    block = markdown_trial_block(markdown, trial)
    outcome = trial["outcome"] or {}
    for label, value in (
        ("Run ID", trial["run_id"]),
        ("Evidence", trial["evidence_state"]),
        ("Trial state", trial["trial_state"]),
        ("Outcome status", outcome.get("status")),
        ("Functional pass", outcome.get("functional_pass")),
        ("Voided", outcome.get("voided")),
        ("Score", outcome.get("final_score")),
        ("Artifacts", trial["artifact_state"]),
        ("Comparability", trial["comparability"]),
    ):
        rendered = "unavailable" if value is None else str(value).lower() if isinstance(value, bool) else str(value)
        assert f"- {label}: `{rendered}`" in block
    if not outcome:
        result = "UNAVAILABLE"
    elif outcome.get("voided"):
        result = f"VOIDED ({outcome.get('status')})" if outcome.get("status") else "VOIDED"
    else:
        result = "PASS" if outcome.get("functional_pass") else "FAIL"
        if outcome.get("status") and outcome["status"] != "valid":
            result = f"{result} ({outcome['status']})"
    assert f"- Result: `{result}`" in block
    for label, key in (
        ("Source evaluation", "source_evaluation_id"),
        ("Source run ID", "source_run_id"),
        ("Origin evaluation", "origin_evaluation_id"),
    ):
        value = trial[key]
        rendered = "unavailable" if value is None else str(value)
        line = f"- {label}: `{rendered}`"
        assert (line in block) is (value is not None)
    return block


def report_native_ids(report: dict) -> set[int]:
    return {
        value
        for trial in report["trials"]
        for key in ("run_id", "source_run_id")
        if (value := trial[key]) is not None
    }


def insert_raw_report_job(
    report_db, job_id: str, params_json: str, snapshot_json: str | None = None
) -> None:
    conn = db.connect(report_db)
    try:
        conn.execute(
            "INSERT INTO evaluation_jobs "
            "(id, status, cancel_requested, params_json, total_runs, completed_runs, "
            "passed_runs, voided_runs, failed_runs, reused_runs, mode, snapshot_json) "
            "VALUES (?, 'failed', 0, ?, 0, 0, 0, 0, 0, 0, 'legacy', ?)",
            (job_id, params_json, snapshot_json),
        )
        conn.commit()
    finally:
        conn.close()


def test_reports_are_scoped_deterministic_and_survive_app_reopen(report_client, report_db):
    first_id, first_job = create_done(
        report_client,
        "report-scope-model",
        base_seed=4321,
        temperature=0.25,
        request_timeout_s=17,
        name="nondefault-report",
    )
    second_id, second_job = create_done(report_client, "report-scope-model")
    first, first_md = report_pair(report_client, first_id)
    second, second_md = report_pair(report_client, second_id)

    assert first["schema_version"] == 1
    assert first["evaluation_id"] == first_id
    assert first["status"] == "succeeded"
    assert first["mode"] == "fresh"
    assert first["model"] == "report-scope-model"
    assert first["provider"] == "mock"
    assert first["backend"] == {"kind": "mock", "base_url": None}
    assert first["created_at"] == first_job["created_at"]
    assert first["started_at"] == first_job["started_at"]
    assert first["finished_at"] == first_job["finished_at"]
    assert first["evaluation_parameters"] == {
        "model": "report-scope-model",
        "name": "nondefault-report",
        "repeats": 2,
        "base_seed": 4321,
        "temperature": 0.25,
        "request_timeout_s": 17,
        "backend": {"kind": "mock", "base_url": None},
        "source_evaluation_id": None,
    }
    assert first["generation"] == {
        "base_seed": 4321,
        "temperature": 0.25,
        "request_timeout_s": 17,
        "seed_provenance": "unavailable",
        "timeout_provenance": "not_applicable",
    }
    assert first["task_snapshots"][0]["task_id"] == TASK
    assert first["task_snapshots"][0]["task_version"]
    assert first["task_snapshots"][0]["task_digest"].startswith("sha256:")
    assert first["counters"] == {
        "total": 2,
        "completed": 2,
        "passed": 2,
        "failed": 0,
        "voided": 0,
        "reused": 0,
        "incomplete": 0,
        "unavailable": 0,
    }
    assert first["counter_semantics"]["passed"].startswith("fresh completed")
    assert first["counter_semantics"]["unavailable"].startswith("rows without")
    first_runs = {trial["run_id"] for trial in first["trials"]}
    second_runs = {trial["run_id"] for trial in second["trials"]}
    assert first_runs.isdisjoint(second_runs)
    for trial in first["trials"]:
        assert trial["outcome"]["status"] == "valid"
        assert trial["outcome"]["functional_pass"] is True
        assert trial["outcome"]["voided"] is False
        assert trial["comparability"] == "comparable"
        assert trial["artifact_state"] == "complete"
    assert f"- Evaluation: `{first_id}`" in first_md
    assert f"- Evaluation: `{second_id}`" not in first_md
    assert f"- Evaluation: `{first_id}`" not in second_md
    assert report_native_ids(first).isdisjoint(report_native_ids(second))
    for trial in first["trials"]:
        block = assert_markdown_trial_fields(first_md, trial)
        assert f"- Run ID: `{trial['run_id']}`" in block
        assert f"- Evidence: `{trial['evidence_state']}`" in block
        assert f"- Trial state: `{trial['trial_state']}`" in block
        assert f"- Outcome status: `{trial['outcome']['status']}`" in block
        assert f"- Functional pass: `{str(trial['outcome']['functional_pass']).lower()}`" in block
        assert f"- Voided: `{str(trial['outcome']['voided']).lower()}`" in block
        assert f"- Score: `{trial['outcome']['final_score']}`" in block
        assert f"- Artifacts: `{trial['artifact_state']}`" in block
        assert f"- Comparability: `{trial['comparability']}`" in block
        for other_run_id in second_runs:
            assert f"- Run ID: `{other_run_id}`" not in block
    for trial in second["trials"]:
        block = assert_markdown_trial_fields(second_md, trial)
        assert f"- Run ID: `{trial['run_id']}`" in block
        for other_run_id in first_runs:
            assert f"- Run ID: `{other_run_id}`" not in block
    assert f"Created at: `{first['created_at']}`" in first_md
    assert f"Started at: `{first['started_at']}`" in first_md
    assert f"Finished at: `{first['finished_at']}`" in first_md
    first_task = first["task_snapshots"][0]
    assert (
        f"- `{first_task['task_id']}` @ `{first_task['task_version']}` "
        f"(`{first_task['task_digest']}`)"
    ) in first_md
    assert 'Backend: `{"base_url":null,"kind":"mock"}`' in first_md
    assert f"- Parameters: `{compact_json(first['evaluation_parameters'])}`" in first_md
    assert f"- Generation: `{compact_json(first['generation'])}`" in first_md
    assert '"base_seed":4321' in first_md
    assert '"seed_provenance":"unavailable"' in first_md
    assert "Outcome status: `valid`" in first_md
    assert "Functional pass: `true`" in first_md
    assert "Voided: `false`" in first_md
    assert "Score: `1.0`" in first_md
    assert "Artifacts: `complete`" in first_md
    assert "Comparability: `comparable`" in first_md
    assert first == report_pair(report_client, first_id)[0]
    assert first_md == report_pair(report_client, first_id)[1]
    assert first_job["id"] != second_job["id"]

    reopened = create_app()
    reopened.state.db_path = report_db
    reopened.state.agent_factory = worker.mock_agent_factory
    with TestClient(reopened) as client:
        reopened_first, reopened_md = report_pair(client, first_id)
        assert client.get(f"/api/v1/jobs/{second_id}/report.json").status_code == 200
    assert reopened_first == first
    assert reopened_md == first_md


def test_reuse_report_marks_source_without_new_raw_runs(report_client, report_db):
    source_id, _ = create_done(report_client, "report-reuse-model")
    conn = db.connect_readonly(report_db)
    try:
        before = [row["id"] for row in conn.execute("SELECT id FROM runs ORDER BY id")]
    finally:
        conn.close()

    response = report_client.post(
        "/api/v1/jobs",
        json={
            "model": "report-reuse-model",
            "backend": {"kind": "mock"},
            "tasks": [TASK],
            "repeats": 2,
            "mode": "reuse",
            "source_evaluation_id": source_id,
        },
    )
    assert response.status_code == 200
    reused_id = response.json()["id"]
    wait_terminal(report_client, reused_id)
    report, markdown = report_pair(report_client, reused_id)

    conn = db.connect_readonly(report_db)
    try:
        after = [row["id"] for row in conn.execute("SELECT id FROM runs ORDER BY id")]
    finally:
        conn.close()
    assert after == before
    assert report["mode"] == "reuse"
    assert report["counters"]["reused"] == 2
    assert report["counters"]["passed"] == 0
    for trial in report["trials"]:
        assert trial["evidence_state"] == "reused"
        assert trial["source_evaluation_id"] == source_id
        assert trial["source_run_id"] is not None
        assert trial["origin_evaluation_id"] == source_id
        assert trial["comparability"] == "provisional"
        block = assert_markdown_trial_fields(markdown, trial)
        assert f"- Source evaluation: `{source_id}`" in block
        assert f"- Source run ID: `{trial['source_run_id']}`" in block
        assert f"- Origin evaluation: `{source_id}`" in block
    assert "not freshly executed" in markdown


def test_reports_show_partial_missing_and_unverifiable_artifacts(report_client, report_db):
    job_id, _ = create_done(report_client, "report-artifact-model", repeats=1)
    conn = db.connect(report_db)
    try:
        run_id = conn.execute(
            "SELECT run_id FROM evaluation_trials WHERE evaluation_id=?", (job_id,)
        ).fetchone()["run_id"]
        conn.execute("DELETE FROM test_results WHERE run_id=?", (run_id,))
        conn.commit()
    finally:
        conn.close()
    partial, partial_md = report_pair(report_client, job_id)
    assert partial["trials"][0]["artifact_state"] == "partial"
    assert partial["trials"][0]["comparability"] is None
    assert partial["counters"]["unavailable"] == 0
    assert "artifacts are partial" in partial_md

    conn = db.connect(report_db)
    try:
        conn.execute("DELETE FROM run_scores WHERE run_id=?", (run_id,))
        conn.commit()
    finally:
        conn.close()
    unavailable, unavailable_md = report_pair(report_client, job_id)
    assert unavailable["trials"][0]["artifact_state"] == "unavailable"
    assert unavailable["trials"][0]["outcome"] is None
    assert unavailable["counters"]["unavailable"] == 1
    assert "unavailable or unverifiable" in unavailable_md


def test_report_counts_incomplete_and_outcome_states(report_client, report_db):
    report_client.app.state.auto_dispatch = False
    pending_response = report_client.post(
        "/api/v1/jobs",
        json={"model": "pending-report-model", "backend": {"kind": "mock"}, "tasks": [TASK]},
    )
    assert pending_response.status_code == 200
    pending_id = pending_response.json()["id"]
    pending, pending_md = report_pair(report_client, pending_id)
    assert pending["counters"]["incomplete"] == 1
    assert pending["counters"]["unavailable"] == 1
    assert pending["trials"][0]["trial_state"] == "pending"
    assert pending["trials"][0]["evidence_state"] == "missing"
    assert "Trial state: `pending`" in pending_md
    assert "Result: `UNAVAILABLE`" in pending_md

    blocked_response = report_client.post(
        "/api/v1/jobs",
        json={"model": "blocked-report-model", "backend": {"kind": "mock"}, "tasks": [TASK]},
    )
    blocked_id = blocked_response.json()["id"]
    conn = db.connect(report_db)
    try:
        conn.execute(
            "UPDATE evaluation_trials SET trial_state='blocked', evidence_state='unverifiable', "
            "error_message='snapshot unavailable' WHERE evaluation_id=?",
            (blocked_id,),
        )
        conn.commit()
    finally:
        conn.close()
    blocked, blocked_md = report_pair(report_client, blocked_id)
    assert blocked["counters"]["incomplete"] == 1
    assert blocked["trials"][0]["evidence_state"] == "unverifiable"
    assert "snapshot unavailable" in blocked_md

    report_client.app.state.auto_dispatch = True
    failed_id, _ = create_done(report_client, "failed-report-model", repeats=1)
    failed_run = report_client.get(f"/api/v1/jobs/{failed_id}/results").json()["trials"][0]["run_id"]
    conn = db.connect(report_db)
    try:
        conn.execute("UPDATE runs SET status='valid' WHERE id=?", (failed_run,))
        conn.execute(
            "UPDATE run_scores SET functional_pass=0, voided=0, final_score=0 WHERE run_id=?",
            (failed_run,),
        )
        conn.commit()
    finally:
        conn.close()
    failed, failed_md = report_pair(report_client, failed_id)
    assert failed["counters"]["failed"] == 1
    assert failed["counters"]["voided"] == 0
    assert failed["trials"][0]["outcome"]["status"] == "valid"
    assert failed["trials"][0]["outcome"]["voided"] is False
    assert "Outcome status: `valid`" in failed_md
    assert "Result: `FAIL`" in failed_md

    voided_id, _ = create_done(report_client, "voided-report-model", repeats=1)
    voided_run = report_client.get(f"/api/v1/jobs/{voided_id}/results").json()["trials"][0]["run_id"]
    conn = db.connect(report_db)
    try:
        conn.execute("UPDATE runs SET status='infra_error' WHERE id=?", (voided_run,))
        conn.execute(
            "UPDATE run_scores SET functional_pass=1, voided=1, final_score=0 WHERE run_id=?",
            (voided_run,),
        )
        conn.commit()
    finally:
        conn.close()
    voided, voided_md = report_pair(report_client, voided_id)
    assert voided["counters"]["failed"] == 0
    assert voided["counters"]["passed"] == 0
    assert voided["counters"]["voided"] == 1
    assert voided["trials"][0]["outcome"]["status"] == "infra_error"
    assert voided["trials"][0]["outcome"]["functional_pass"] is True
    assert voided["trials"][0]["outcome"]["voided"] is True
    assert "Result: `VOIDED (infra_error)`" in voided_md


def test_report_does_not_invent_defaults_for_invalid_persisted_params(report_client, report_db):
    cases = {
        "invalid-report-params": ("not-json", None),
        "empty-backend-params": (
            json.dumps({"model": "persisted-model", "backend": {}, "repeats": 9,
                        "base_seed": 2222, "temperature": 0.2, "request_timeout_s": 11}),
            None,
        ),
        "missing-kind-params": (
            json.dumps({"model": "missing-kind-model", "backend": {"base_url": "http://localhost:9999"}}),
            None,
        ),
        "missing-kind-snapshot": (
            json.dumps({"model": "missing-kind-snapshot-model"}),
            json.dumps({"model": "missing-kind-snapshot-model", "backend": {"base_url": "http://localhost:9999"}}),
        ),
        "credential-url-params": (
            json.dumps({"model": "credential-url-model", "backend": {
                "kind": "openai_compat", "base_url": "https://user:password@example.com/?token=URLSECRET"}}),
            None,
        ),
        "safe-backend-params": (
            json.dumps({
                "model": "safe-backend-model",
                "backend": {
                    "kind": "openai_compat",
                    "base_url": "http://localhost:1234",
                },
                "repeats": 4,
                "base_seed": 4321,
                "temperature": 0.3,
                "request_timeout_s": 17,
            }),
            None,
        ),
        "unknown-secret-field-params": (
            json.dumps({
                "model": "unknown-secret-model",
                "backend": {
                    "kind": "openai_compat",
                    "base_url": "http://localhost:1234",
                    "secret": "FIELDSECRET",
                },
                "repeats": 4,
                "base_seed": 4321,
                "temperature": 0.3,
                "request_timeout_s": 17,
            }),
            None,
        ),
        "credential-params": (
            json.dumps({"model": "credential-model", "backend": {
                "kind": "openai_compat", "base_url": "https://user:password@example.com/?token=TOPSECRET",
                "api_key": "TOPSECRET"}}),
            None,
        ),
        "nonobject-snapshot": (json.dumps({"model": "snapshot-shape-model"}), "[]"),
        "malformed-snapshot": (
            json.dumps({
                "model": "malformed-snapshot-model",
                "repeats": 4,
                "base_seed": 3333,
                "temperature": 0.15,
                "request_timeout_s": 13,
            }),
            '{"model":"malformed-snapshot-model"',
        ),
        "empty-backend-snapshot": (
            json.dumps({"model": "snapshot-backend-model"}),
            json.dumps({"model": "snapshot-backend-model", "backend": {}}),
        ),
        "container-mode-params": (json.dumps({"model": "container-mode-model", "mode": []}), None),
        "nonfinite-params": (
            '{"model":"nonfinite-model","temperature":NaN,"repeats":Infinity,'
            '"base_seed":Infinity,"request_timeout_s":Infinity}',
            '{"model":"nonfinite-model","repeats":Infinity,'
            '"generation":{"base_seed":Infinity,"temperature":Infinity,'
            '"request_timeout_s":Infinity}}',
        ),
        "nonfinite-snapshot": (
            json.dumps({
                "model": "nonfinite-snapshot-model",
                "repeats": 4,
                "base_seed": 2468,
                "temperature": 0.125,
                "request_timeout_s": 23,
            }),
            '{"model":"nonfinite-snapshot-model","repeats":Infinity,'
            '"base_seed":Infinity,"generation":{"base_seed":Infinity,'
            '"temperature":Infinity,"request_timeout_s":Infinity}}',
        ),
    }
    for job_id, (params_json, snapshot_json) in cases.items():
        insert_raw_report_job(report_db, job_id, params_json, snapshot_json)

    invalid, invalid_md = report_pair(report_client, "invalid-report-params")
    assert invalid["model"] is None
    assert invalid["provider"] is None
    assert invalid["backend"] is None
    assert invalid["evaluation_parameters"]["repeats"] is None
    assert invalid["generation"]["base_seed"] is None
    assert invalid["task_snapshots"] == []
    assert any("parameters are unavailable" in item for item in invalid["limitations"])
    assert "mock" not in invalid_md
    assert "unavailable" in invalid_md

    persisted, persisted_md = report_pair(report_client, "empty-backend-params")
    assert persisted["model"] == "persisted-model"
    assert persisted["backend"] is None
    assert persisted["evaluation_parameters"]["repeats"] == 9
    assert persisted["generation"]["base_seed"] == 2222
    assert persisted["generation"]["temperature"] == 0.2
    assert persisted["generation"]["request_timeout_s"] == 11
    assert any("backend provenance" in item for item in persisted["limitations"])
    assert "mock" not in persisted_md

    missing_kind, missing_kind_md = report_pair(report_client, "missing-kind-params")
    assert missing_kind["model"] == "missing-kind-model"
    assert missing_kind["backend"] is None
    assert "mock" not in missing_kind_md
    assert "localhost:9999" not in json.dumps(missing_kind)
    assert "localhost:9999" not in missing_kind_md

    missing_snapshot, missing_snapshot_md = report_pair(report_client, "missing-kind-snapshot")
    assert missing_snapshot["model"] == "missing-kind-snapshot-model"
    assert missing_snapshot["backend"] is None
    assert "localhost:9999" not in json.dumps(missing_snapshot)
    assert "localhost:9999" not in missing_snapshot_md

    safe_backend, safe_backend_md = report_pair(report_client, "safe-backend-params")
    assert safe_backend["model"] == "safe-backend-model"
    assert safe_backend["provider"] == "openai_compat"
    assert safe_backend["backend"] == {
        "kind": "openai_compat",
        "base_url": "http://localhost:1234",
    }
    assert safe_backend["evaluation_parameters"]["repeats"] == 4
    assert safe_backend["evaluation_parameters"]["base_seed"] == 4321
    assert safe_backend["evaluation_parameters"]["temperature"] == 0.3
    assert safe_backend["evaluation_parameters"]["request_timeout_s"] == 17
    assert safe_backend["generation"]["base_seed"] == 4321
    assert safe_backend["generation"]["temperature"] == 0.3
    assert safe_backend["generation"]["request_timeout_s"] == 17
    assert f"- Parameters: `{compact_json(safe_backend['evaluation_parameters'])}`" in safe_backend_md
    assert f"- Generation: `{compact_json(safe_backend['generation'])}`" in safe_backend_md

    credential_url, credential_url_md = report_pair(report_client, "credential-url-params")
    assert credential_url["model"] == "credential-url-model"
    assert credential_url["backend"] is None
    assert "URLSECRET" not in json.dumps(credential_url)
    assert "URLSECRET" not in credential_url_md
    assert "user:password@example.com" not in credential_url_md

    unknown_secret, unknown_secret_md = report_pair(report_client, "unknown-secret-field-params")
    assert unknown_secret["model"] == "unknown-secret-model"
    assert unknown_secret["provider"] is None
    assert unknown_secret["backend"] is None
    assert unknown_secret["evaluation_parameters"]["repeats"] == 4
    assert unknown_secret["evaluation_parameters"]["base_seed"] == 4321
    assert unknown_secret["evaluation_parameters"]["temperature"] == 0.3
    assert unknown_secret["evaluation_parameters"]["request_timeout_s"] == 17
    assert unknown_secret["generation"]["base_seed"] == 4321
    assert unknown_secret["generation"]["temperature"] == 0.3
    assert unknown_secret["generation"]["request_timeout_s"] == 17
    assert "FIELDSECRET" not in json.dumps(unknown_secret)
    assert "FIELDSECRET" not in unknown_secret_md
    assert "http://localhost:1234" not in json.dumps(unknown_secret)
    assert "http://localhost:1234" not in unknown_secret_md
    assert f"- Parameters: `{compact_json(unknown_secret['evaluation_parameters'])}`" in unknown_secret_md
    assert f"- Generation: `{compact_json(unknown_secret['generation'])}`" in unknown_secret_md

    credential, credential_md = report_pair(report_client, "credential-params")
    assert credential["model"] == "credential-model"
    assert credential["backend"] is None
    assert "TOPSECRET" not in json.dumps(credential)
    assert "TOPSECRET" not in credential_md

    nonobject, nonobject_md = report_pair(report_client, "nonobject-snapshot")
    assert nonobject["model"] == "snapshot-shape-model"
    assert nonobject["task_snapshots"] == []
    assert any("task snapshot" in item for item in nonobject["limitations"])
    assert "unavailable" in nonobject_md

    malformed, malformed_md = report_pair(report_client, "malformed-snapshot")
    assert malformed["status"] == "failed"
    assert malformed["mode"] == "legacy"
    assert malformed["model"] == "malformed-snapshot-model"
    assert malformed["task_snapshots"] == []
    assert malformed["evaluation_parameters"]["repeats"] == 4
    assert malformed["evaluation_parameters"]["base_seed"] == 3333
    assert malformed["evaluation_parameters"]["temperature"] == 0.15
    assert malformed["evaluation_parameters"]["request_timeout_s"] == 13
    assert malformed["generation"] == {
        "base_seed": 3333,
        "temperature": 0.15,
        "request_timeout_s": 13,
        "seed_provenance": None,
        "timeout_provenance": None,
    }
    assert any("task snapshot is unavailable" in item for item in malformed["limitations"])
    assert f"- Parameters: `{compact_json(malformed['evaluation_parameters'])}`" in malformed_md
    assert f"- Generation: `{compact_json(malformed['generation'])}`" in malformed_md
    assert "task snapshot is unavailable or unverifiable" in malformed_md

    empty_snapshot, empty_snapshot_md = report_pair(report_client, "empty-backend-snapshot")
    assert empty_snapshot["model"] == "snapshot-backend-model"
    assert empty_snapshot["backend"] is None
    assert "mock" not in empty_snapshot_md

    container_mode, _ = report_pair(report_client, "container-mode-params")
    assert container_mode["model"] == "container-mode-model"
    assert container_mode["mode"] == "legacy"

    nonfinite, nonfinite_md = report_pair(report_client, "nonfinite-params")
    assert nonfinite["model"] == "nonfinite-model"
    assert nonfinite["generation"]["base_seed"] is None
    assert nonfinite["generation"]["temperature"] is None
    assert nonfinite["evaluation_parameters"]["repeats"] is None
    assert nonfinite["evaluation_parameters"]["base_seed"] is None
    assert nonfinite["evaluation_parameters"]["temperature"] is None
    assert nonfinite["generation"]["request_timeout_s"] is None
    assert nonfinite["evaluation_parameters"]["request_timeout_s"] is None
    json.dumps(nonfinite, allow_nan=False)
    assert "NaN" not in json.dumps(nonfinite)
    assert "Infinity" not in json.dumps(nonfinite)
    assert "NaN" not in nonfinite_md
    assert "Infinity" not in nonfinite_md

    nonfinite_snapshot, nonfinite_snapshot_md = report_pair(report_client, "nonfinite-snapshot")
    assert nonfinite_snapshot["model"] == "nonfinite-snapshot-model"
    assert nonfinite_snapshot["evaluation_parameters"] == {
        "model": "nonfinite-snapshot-model",
        "name": None,
        "repeats": 4,
        "base_seed": 2468,
        "temperature": 0.125,
        "request_timeout_s": 23,
        "backend": None,
        "source_evaluation_id": None,
    }
    assert nonfinite_snapshot["generation"] == {
        "base_seed": 2468,
        "temperature": 0.125,
        "request_timeout_s": 23,
        "seed_provenance": None,
        "timeout_provenance": None,
    }
    json.dumps(nonfinite_snapshot, allow_nan=False)
    assert f"- Parameters: `{compact_json(nonfinite_snapshot['evaluation_parameters'])}`" in nonfinite_snapshot_md
    assert f"- Generation: `{compact_json(nonfinite_snapshot['generation'])}`" in nonfinite_snapshot_md
    assert "Infinity" not in json.dumps(nonfinite_snapshot)
    assert "Infinity" not in nonfinite_snapshot_md


def test_report_uses_one_coherent_read_snapshot(report_client, report_db, monkeypatch):
    job_id, _ = create_done(report_client, "coherent-report-model", repeats=1)
    before = report_client.get(f"/api/v1/jobs/{job_id}/results").json()
    run_id = before["trials"][0]["run_id"]
    original_trial_rows = jobs.trial_rows
    interleaved = False

    def interleaving_trial_rows(conn, evaluation_id):
        nonlocal interleaved
        rows = original_trial_rows(conn, evaluation_id)
        if evaluation_id == job_id and not interleaved:
            interleaved = True
            writer = db.connect(report_db)
            try:
                writer.execute(
                    "UPDATE evaluation_trials SET trial_state='pending', "
                    "evidence_state='missing', run_id=NULL WHERE evaluation_id=?",
                    (job_id,),
                )
                writer.commit()
            finally:
                writer.close()
        return rows

    monkeypatch.setattr(jobs, "trial_rows", interleaving_trial_rows)
    conn = db.connect_readonly(report_db)
    try:
        report = build_evaluation_report(conn, job_id)
    finally:
        conn.close()
    assert interleaved is True
    trial = report["trials"][0]
    assert trial["trial_state"] == "completed"
    assert trial["run_id"] == run_id
    assert trial["outcome"]["functional_pass"] is True
    assert trial["artifact_state"] == "complete"
    assert trial["comparability"] == "comparable"


def test_report_routes_use_readonly_connections(report_client, report_db, monkeypatch):
    job_id, _ = create_done(report_client, "readonly-report-model", repeats=1)
    real_connect_readonly = db.connect_readonly
    calls = []

    def observed_readonly(path):
        calls.append(path)
        return real_connect_readonly(path)

    monkeypatch.setattr(db, "connect_readonly", observed_readonly)
    report_pair(report_client, job_id)
    assert len(calls) == 2
    assert all(str(path) == str(report_db) for path in calls)


def test_report_unknown_evaluation_is_404(report_client):
    assert report_client.get("/api/v1/jobs/not-an-evaluation/report.json").status_code == 404
    assert report_client.get("/api/v1/jobs/not-an-evaluation/report.md").status_code == 404
