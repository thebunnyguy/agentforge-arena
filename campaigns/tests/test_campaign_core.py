"""Independent adversarial tests for the campaign CORE: manifest, ledger, cohort
(the definition of a valid campaign cell), completeness validation and status.

Every campaign database here is a fresh file (``launcher.init_db``) or a
sqlite-backup copy of one; evaluations are REAL ATLAS lifecycle evaluations
(``jobs.create_job`` -> ``worker.claim_and_run``) driven by a reference-overlay
agent factory that DECLARES the ``ollama`` backend, so its runs are
provenance-real exactly as a genuine local-model campaign's would be. No model,
no Ollama and no network are contacted. The historical evidence DB is only read
(``immutable=1``); the package conftest proves it stays byte-identical.

Tests that assert behaviour the product does not (yet) have are marked
``xfail(strict=True, reason="PRODUCT BUG: ...")``: they fail until the product is
fixed, and then XPASS, which fails the suite so the marker is removed.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import sqlite3
from contextlib import closing
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from afa_campaign import cli, cohort, launcher, paths
from afa_campaign import status as status_mod
from afa_campaign import validate as validate_mod
from afa_campaign.ledger import (
    FAILED, NEEDS_ATTENTION, REJECTED, SUBMITTED, SUBMITTING, SUCCEEDED, SUPERSEDED,
    Ledger, LedgerError,
)
from afa_campaign.manifest import (
    CAMPAIGN_ID, ROSTER, Cell, Manifest, ManifestError, canonical_sha256, derive_subset,
    dump, expected_counts, file_sha256, validate,
)

from afa_api import db as app_db
from afa_api import jobs, worker
from afa_api.schemas import JobCreate

HISTORICAL_SHA256 = "42b6dad85ee662d6d5d7f75ffbda5a3b95d50837837f81c875730a8987838ced"

GOLDEN_MODELS = ["qwen2.5-coder:3b", "gemma2:2b"]
GOLDEN_TASKS = ["two-sum-indices", "grid-paths"]  # fast tasks; grid-paths was ORACLE-bumped
GOLDEN_REPS = 2


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #


def declared_factory(backend_kind: str | None = "ollama", seeds: list | None = None):
    """Reference-overlay agent factory that declares the backend it stands in
    for (what production factories do). ``backend_kind=None`` declares nothing
    (an unattested test double); ``seeds`` records every per-trial seed."""

    def factory(model, task, params):
        agent = worker.mock_agent_factory(model, task, params)
        if seeds is not None:
            name = params.name
            agent.set_run_seed = lambda seed: seeds.append((name, seed))  # type: ignore[attr-defined]
        return agent

    if backend_kind is not None:
        factory.backend_kind = backend_kind  # type: ignore[attr-defined]
    return factory


def failing_factory(model, task, params):
    raise RuntimeError("simulated backend failure")


failing_factory.backend_kind = "ollama"  # type: ignore[attr-defined]


def run_evaluation(conn: sqlite3.Connection, body: dict, factory) -> str:
    """Create one evaluation through the lifecycle and execute it to terminal."""
    job = jobs.create_job(conn, JobCreate(**body))
    ran = worker.claim_and_run(conn, agent_factory=factory)
    assert ran == job.id
    return job.id


def backup_copy(src: Path, dst: Path) -> Path:
    """Coherent copy of a (WAL-mode) SQLite database."""
    source = sqlite3.connect(f"{Path(src).as_uri()}?mode=ro", uri=True)
    dest = sqlite3.connect(str(dst))
    try:
        source.backup(dest)
    finally:
        dest.close()
        source.close()
    return dst


def tamper(src: Path, dst: Path, *statements: tuple[str, tuple]) -> Path:
    backup_copy(src, dst)
    conn = sqlite3.connect(str(dst))
    try:
        for sql, args in statements:
            conn.execute(sql, args)
        conn.commit()
    finally:
        conn.close()
    return dst


def check(db_path: Path, manifest: Manifest, cell: Cell, evaluation_id: str | None) -> cohort.CellCheck:
    with closing(cohort.open_readonly(db_path)) as conn:
        return cohort.check_cell_evaluation(conn, manifest, cell, evaluation_id)


def assert_only(result: cohort.CellCheck, *fragments: str) -> None:
    """The check failed, every expected fragment appears in some problem, and
    every problem is explained by one of the fragments (the tampering is
    detected by the RIGHT check, not by an unrelated side effect)."""
    assert not result.ok, result.as_dict()
    for fragment in fragments:
        assert any(fragment in p for p in result.problems), (fragment, result.problems)
    for problem in result.problems:
        assert any(f in problem for f in fragments), (problem, fragments)


def historical_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(f"{paths.EVIDENCE_DB.as_uri()}?mode=ro&immutable=1", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def campaign_clone(golden: "Golden", tmp_path: Path, name: str = "clone") -> Manifest:
    """The golden campaign (same campaign id / name prefix / pins) relocated to a
    private database copy and runtime directory."""
    data = copy.deepcopy(golden.data)
    db = tmp_path / f"{name}.sqlite"
    runtime = tmp_path / f"{name}-rt"
    data["runtime"] = {
        **data["runtime"],
        "campaign_db": str(db),
        "runtime_dir": str(runtime),
        "ledger": str(runtime / "ledger.json"),
        "outputs": str(runtime / "outputs"),
    }
    backup_copy(golden.db, db)
    return Manifest(data)


def fake_digest(model: str) -> str:
    """A stable, model-specific fake Ollama digest."""
    return "sha256:" + hashlib.sha256(model.encode()).hexdigest()


OLLAMA_VERSION = "0.0-test"  # the server version every launch_record's inventory reports


def launch_record(models, digests: dict[str, str] | None = None, **extra) -> dict:
    """A launch record as the launcher writes it: the external Ollama inventory
    whose digests AND server version (round 4) become the campaign's
    model-identity reference, and whether the launch ran a passing runtime-code
    check and warmed the model (round 4: a launch without them is only a
    WARNING; the cells it touched carry the verdict themselves)."""
    digests = digests if digests is not None else {m: fake_digest(m) for m in models}
    return {
        "started_at": "2026-09-26T00:00:00Z", "phase": "A", "outcome": "phase-complete",
        "inventory": {"captured_at": "2026-09-26T00:00:00Z", "source": "fake inventory (test)",
                      "ollama_version": OLLAMA_VERSION,
                      "models": {m: {"present": True, "name": m, "digest": digests[m]} for m in digests}},
        "check_code": True, "warmup": True,
        **extra,
    }


def write_ledger(manifest: Manifest, rows: list[tuple[Cell | str, str | None, str]], *,
                 launches: list[dict] | None = None, identity: bool = True) -> Ledger:
    """A ledger as the launcher would leave it: a first launch recording the
    Ollama inventory (the identity reference) and, on every entry, what round 4's
    launcher records before the POST and at finalisation: the runtime-code check
    at submission and at finalisation, the warm-up at submission, and
    (``identity=True``) the model digest and Ollama server version at submission
    and at finalisation (``identity=False`` omits the digests and versions)."""
    ledger = Ledger.new(manifest.ledger_path(), campaign_id=manifest.campaign_id,
                        manifest_sha256=manifest.sha256, manifest_path="")
    ledger.data["launches"] = launches if launches is not None else [launch_record(manifest.models)]
    for cell, evaluation_id, state in rows:
        if isinstance(cell, Cell):
            key, model, task_id, phase = cell.key, cell.model, cell.task_id, cell.phase
            name = manifest.evaluation_name(cell)
        else:
            key, (model, task_id), phase = cell, cell.split("|", 1), "A"
            name = f"{manifest.data['evaluation_name_prefix']}:A:{cell}"
        entry = ledger.new_entry(key=key, model=model, task_id=task_id, phase=phase,
                                 evaluation_name=name, positions=list(range(manifest.repetitions)))
        ledger.update(entry, evaluation_id=evaluation_id, state=state,
                      code_check_at_submit=True, code_check_at_finalize=True, warmed_up_at_submit=True,
                      submitted_by_launch="2026-09-26T00:00:00Z", finalized_by_launch="2026-09-26T00:00:00Z")
        if identity:
            ledger.update(entry, model_digest_at_submit=fake_digest(model),
                          model_digest_at_finalize=fake_digest(model),
                          ollama_version_at_submit=OLLAMA_VERSION, ollama_version_at_finalize=OLLAMA_VERSION)
    ledger.save()
    return ledger


# --------------------------------------------------------------------------- #
# fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="module")
def base() -> Manifest:
    return Manifest.load()


@dataclass
class Golden:
    data: dict
    manifest: Manifest
    db: Path
    evals: dict[str, str]  # cell key -> evaluation id
    foreign: str  # a real, NON-campaign evaluation for the last cell's model/task
    seeds: list = field(default_factory=list)

    def cell(self, i: int) -> Cell:
        return self.manifest.cells()[i]


@pytest.fixture(scope="module")
def golden(base, tmp_path_factory) -> Golden:
    """2 models x 2 tasks x 2 repetitions, every cell a real lifecycle
    evaluation, plus one foreign (non-campaign-named) real evaluation."""
    tmp = tmp_path_factory.mktemp("golden")
    data = derive_subset(
        base.data, campaign_id="t-golden", models=GOLDEN_MODELS, task_ids=GOLDEN_TASKS,
        repetitions=GOLDEN_REPS, campaign_db=str(tmp / "golden.sqlite"),
        runtime_dir=str(tmp / "rt"), purpose="test",
    )
    manifest = Manifest(data)
    launcher.init_db(manifest)
    seeds: list = []
    factory = declared_factory("ollama", seeds)
    evals: dict[str, str] = {}
    with closing(app_db.connect(manifest.db_path())) as conn:
        for cell in manifest.cells():
            evals[cell.key] = run_evaluation(conn, manifest.job_body(cell), factory)
        last = manifest.cells()[-1]
        foreign = run_evaluation(conn, {**manifest.job_body(last), "name": "ui-experiment"}, factory)
        for evaluation_id in [*evals.values(), foreign]:
            assert jobs.get_job(conn, evaluation_id).status == "succeeded"
    return Golden(data, manifest, manifest.db_path(), evals, foreign, seeds)


@dataclass
class Variants:
    manifest: Manifest
    db: Path
    cell: Cell
    evals: dict[str, str]


@pytest.fixture(scope="module")
def variants(base, tmp_path_factory) -> Variants:
    """One cell (1 repetition) evaluated validly and in several WRONG ways, each a
    real lifecycle evaluation carrying the campaign's own evaluation name."""
    tmp = tmp_path_factory.mktemp("variants")
    data = derive_subset(
        base.data, campaign_id="t-variants", models=["qwen2.5-coder:3b"],
        task_ids=["two-sum-indices"], repetitions=1, campaign_db=str(tmp / "v.sqlite"),
        runtime_dir=str(tmp / "rt"), purpose="test",
    )
    manifest = Manifest(data)
    launcher.init_db(manifest)
    cell = manifest.cells()[0]
    body = manifest.job_body(cell)
    good = declared_factory("ollama")
    evals: dict[str, str] = {}
    with closing(app_db.connect(manifest.db_path())) as conn:
        evals["valid"] = run_evaluation(conn, body, good)
        evals["undeclared"] = run_evaluation(conn, body, declared_factory(None))
        evals["mock_declared"] = run_evaluation(conn, body, worker.mock_agent_factory)
        evals["reuse"] = run_evaluation(
            conn, {**body, "mode": "reuse", "source_evaluation_id": evals["valid"]}, good)
        evals["temperature"] = run_evaluation(conn, {**body, "temperature": 0.5}, good)
        evals["base_seed"] = run_evaluation(conn, {**body, "base_seed": 7}, good)
        evals["repeats"] = run_evaluation(conn, {**body, "repeats": 2}, good)
        evals["name"] = run_evaluation(
            conn, {**body, "name": manifest.evaluation_name(Cell(cell.model, cell.task_id, "B"))}, good)
        evals["timeout"] = run_evaluation(conn, {**body, "request_timeout_s": 60}, good)
        evals["backend_url"] = run_evaluation(
            conn, {**body, "backend": {"kind": "ollama", "base_url": "http://10.0.0.9:11434"}}, good)
        for key, evaluation_id in evals.items():
            assert jobs.get_job(conn, evaluation_id).status == "succeeded", key
    return Variants(manifest, manifest.db_path(), cell, evals)


# =========================================================================== #
# Manifest
# =========================================================================== #


def test_committed_manifest_loads_and_has_the_planned_shape(base):
    data = base.data
    validate(data)
    assert base.campaign_id == CAMPAIGN_ID == "phase0-post-integrity-v1"
    assert base.models == list(ROSTER) and len(ROSTER) == len(set(ROSTER)) == 6
    task_manifest = json.loads(paths.TASK_MANIFEST.read_text())
    assert base.task_ids == [t["id"] for t in task_manifest] and len(base.task_ids) == 24
    assert base.repetitions == 5
    cells = base.cells()
    assert len(cells) == 144 == len({c.key for c in cells})
    assert {(c.model, c.task_id) for c in cells} == {(m, t) for m in base.models for t in base.task_ids}
    phase_a, phase_b = base.cells("A"), base.cells("B")
    assert (len(phase_a), len(phase_b)) == (51, 93)
    assert base.cells("all") == cells
    assert data["expected"] == expected_counts(data) == {
        "models": 6, "tasks": 24, "cells": 144, "runs_per_cell": 5, "runs_per_model": 120,
        "total_runs": 720, "phase_A_cells": 51, "phase_A_runs": 255,
        "phase_B_cells": 93, "phase_B_runs": 465,
    }
    assert base.backend == {"kind": "ollama", "base_url": "http://127.0.0.1:11434"}
    assert data["mode"] == "fresh" and data["evidence_scope"] == "real"
    assert base.generation["temperature"] == 0.8 and base.generation["base_seed"] == 42
    assert base.generation["request_timeout_s"] == 180
    assert data["evaluation_name_prefix"] == f"campaign:{CAMPAIGN_ID}"
    assert data["runtime"]["db_strategy"] == "clean"
    assert Path(data["runtime"]["campaign_db"]).name != "runs.sqlite"
    assert base.db_path() != paths.EVIDENCE_DB.resolve()
    assert data["historical_evidence"]["sha256"] == HISTORICAL_SHA256 == file_sha256(paths.EVIDENCE_DB)
    assert data["remediation_manifest"]["sha256"] == file_sha256(paths.REMEDIATION_MANIFEST)
    # contract change 9 (corrected in round 3): what the repository DOCUMENTS about
    # how the historical runs were generated travels with the frozen plan
    # (disclosed in every comparison); unknowns stay explicitly unknown
    from afa_campaign.analysis import HISTORICAL_STACK
    from afa_campaign.manifest import HISTORICAL_GENERATION
    assert data["historical_evidence"]["documented_generation"] == HISTORICAL_GENERATION
    documented = HISTORICAL_GENERATION
    assert set(documented) == {"sources", "p0_completion_runs", "qwen3.5:9b"} and "qwen3.5:9b" in ROSTER
    p0, q35 = documented["p0_completion_runs"], documented["qwen3.5:9b"]
    assert (p0["temperature"], p0["base_seed"], p0["ollama_version"], p0["request_timeout_s"]) == (
        0.8, 42, "0.17.4", None)
    assert p0["digest_prefixes"] == {"qwen2.5-coder:7b": "dae161e27b0e", "llama3.2:latest": "a80c4f17acd5"}
    assert "not enumerated" in p0["models"]  # the README never says WHICH models' runs these were
    assert (q35["temperature"], q35["base_seed"], q35["request_timeout_s"], q35["ollama_version"],
            q35["digest"]) == (0.6, 42, 180, None, None)
    assert "eb54c065c0b84d099a82570f4aeee83c" in q35["evaluation_path"] and "1101-1220" in q35["evaluation_path"]
    # fact-check against the documents themselves (not against the tooling)
    readme = " ".join((paths.REPO / "README.md").read_text().split())
    assert ("the P0 completion runs used Ollama 0.17.4, temperature 0.8, base seed 42, "
            "`qwen2.5-coder:7b` digest `dae161e27b0e`, and `llama3.2:latest` digest `a80c4f17acd5`") in readme
    assert "`qwen3.5:9b` evaluation used the local Ollama backend, temperature 0.6, base seed 42" in readme
    assert "The evaluated model digest was not recorded." in readme
    report = (paths.REPO / "reports" / "qwen3.5-9b-evaluation-2026-09-17.md").read_text()
    assert "`eb54c065c0b84d099a82570f4aeee83c`" in report and "run IDs 1101\u20131220" in report
    assert "Base seed: `42`; temperature: `0.6`; model request timeout: `180` seconds" in report
    assert all(source.split(",")[0] in {"README.md", "reports/qwen3.5-9b-evaluation-2026-09-17.md"}
               for source in documented["sources"])
    # the analysis discloses the same facts
    stack_p0, stack_q35 = HISTORICAL_STACK["p0_completion_runs"], HISTORICAL_STACK["per_model_exceptions"]["qwen3.5:9b"]
    assert (stack_p0["temperature"], stack_p0["base_seed"], stack_p0["ollama_version"],
            stack_p0["request_timeout_s"]) == (0.8, 42, "0.17.4", None)
    assert stack_p0["recorded_digests"] == p0["digest_prefixes"]
    assert (stack_q35["temperature"], stack_q35["base_seed"], stack_q35["request_timeout_s"],
            stack_q35["ollama_version"], stack_q35["digest"]) == (0.6, 42, 180, None, None)
    assert "eb54c065c0b84d099a82570f4aeee83c" in stack_q35["evaluation_path"]
    # the plan is frozen by content: the canonical hash is stable across loads
    assert Manifest.load().sha256 == base.sha256 == canonical_sha256(data)


def test_phase_a_is_exactly_the_independently_recomputed_prior_pass_cells(base):
    remediation = json.loads(paths.REMEDIATION_MANIFEST.read_text())
    bumped = {t["task_id"]: t for t in remediation["tasks"]}
    assert len(bumped) == 18
    from_remediation = {
        (pm["model"], task_id)
        for task_id, t in bumped.items()
        for pm in t["known_affected_runs"]["per_model"]
        if pm["passed"] > 0
    }
    with closing(historical_conn()) as conn:
        rows = conn.execute(
            "SELECT r.agent, r.task_id, r.task_version, COUNT(*) AS n, "
            "SUM(r.status != 'infra_failure' AND COALESCE(s.voided, 0) = 0) AS valid, "
            "SUM(r.status != 'infra_failure' AND COALESCE(s.voided, 0) = 0 "
            "    AND s.functional_pass = 1) AS passes "
            "FROM runs r LEFT JOIN run_scores s ON s.run_id = r.id AND s.formula_version = 'v0.1' "
            "GROUP BY r.agent, r.task_id, r.task_version"
        ).fetchall()
    hist = {(r["agent"], r["task_id"]): r for r in rows}
    assert len(rows) == len(hist) == 144  # exactly one historical version per (model, task)
    assert sum(r["n"] for r in rows) == 720
    from_db = {
        key for key, r in hist.items()
        if key[1] in bumped and r["task_version"] == bumped[key[1]]["old_version"] and r["passes"] > 0
    }
    assert from_db == from_remediation
    assert len(from_db) == 51
    phase_a = {(c.model, c.task_id) for c in base.cells("A")}
    assert phase_a == from_db
    # every cell's recorded historical facts match the raw evidence
    for cell in base.data["cells"]:
        r = hist[(cell["model"], cell["task_id"])]
        assert (cell["historical_runs"], cell["historical_valid"], cell["historical_passes"]) == (
            r["n"], r["valid"], r["passes"]), cell
        assert cell["historical_version"] == r["task_version"]
        assert cell["prior_pass"] is ((cell["model"], cell["task_id"]) in from_db)
        assert cell["phase"] == ("A" if cell["prior_pass"] else "B")
    # remediation says the same numbers as the DB for every (model, bumped task)
    for task_id, t in bumped.items():
        for pm in t["known_affected_runs"]["per_model"]:
            r = hist[(pm["model"], task_id)]
            assert (r["n"], r["passes"]) == (pm["n"], pm["passed"])


def test_every_task_pin_equals_the_runtime_snapshot_now(base):
    remediation = {t["task_id"]: t for t in json.loads(paths.REMEDIATION_MANIFEST.read_text())["tasks"]}
    for task in base.data["tasks"]:
        snap = jobs.task_snapshot(task["task_id"])
        assert snap["task_version"] == task["task_version"], task["task_id"]
        assert snap["task_digest"] == task["task_digest"], task["task_id"]
        spec = json.loads((paths.TASKS_DIR / task["task_id"] / "task.json").read_text())
        assert spec["version"] == task["task_version"]
        if task["task_id"] in remediation:
            assert task["task_version"] == remediation[task["task_id"]]["new_version"]
            assert task["historical_version"] == remediation[task["task_id"]]["old_version"]
            assert task["version_changed_since_historical"] is True
        else:
            assert task["version_changed_since_historical"] is False
    assert launcher.check_task_pins(base) == []


def test_job_body_matches_the_manifest_for_every_cell(base):
    names = set()
    snapshotted_tasks = set()
    for cell in base.cells():
        body = base.job_body(cell)
        assert body == {
            "model": cell.model,
            "backend": {"kind": "ollama", "base_url": "http://127.0.0.1:11434"},
            "tasks": [cell.task_id],
            "repeats": 5,
            "base_seed": 42,
            "temperature": 0.8,
            "request_timeout_s": 180,
            "mode": "fresh",
            "name": f"campaign:{CAMPAIGN_ID}:{cell.phase}:{cell.model}|{cell.task_id}",
        }
        assert body["name"] == base.evaluation_name(cell)
        names.add(body["name"])
        params = JobCreate(**body)  # the app accepts it as-is
        if cell.task_id not in snapshotted_tasks:
            snapshotted_tasks.add(cell.task_id)
            snap = jobs.build_snapshot(params)
            pin = base.task_by_id[cell.task_id]
            assert snap["tasks"] == [{"task_id": cell.task_id, "task_version": pin["task_version"],
                                      "task_digest": pin["task_digest"]}]
            assert snap["backend"] == {"kind": "ollama", "base_url": "http://127.0.0.1:11434"}
            assert snap["repeats"] == 5
    assert len(names) == 144
    assert snapshotted_tasks == set(base.task_ids)


def _mutated(data: dict, mutate) -> dict:
    out = copy.deepcopy(data)
    mutate(out)
    return out


@pytest.mark.parametrize(
    "label, mutate, match",
    [
        ("mock backend", lambda d: d["backend"].update(kind="mock"), "backend.kind"),
        ("unknown backend", lambda d: d["backend"].update(kind="hosted"), "backend.kind"),
        ("non-http backend url", lambda d: d["backend"].update(base_url="ftp://x"), "base_url"),
        ("reuse mode", lambda d: d.update(mode="reuse"), "mode must be 'fresh'"),
        ("mode missing", lambda d: d.pop("mode"), "mode must be 'fresh'"),
        ("benchmark scope", lambda d: d.update(evidence_scope="benchmark"), "evidence_scope"),
        ("all scope", lambda d: d.update(evidence_scope="all"), "evidence_scope"),
        ("duplicate cell", lambda d: d["cells"].append(dict(d["cells"][0])), "duplicate cells"),
        ("missing cell", lambda d: d["cells"].pop(), "cells must cover exactly"),
        ("cell for a foreign model",
         lambda d: d["cells"].__setitem__(0, {**d["cells"][0], "model": "llama3:70b"}),
         "cells must cover exactly"),
        ("evidence db as campaign db",
         lambda d: d["runtime"].update(campaign_db="reports/runs.sqlite"), "evidence DB"),
        ("any runs.sqlite as campaign db",
         lambda d: d["runtime"].update(campaign_db="/elsewhere/x/runs.sqlite"), "evidence DB"),
        ("tampered total", lambda d: d["expected"].update(total_runs=719), "expected counts"),
        ("tampered phase A count", lambda d: d["expected"].update(phase_A_cells=52), "expected counts"),
        ("cell moved between phases without recount",
         lambda d: d["cells"].__setitem__(0, {**d["cells"][0], "phase": "B"}), "expected counts"),
        ("bad phase", lambda d: d["cells"].__setitem__(0, {**d["cells"][0], "phase": "C"}), "phase must be"),
        ("bool repetitions", lambda d: d.update(repetitions=True), "repetitions"),
        ("zero repetitions", lambda d: d.update(repetitions=0), "repetitions"),
        ("string temperature", lambda d: d["generation"].update(temperature="0.8"), "temperature"),
        ("float seed", lambda d: d["generation"].update(base_seed=42.0), "base_seed"),
        ("digest missing", lambda d: d["tasks"][0].update(task_digest="md5:x"), "task_digest"),
        ("duplicate model", lambda d: d["models"].append(d["models"][0]), "models must be unique"),
        ("schema bump", lambda d: d.update(schema_version=2), "schema_version"),
    ],
)
def test_validate_rejects(base, label, mutate, match):
    with pytest.raises(ManifestError, match=match):
        validate(_mutated(base.data, mutate))
    with pytest.raises(ManifestError):
        Manifest(_mutated(base.data, mutate))


def test_validate_rejects_a_manifest_without_an_evaluation_name_prefix(base):
    # Was a PRODUCT BUG (fixed in e2c86dc): validate() never checked
    # evaluation_name_prefix, so a manifest without it validated and every
    # consumer then crashed with a bare KeyError.
    broken = _mutated(base.data, lambda d: d.pop("evaluation_name_prefix"))
    with pytest.raises(ManifestError):
        Manifest(broken)


def test_validate_rejects_a_name_prefix_that_is_not_the_campaigns_own(base):
    # Was a PRODUCT BUG (fixed in e2c86dc; contract: the prefix must be exactly
    # 'campaign:<campaign_id>'). The evaluation name prefix is how a campaign
    # recognises (and ADOPTS, after a crash) its own evaluations; a manifest
    # carrying ANOTHER campaign's prefix (or a bare / extended one) could make a
    # dry run create/adopt evaluations under the production campaign's names.
    own = base.data["evaluation_name_prefix"]
    for prefix in ("campaign:some-other-campaign", "campaign", "", own + ":", own + "-2",
                   own.upper(), " " + own, "campaign:" + base.campaign_id + "/x"):
        broken = _mutated(base.data, lambda d: d.update(evaluation_name_prefix=prefix))
        with pytest.raises(ManifestError):
            validate(broken)


def test_derive_subset_keeps_every_pin(base, tmp_path):
    derived = derive_subset(
        base.data, campaign_id="t-derive", models=["gemma2:2b", "qwen2.5-coder:7b"],
        task_ids=["toposort", "fix-list-dedup", "escape-html"], repetitions=3,
        campaign_db=str(tmp_path / "d.sqlite"), runtime_dir=str(tmp_path / "rt"), purpose="test",
    )
    validate(derived)
    by_id = base.task_by_id
    # base order is kept, never the caller's order
    assert derived["models"] == ["qwen2.5-coder:7b", "gemma2:2b"]
    assert [t["task_id"] for t in derived["tasks"]] == [
        t for t in base.task_ids if t in {"toposort", "fix-list-dedup", "escape-html"}]
    for task in derived["tasks"]:
        assert task == by_id[task["task_id"]]  # version, digest, domains... unchanged
    for key in ("backend", "generation", "mode", "evidence_scope", "code", "historical_evidence",
                "remediation_manifest", "schema_version"):
        assert derived[key] == base.data[key], key
    assert derived["campaign_id"] == "t-derive"
    assert derived["evaluation_name_prefix"] == "campaign:t-derive"
    assert derived["derived_from"] == {"campaign_id": CAMPAIGN_ID, "sha256": base.sha256}
    assert derived["repetitions"] == 3
    assert len(derived["cells"]) == 6 and all(c["phase"] == "A" for c in derived["cells"])
    for cell in derived["cells"]:
        original = base.cell_meta(f"{cell['model']}|{cell['task_id']}")
        assert {**original, "phase": "A"} == cell
    assert derived["expected"]["total_runs"] == 18 and derived["expected"]["phase_B_cells"] == 0
    assert derived["runtime"]["campaign_db"] == str(tmp_path / "d.sqlite")
    assert derived["runtime"]["ledger"] == f"{tmp_path / 'rt'}/ledger.json"
    assert derived["runtime"]["db_strategy"] == "clean"
    # the base manifest object is untouched
    assert Manifest.load().sha256 == base.sha256
    m = Manifest(derived)
    body = m.job_body(m.cells()[0])
    assert body["name"].startswith("campaign:t-derive:A:")
    assert (body["repeats"], body["base_seed"], body["temperature"]) == (3, 42, 0.8)
    for bad in ({"models": ["mistral:7b"]}, {"task_ids": ["no-such-task"]}):
        kwargs = dict(campaign_id="x", models=["gemma2:2b"], task_ids=["toposort"], repetitions=1,
                      campaign_db=str(tmp_path / "x.sqlite"), runtime_dir=str(tmp_path / "x"),
                      purpose="t")
        kwargs.update(bad)
        with pytest.raises(ManifestError):
            derive_subset(base.data, **kwargs)
    with pytest.raises(ManifestError, match="evidence DB"):
        derive_subset(base.data, campaign_id="x", models=["gemma2:2b"], task_ids=["toposort"],
                      repetitions=1, campaign_db=str(tmp_path / "runs.sqlite"),
                      runtime_dir=str(tmp_path / "x"), purpose="t")


def test_manifest_load_errors_are_manifest_errors(tmp_path):
    with pytest.raises(ManifestError):
        Manifest.load(tmp_path / "absent.json")
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    with pytest.raises(ManifestError):
        Manifest.load(bad)


def test_init_db_refuses_the_evidence_db_and_existing_files(base, tmp_path, monkeypatch):
    # campaign_db named runs.sqlite never validates; a symlink to the evidence DB
    # under an innocent name passes validate() and must be refused by init_db.
    # The guard is exercised against a SCRATCH copy registered as the evidence
    # DB, so a regression could only ever write the copy, never reports/.
    stand_in = backup_copy(paths.EVIDENCE_DB, tmp_path / "evidence-stand-in.sqlite")
    monkeypatch.setattr(app_db, "EVIDENCE_DB_PATH", stand_in)
    before = file_sha256(stand_in)
    link = tmp_path / "innocent.sqlite"
    link.symlink_to(stand_in)
    via_link = derive_subset(base.data, campaign_id="t-link", models=["gemma2:2b"],
                             task_ids=["toposort"], repetitions=1, campaign_db=str(link),
                             runtime_dir=str(tmp_path / "rt"), purpose="t")
    with pytest.raises((ValueError, launcher.CampaignStop)):
        launcher.init_db(Manifest(via_link))
    assert file_sha256(stand_in) == before
    monkeypatch.undo()
    fresh = derive_subset(base.data, campaign_id="t-init", models=["gemma2:2b"],
                          task_ids=["toposort"], repetitions=1, campaign_db=str(tmp_path / "n.sqlite"),
                          runtime_dir=str(tmp_path / "rt2"), purpose="t")
    target = launcher.init_db(Manifest(fresh))
    with closing(cohort.open_readonly(target)) as conn:
        assert conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 0
        assert conn.execute("SELECT COUNT(*) FROM evaluation_jobs").fetchone()[0] == 0
        assert cohort.jobless_run_count(conn) == 0
    with pytest.raises(launcher.CampaignStop, match="already exists"):
        launcher.init_db(Manifest(fresh))


# =========================================================================== #
# Ledger
# =========================================================================== #


def _ledger(tmp_path: Path, **kw) -> Ledger:
    return Ledger.new(tmp_path / "rt" / "ledger.json", campaign_id=kw.get("campaign_id", "c1"),
                      manifest_sha256=kw.get("sha", "sha256:aaa"), manifest_path="m.json")


def _entry(ledger: Ledger, key: str = "m|t", state: str | None = None, evaluation_id: str | None = None):
    model, task = key.split("|")
    entry = ledger.new_entry(key=key, model=model, task_id=task, phase="A",
                             evaluation_name=f"campaign:c1:A:{key}", positions=[0, 1])
    if state is not None:
        ledger.update(entry, state=state, evaluation_id=evaluation_id)
    return entry


def test_ledger_atomic_save_round_trip(tmp_path):
    ledger = _ledger(tmp_path)
    entry = _entry(ledger)
    assert entry["state"] == SUBMITTING and entry["evaluation_id"] is None
    ledger.update(entry, evaluation_id="e1", state=SUCCEEDED)
    ledger.event("launch", phase="A")
    ledger.save()
    loaded = Ledger.load(ledger.path, campaign_id="c1", manifest_sha256="sha256:aaa")
    assert loaded.data == ledger.data
    assert loaded.active_entry("m|t")["evaluation_id"] == "e1"
    assert loaded.evaluation_ids() == {"e1"}
    assert loaded.entry_by_evaluation("e1")["cell"] == "m|t"
    leftovers = [p.name for p in ledger.path.parent.iterdir() if p.name.endswith(".tmp")]
    assert leftovers == []


def test_ledger_save_refuses_invariant_violations_and_keeps_the_previous_file(tmp_path):
    ledger = _ledger(tmp_path)
    _entry(ledger, "m|t", SUCCEEDED, "e1")
    ledger.save()
    before = ledger.path.read_text()
    with pytest.raises(LedgerError, match="already has an active"):
        _entry(ledger, "m|t")
    # force a second active entry past new_entry's guard
    ledger.entries.append({**ledger.entries[0], "evaluation_id": "e2"})
    with pytest.raises(LedgerError, match="more than one active"):
        ledger.save()
    assert ledger.path.read_text() == before


def _raw_entry(cell: str, state, evaluation_id) -> dict:
    """A structurally complete entry (contract: every entry carries cell / model /
    task_id / phase / evaluation_name / state), so the invariant under test - not
    a missing key - is what the ledger refuses."""
    model, task = cell.split("|")
    return {"cell": cell, "model": model, "task_id": task, "phase": "A",
            "evaluation_name": f"campaign:c1:A:{cell}", "state": state, "evaluation_id": evaluation_id}


@pytest.mark.parametrize(
    "entries, match",
    [
        ([_raw_entry("m|t", SUCCEEDED, "e1"), _raw_entry("m|t", FAILED, "e2")], "more than one active"),
        ([_raw_entry("m|t", SUPERSEDED, "e1"), _raw_entry("m|u", SUCCEEDED, "e1")], "two ledger entries"),
        ([_raw_entry("m|t", "done", "e1")], "unknown state"),
        # a null state is now caught by the structural check (contract change 8)
        ([_raw_entry("m|t", None, None)], r"lacks \['state'\]"),
        ([_raw_entry("m|t", SUCCEEDED, 7)], "malformed evaluation_id"),
        ([_raw_entry("m|t", SUCCEEDED, "")], "malformed evaluation_id"),
    ],
)
def test_ledger_load_refuses_broken_invariants(tmp_path, entries, match):
    ledger = _ledger(tmp_path)
    ledger.data["entries"] = entries
    ledger.path.parent.mkdir(parents=True, exist_ok=True)
    ledger.path.write_text(json.dumps(ledger.data))
    with pytest.raises(LedgerError, match=match):
        Ledger.load(ledger.path)


def test_ledger_load_refuses_a_corrupt_entry_with_a_ledger_error(tmp_path):
    # Was a PRODUCT BUG (fixed in e2c86dc): LedgerError is documented as "the
    # ledger is missing, locked, corrupt, or belongs to another plan", and
    # validate/status/cli only catch LedgerError; an entry without a "cell" key
    # used to escape _check_invariants as a bare KeyError (a non-dict entry as
    # AttributeError).
    ledger = _ledger(tmp_path)
    ledger.path.parent.mkdir(parents=True, exist_ok=True)
    for entries in ([{"state": SUCCEEDED, "evaluation_id": "e1"}], ["garbage"], "not-a-list"):
        ledger.data["entries"] = entries
        ledger.path.write_text(json.dumps(ledger.data))
        with pytest.raises(LedgerError):
            Ledger.load(ledger.path)


def test_ledger_identity_is_enforced(tmp_path):
    ledger = _ledger(tmp_path)
    ledger.save()
    with pytest.raises(LedgerError, match="manifest changed"):
        Ledger.load(ledger.path, campaign_id="c1", manifest_sha256="sha256:bbb")
    with pytest.raises(LedgerError, match="belongs to campaign"):
        Ledger.load(ledger.path, campaign_id="c2", manifest_sha256="sha256:aaa")
    with pytest.raises(LedgerError, match="manifest changed"):
        Ledger.open_or_create(ledger.path, campaign_id="c1", manifest_sha256="sha256:bbb",
                              manifest_path="m.json")
    with pytest.raises(LedgerError, match="no campaign ledger"):
        Ledger.load(tmp_path / "missing.json")
    (tmp_path / "junk.json").write_text("{")
    with pytest.raises(LedgerError, match="unreadable"):
        Ledger.load(tmp_path / "junk.json")
    (tmp_path / "v2.json").write_text(json.dumps({**ledger.data, "schema_version": 2}))
    with pytest.raises(LedgerError, match="schema"):
        Ledger.load(tmp_path / "v2.json")
    created = Ledger.open_or_create(tmp_path / "new" / "ledger.json", campaign_id="c1",
                                    manifest_sha256="sha256:aaa", manifest_path="m.json")
    assert created.path.exists() and created.entries == []


def test_ledger_lock_is_exclusive(tmp_path):
    first = _ledger(tmp_path)
    first.save()
    second = Ledger.load(first.path)
    with first.lock():
        with pytest.raises(LedgerError, match="only one launcher"):
            with second.lock():
                pass  # pragma: no cover
        with pytest.raises(LedgerError):
            with first.lock():  # not re-entrant either: a second fd is a second launcher
                pass  # pragma: no cover
    with second.lock():  # released on exit
        pass


def test_ledger_lock_excludes_another_process(tmp_path):
    import subprocess
    import sys

    ledger = _ledger(tmp_path)
    ledger.save()
    script = (
        "import sys; sys.path[:0] = sys.argv[2:]\n"
        "from pathlib import Path\n"
        "from afa_campaign.ledger import Ledger, LedgerError\n"
        "try:\n"
        "    with Ledger(Path(sys.argv[1]), {}).lock(): print('ACQUIRED')\n"
        "except LedgerError: print('REFUSED')\n"
    )
    argv = [sys.executable, "-c", script, str(ledger.path), str(paths.REPO / "campaigns"), str(paths.REPO)]
    with ledger.lock():
        held = subprocess.run(argv, capture_output=True, text=True, timeout=60)
    free = subprocess.run(argv, capture_output=True, text=True, timeout=60)
    assert held.stdout.strip() == "REFUSED", held.stderr
    assert free.stdout.strip() == "ACQUIRED", free.stderr


def test_supersede_rules(tmp_path):
    ledger = _ledger(tmp_path)
    _entry(ledger, "m|ok", SUCCEEDED, "e-ok")
    _entry(ledger, "m|live", SUBMITTED, "e-live")
    _entry(ledger, "m|new", SUBMITTING)
    _entry(ledger, "m|bad", FAILED, "e-bad")
    for key in ("m|ok", "m|live", "m|new"):
        with pytest.raises(LedgerError):
            ledger.supersede(key, "operator decision")
    with pytest.raises(LedgerError, match="succeeded cell is final"):
        ledger.supersede("m|ok", "the result looked too good")
    for reason in ("", "   ", None):
        with pytest.raises(LedgerError, match="reason"):
            ledger.supersede("m|bad", reason)
    assert ledger.active_entry("m|bad")["state"] == FAILED
    with pytest.raises(LedgerError, match="no active"):
        ledger.supersede("m|nothing", "x")
    for state in (NEEDS_ATTENTION, REJECTED, "canceled"):
        key = f"m|{state}"
        _entry(ledger, key, state, f"e-{state}")
        ledger.supersede(key, f"  {state} investigated  ")
        assert ledger.active_entry(key) is None
    entry = ledger.supersede("m|bad", "backend crashed; see incident 7")
    assert entry["state"] == SUPERSEDED and entry["superseded_reason"] == "backend crashed; see incident 7"
    assert ledger.active_entry("m|bad") is None
    assert "e-bad" in ledger.evaluation_ids(active_only=False)
    assert "e-bad" not in ledger.evaluation_ids()
    assert ledger.data["events"][-1]["type"] == "superseded"
    replacement = _entry(ledger, "m|bad")  # a superseded cell may be re-run
    assert replacement["state"] == SUBMITTING
    ledger.save()
    reloaded = Ledger.load(ledger.path)
    assert reloaded.active_entry("m|bad")["state"] == SUBMITTING
    assert [e["state"] for e in reloaded.entries_for("m|bad")] == [SUPERSEDED, SUBMITTING]


# =========================================================================== #
# Cohort: the definition of a valid campaign cell, on REAL lifecycle evidence
# =========================================================================== #


def test_golden_cells_are_valid_real_fresh_evidence(golden):
    m = golden.manifest
    assert set(golden.evals) == {c.key for c in m.cells()}
    with closing(cohort.open_readonly(golden.db)) as conn:
        for cell in m.cells():
            result = cohort.check_cell_evaluation(conn, m, cell, golden.evals[cell.key])
            assert result.ok, result.as_dict()
            assert result.problems == [] and result.warnings == []
            assert result.job_status == "succeeded"
            assert (result.n_runs, result.valid, result.voided) == (2, 2, 0)
            assert result.classes == {"real": 2}
            assert sorted(result.positions) == [0, 1]
            assert len(result.run_ids) == 2
            records = cohort.load_cell_records(golden.db, result)
            assert sorted(r.run_id for r in records) == result.run_ids
            assert {r.task_version for r in records} == {m.task_by_id[cell.task_id]["task_version"]}
            progress = cohort.evaluation_progress(conn, golden.evals[cell.key])
            assert progress["status"] == "succeeded" and progress["trial_states"] == {"completed": 2}
            assert (progress["total"], progress["completed"]) == (2, 2)
        runs = conn.execute("SELECT id, backend_kind, job_id FROM runs").fetchall()
        assert len(runs) == 10  # 4 campaign cells + 1 foreign evaluation, 2 runs each
        assert {r["backend_kind"] for r in runs} == {"ollama"}
        assert cohort.jobless_run_count(conn) == 0
        named = cohort.evaluations_named(conn, m.data["evaluation_name_prefix"])
        assert {e["id"] for e in named} == set(golden.evals.values())  # never the foreign one
        assert {e["name"] for e in named} == {m.evaluation_name(c) for c in m.cells()}
        assert len(cohort.all_evaluations(conn)) == 5
        assert cohort.evaluation_progress(conn, "nope") == {"status": None}
    # the worker's per-trial seed policy: position idx runs with base_seed + idx
    by_name: dict[str, list[int]] = {}
    for name, seed in golden.seeds:
        by_name.setdefault(name, []).append(seed)
    for cell in m.cells():
        assert by_name[m.evaluation_name(cell)] == [42, 43]


def test_a_foreign_evaluation_is_valid_evidence_only_by_its_own_name(golden):
    # the foreign evaluation has identical evidence but is not the campaign's
    result = check(golden.db, golden.manifest, golden.cell(3), golden.foreign)
    assert_only(result, "parameter name")


def test_wrong_model_and_wrong_task_evaluations_fail(golden):
    m = golden.manifest
    c_3b_first, c_3b_second, c_gemma_first = golden.cell(0), golden.cell(1), golden.cell(2)
    assert c_3b_first.task_id == c_gemma_first.task_id and c_3b_first.model != c_gemma_first.model
    # ledger mix-up: cell (gemma, T) pointed at the evaluation of (3b, T)
    wrong_model = check(golden.db, m, c_gemma_first, golden.evals[c_3b_first.key])
    assert_only(wrong_model, "parameter model", "parameter name", "raw run identity")
    # ledger mix-up: cell (3b, T1) pointed at the evaluation of (3b, T2)
    wrong_task = check(golden.db, m, c_3b_first, golden.evals[c_3b_second.key])
    assert_only(wrong_task, "parameter tasks", "parameter name", "snapshot task", "trial positions",
                "trial version/digest", "raw run identity")


def test_no_or_unknown_evaluation_fails(golden):
    assert_only(check(golden.db, golden.manifest, golden.cell(0), None), "no evaluation recorded")
    assert_only(check(golden.db, golden.manifest, golden.cell(0), "0" * 32), "missing from the campaign database")


@pytest.mark.parametrize(
    "variant, fragments",
    [
        ("undeclared", ("runs.backend_kind is None",)),
        ("mock_declared", ("runs.backend_kind is 'mock'", "provenance class is 'conflict'")),
        ("temperature", ("parameter temperature is 0.5",)),
        ("base_seed", ("parameter base_seed is 7",)),
        ("repeats", ("parameter repeats is 2", "trial positions")),
        ("name", ("parameter name",)),
        ("timeout", ("parameter request_timeout_s is 60",)),
        ("backend_url", ("parameter backend.base_url",)),
    ],
)
def test_wrongly_run_lifecycle_evaluations_fail_with_the_specific_problem(variants, variant, fragments):
    valid = check(variants.db, variants.manifest, variants.cell, variants.evals["valid"])
    assert valid.ok, valid.as_dict()
    result = check(variants.db, variants.manifest, variants.cell, variants.evals[variant])
    assert result.job_status == "succeeded"  # the runtime was happy; the CAMPAIGN is not
    assert_only(result, *fragments)


def test_reuse_mode_evaluation_is_never_campaign_evidence(variants):
    result = check(variants.db, variants.manifest, variants.cell, variants.evals["reuse"])
    assert result.job_status == "succeeded"
    assert_only(
        result,
        "campaign evidence must be fresh",
        "evidence is 'reused', not fresh",
        "does not originate in this evaluation",
        "raw run is owned by evaluation",
    )
    assert result.run_ids == check(variants.db, variants.manifest, variants.cell,
                                   variants.evals["valid"]).run_ids


def _run_of(db: Path, evaluation_id: str, idx: int = 0) -> int:
    with closing(cohort.open_readonly(db)) as conn:
        return int(conn.execute(
            "SELECT run_id FROM evaluation_trials WHERE evaluation_id=? AND idx=?",
            (evaluation_id, idx)).fetchone()[0])


def _snapshot_with(golden: Golden, evaluation_id: str, **task_fields) -> str:
    with closing(cohort.open_readonly(golden.db)) as conn:
        snapshot = json.loads(conn.execute(
            "SELECT snapshot_json FROM evaluation_jobs WHERE id=?", (evaluation_id,)).fetchone()[0])
    snapshot["tasks"][0].update(task_fields)
    return json.dumps(snapshot, sort_keys=True)


TAMPERS = {
    "run backend mock": (
        lambda g, e, r: [("UPDATE runs SET backend_kind='mock' WHERE id=?", (r,))],
        ("runs.backend_kind is 'mock'", "provenance class is 'conflict'")),
    "run backend openai_compat": (
        lambda g, e, r: [("UPDATE runs SET backend_kind='openai_compat' WHERE id=?", (r,))],
        ("runs.backend_kind is 'openai_compat'", "provenance class is 'conflict'")),
    "run backend erased": (
        lambda g, e, r: [("UPDATE runs SET backend_kind=NULL WHERE id=?", (r,))],
        ("runs.backend_kind is None",)),
    "all runs mock": (
        lambda g, e, r: [("UPDATE runs SET backend_kind='mock' WHERE job_id=?", (e,))],
        ("runs.backend_kind is 'mock'", "provenance class is 'conflict'")),
    "snapshot digest": (
        lambda g, e, r: [("UPDATE evaluation_jobs SET snapshot_json=? WHERE id=?",
                          (_snapshot_with(g, e, task_digest="sha256:" + "0" * 64), e))],
        ("snapshot task digest differs",)),
    "snapshot version": (
        lambda g, e, r: [("UPDATE evaluation_jobs SET snapshot_json=? WHERE id=?",
                          (_snapshot_with(g, e, task_version="9.9.9"), e))],
        ("snapshot task version",)),
    "trial digest": (
        lambda g, e, r: [("UPDATE evaluation_trials SET task_digest='sha256:0' WHERE evaluation_id=? AND idx=1",
                          (e,))],
        ("trial version/digest differ",)),
    "extra owned run": (
        lambda g, e, r: [(
            "INSERT INTO runs (task_id, task_version, agent, idx, status, transcript_hash, duration_ms, "
            "job_id, backend_kind) SELECT task_id, task_version, agent, 2, status, transcript_hash, "
            "duration_ms, job_id, backend_kind FROM runs WHERE id=?", (r,))],
        ("outside its trial positions",)),
    "trial not completed": (
        lambda g, e, r: [("UPDATE evaluation_trials SET trial_state='pending' WHERE evaluation_id=? AND idx=1",
                          (e,))],
        ("trial is 'pending'",)),
    "trial lost its run": (
        lambda g, e, r: [("UPDATE evaluation_trials SET run_id=NULL WHERE evaluation_id=? AND idx=0", (e,))],
        ("no raw run", "outside its trial positions")),
    "trial missing": (
        lambda g, e, r: [("DELETE FROM evaluation_trials WHERE evaluation_id=? AND idx=1", (e,))],
        ("trial positions", "outside its trial positions")),
    "trial evidence reused": (
        lambda g, e, r: [("UPDATE evaluation_trials SET evidence_state='reused' WHERE evaluation_id=? AND idx=0",
                          (e,))],
        ("evidence is 'reused'",)),
    "trial origin elsewhere": (
        lambda g, e, r: [("UPDATE evaluation_trials SET origin_evaluation_id='x' WHERE evaluation_id=? AND idx=0",
                          (e,))],
        ("does not originate in this evaluation",)),
    "score row missing": (
        lambda g, e, r: [("DELETE FROM run_scores WHERE run_id=?", (r,))],
        ("no score row of formula v0.1",)),
    "score row of another formula only": (
        lambda g, e, r: [("UPDATE run_scores SET formula_version='v0.0' WHERE run_id=?", (r,))],
        ("no score row of formula v0.1",)),
    "diff row missing": (
        lambda g, e, r: [("DELETE FROM diffs WHERE run_id=?", (r,))],
        ("no diff row",)),
    "run row missing": (
        lambda g, e, r: [("DELETE FROM runs WHERE id=?", (r,))],
        ("raw run row is missing",)),
    "run owned by another evaluation": (
        lambda g, e, r: [("UPDATE runs SET job_id='f' || job_id WHERE id=?", (r,))],
        ("raw run is owned by evaluation",)),
    "run version": (
        lambda g, e, r: [("UPDATE runs SET task_version='0.0.1' WHERE id=?", (r,))],
        ("raw run version",)),
    "run position": (
        lambda g, e, r: [("UPDATE runs SET idx=1 WHERE id=?", (r,))],
        ("raw run identity",)),
    "run agent": (
        lambda g, e, r: [("UPDATE runs SET agent='gemma2:2b' WHERE id=?", (r,))],
        ("raw run identity",)),
    "evaluation failed": (
        lambda g, e, r: [("UPDATE evaluation_jobs SET status='failed' WHERE id=?", (e,))],
        ("evaluation status is 'failed'",)),
    "evaluation still running": (
        lambda g, e, r: [("UPDATE evaluation_jobs SET status='running' WHERE id=?", (e,))],
        ("evaluation status is 'running'",)),
    "mode reuse": (
        lambda g, e, r: [("UPDATE evaluation_jobs SET mode='reuse' WHERE id=?", (e,))],
        ("campaign evidence must be fresh", "do not verify")),
    "source evaluation set": (
        lambda g, e, r: [("UPDATE evaluation_jobs SET source_evaluation_id='x' WHERE id=?", (e,))],
        ("campaign evidence must be fresh", "do not verify")),
    "params temperature (snapshot not updated)": (
        lambda g, e, r: [("UPDATE evaluation_jobs SET params_json=json_set(params_json, '$.temperature', 0.1) "
                          "WHERE id=?", (e,))],
        ("do not verify",)),
    "params name only (snapshot has no name)": (
        lambda g, e, r: [("UPDATE evaluation_jobs SET params_json=json_set(params_json, '$.name', 'x') "
                          "WHERE id=?", (e,))],
        ("parameter name is 'x'",)),
    "params corrupt": (
        lambda g, e, r: [("UPDATE evaluation_jobs SET params_json='{' WHERE id=?", (e,))],
        ("do not verify",)),
    "snapshot missing": (
        lambda g, e, r: [("UPDATE evaluation_jobs SET snapshot_json=NULL WHERE id=?", (e,))],
        ("do not verify", "does not pin exactly one task")),
}


@pytest.mark.parametrize("label", sorted(TAMPERS))
def test_tampered_evidence_fails_with_a_specific_problem(golden, tmp_path, label):
    make, fragments = TAMPERS[label]
    cell = golden.cell(0)
    evaluation_id = golden.evals[cell.key]
    run_id = _run_of(golden.db, evaluation_id)
    db = tamper(golden.db, tmp_path / "t.sqlite", *make(golden, evaluation_id, run_id))
    result = check(db, golden.manifest, cell, evaluation_id)
    assert_only(result, *fragments)
    with pytest.raises(ValueError):
        cohort.load_cell_records(db, result)
    # the tampering is local to the tampered evaluation: the other cells still verify
    other = golden.cell(3)
    assert check(db, golden.manifest, other, golden.evals[other.key]).ok


def test_voided_positions_are_warnings_not_problems(golden, tmp_path):
    cell = golden.cell(0)
    evaluation_id = golden.evals[cell.key]
    run_id = _run_of(golden.db, evaluation_id, idx=1)
    db = tamper(golden.db, tmp_path / "v.sqlite",
                ("UPDATE runs SET status='infra_failure' WHERE id=?", (run_id,)),
                ("UPDATE run_scores SET voided=1, functional_pass=0 WHERE run_id=?", (run_id,)))
    result = check(db, golden.manifest, cell, evaluation_id)
    assert result.ok and result.problems == [], result.as_dict()
    assert len(result.warnings) == 1 and "infrastructure-voided" in result.warnings[0]
    assert (result.n_runs, result.valid, result.voided, result.passed) == (2, 1, 1, 1)
    assert result.positions[1]["voided"] is True and result.positions[0]["voided"] is False
    # voided-by-score (status left 'valid') is voided too
    db2 = tamper(golden.db, tmp_path / "v2.sqlite",
                 ("UPDATE run_scores SET voided=1 WHERE run_id=?", (run_id,)))
    result2 = check(db2, golden.manifest, cell, evaluation_id)
    assert result2.ok and (result2.valid, result2.voided) == (1, 1)


def test_evaluations_named_requires_the_exact_prefix_boundary(golden, tmp_path):
    db = backup_copy(golden.db, tmp_path / "p.sqlite")
    prefix = golden.data["evaluation_name_prefix"]
    body = golden.manifest.job_body(golden.cell(0))
    with closing(app_db.connect(db)) as conn:
        lookalike = jobs.create_job(conn, JobCreate(**{**body, "name": body["name"].replace(prefix, prefix + "-2")}))
        bare = jobs.create_job(conn, JobCreate(**{**body, "name": prefix}))
    with closing(cohort.open_readonly(db)) as conn:
        ids = {e["id"] for e in cohort.evaluations_named(conn, prefix)}
    assert ids == set(golden.evals.values())
    assert lookalike.id not in ids and bare.id not in ids


# =========================================================================== #
# Completeness validator
# =========================================================================== #


def _all_succeeded(golden: Golden, manifest: Manifest, skip: tuple[int, ...] = ()):
    return [(c, golden.evals[c.key], SUCCEEDED) for i, c in enumerate(manifest.cells()) if i not in skip]


def test_validate_complete_campaign_and_cli_exit_0_with_receipt(golden, tmp_path, capsys):
    m = campaign_clone(golden, tmp_path)
    write_ledger(m, _all_succeeded(golden, m))
    receipt = validate_mod.validate_campaign(m)
    assert receipt["complete"] is True, receipt["problems"]
    assert receipt["problems"] == [] and receipt["warnings"] == []
    assert receipt["expected"]["cells"] == 4 and receipt["expected"]["runs"] == 8
    assert receipt["present"] == {"cells_complete": 4, "runs": 8, "valid_runs": 8, "models_complete": 2}
    assert receipt["missing"] == {"cells": [], "positions": 0}
    assert receipt["extra"]["untracked_campaign_evaluations"] == []
    assert receipt["extra"]["disowned_evaluations"] == []
    # model identity (contract change 2): the first launch's digests are the reference;
    # round 4: so is its Ollama SERVER version
    assert receipt["model_identity"] == {
        "reference_digests": {mdl: fake_digest(mdl) for mdl in m.models},
        "reference_ollama_version": OLLAMA_VERSION, "required": True}
    assert {row["cell"]: row["model_digest"] for row in receipt["cells"]} == {
        c.key: fake_digest(c.model) for c in m.cells()}
    assert receipt["evidence_classes"] == {"real": 8}
    assert receipt["historical_evidence_sha256"] == HISTORICAL_SHA256
    assert receipt["manifest_sha256"] == m.sha256
    for model in GOLDEN_MODELS:
        assert receipt["per_model"][model]["cells_complete"] == 2
        assert receipt["per_model"][model]["runs"] == 4
    assert all(row["ok"] and row["state"] == SUCCEEDED for row in receipt["cells"])
    assert "COMPLETE" in validate_mod.render(receipt)
    # the CLI: exit 0 and a receipt on disk that says the same
    manifest_file = tmp_path / "manifest.json"
    dump(m.data, manifest_file)
    receipt_file = tmp_path / "out" / "receipt.json"
    rc = cli.main(["--manifest", str(manifest_file), "validate", "--receipt", str(receipt_file)])
    assert rc == 0, capsys.readouterr().out
    written = json.loads(receipt_file.read_text())
    assert written["complete"] is True and written["present"]["runs"] == 8
    # default receipt location is under the campaign outputs
    assert cli.main(["--manifest", str(manifest_file), "validate", "--json"]) == 0
    assert (m.outputs_dir() / "completeness-receipt-all.json").exists()
    assert json.loads((m.outputs_dir() / "completeness-receipt-all.json").read_text())["complete"] is True


def test_validate_counts_missing_cells_and_positions_and_cli_exits_1(golden, tmp_path, capsys):
    m = campaign_clone(golden, tmp_path)
    cells = m.cells()
    rows = [(cells[0], golden.evals[cells[0].key], SUCCEEDED),
            (cells[1], golden.evals[cells[1].key], FAILED),   # halted cell
            (cells[2], None, SUBMITTING)]                     # never created
    write_ledger(m, rows)                                     # cells[3]: not started
    receipt = validate_mod.validate_campaign(m)
    assert receipt["complete"] is False
    assert receipt["present"]["cells_complete"] == 1 and receipt["present"]["runs"] == 2
    assert receipt["missing"]["cells"] == [c.key for c in cells[1:]]
    assert receipt["missing"]["positions"] == 6
    states = {row["cell"]: row["state"] for row in receipt["cells"]}
    assert states == {cells[0].key: SUCCEEDED, cells[1].key: FAILED, cells[2].key: SUBMITTING,
                      cells[3].key: "not_started"}
    # evaluations named for this campaign but not owned by the ledger are EXTRA
    assert set(receipt["extra"]["untracked_campaign_evaluations"]) == {
        golden.evals[cells[2].key], golden.evals[cells[3].key]}
    manifest_file = tmp_path / "manifest.json"
    dump(m.data, manifest_file)
    receipt_file = tmp_path / "r.json"
    assert cli.main(["--manifest", str(manifest_file), "validate", "--receipt", str(receipt_file)]) == 1
    assert json.loads(receipt_file.read_text())["complete"] is False
    assert "NOT COMPLETE" in capsys.readouterr().out


def test_validate_phase_scope_counts_only_that_phase(golden, tmp_path):
    m = campaign_clone(golden, tmp_path)
    write_ledger(m, _all_succeeded(golden, m))
    receipt = validate_mod.validate_campaign(m, phase="A")
    assert receipt["complete"] is True and receipt["expected"]["cells"] == 4
    receipt_b = validate_mod.validate_campaign(m, phase="B")
    assert receipt_b["expected"]["cells"] == 0
    # an empty scope is vacuous, but it must never report the campaign's evidence
    assert receipt_b["present"]["runs"] == 0


def test_validate_untracked_campaign_named_evaluation_is_extra_and_fails(golden, tmp_path):
    m = campaign_clone(golden, tmp_path)
    write_ledger(m, _all_succeeded(golden, m))
    with closing(app_db.connect(m.db_path())) as conn:  # a UI "retry" clone of a campaign evaluation
        clone = jobs.retry_job(conn, golden.evals[m.cells()[0].key])
    receipt = validate_mod.validate_campaign(m)
    assert receipt["complete"] is False
    assert receipt["extra"]["untracked_campaign_evaluations"] == [clone.id]
    assert any("not owned by the ledger" in p for p in receipt["problems"])
    # every planned cell is still individually complete: the failure is the extra
    assert receipt["present"]["cells_complete"] == 4 and receipt["missing"]["cells"] == []


def test_validate_superseded_evaluations_are_not_counted(golden, tmp_path):
    m = campaign_clone(golden, tmp_path)
    cells = m.cells()
    ledger = write_ledger(m, _all_succeeded(golden, m, skip=(0,)))
    entry = ledger.new_entry(key=cells[0].key, model=cells[0].model, task_id=cells[0].task_id,
                             phase=cells[0].phase, evaluation_name=m.evaluation_name(cells[0]),
                             positions=[0, 1])
    ledger.update(entry, evaluation_id=golden.evals[cells[0].key], state=REJECTED)
    ledger.supersede(cells[0].key, "rejected by the operator")
    ledger.save()
    receipt = validate_mod.validate_campaign(m)
    assert receipt["complete"] is False
    assert receipt["missing"]["cells"] == [cells[0].key]
    assert receipt["missing"]["positions"] == 2
    assert receipt["present"] == {"cells_complete": 3, "runs": 6, "valid_runs": 6, "models_complete": 1}
    row = next(r for r in receipt["cells"] if r["cell"] == cells[0].key)
    assert row["state"] == "not_started" and row["superseded_evaluations"] == [golden.evals[cells[0].key]]
    # a superseded evaluation is known to the ledger: never reported as extra
    assert receipt["extra"]["untracked_campaign_evaluations"] == []


def test_validate_foreign_real_evaluation_never_counts(golden, tmp_path):
    m = campaign_clone(golden, tmp_path)
    last = m.cells()[-1]
    # ledger never recorded the last cell; the DB holds (a) its campaign
    # evaluation (untracked -> extra) and (b) a foreign real evaluation of the
    # same model/task with identical evidence
    write_ledger(m, _all_succeeded(golden, m, skip=(3,)))
    receipt = validate_mod.validate_campaign(m)
    assert receipt["complete"] is False
    assert receipt["missing"]["cells"] == [last.key] and receipt["present"]["runs"] == 6
    assert golden.foreign not in receipt["extra"]["untracked_campaign_evaluations"]
    # even when the ledger is pointed at the foreign evaluation it does not count
    m2 = campaign_clone(golden, tmp_path, name="clone2")
    rows = _all_succeeded(golden, m2, skip=(3,)) + [(last, golden.foreign, SUCCEEDED)]
    write_ledger(m2, rows)
    receipt2 = validate_mod.validate_campaign(m2)
    assert receipt2["complete"] is False
    assert receipt2["missing"]["cells"] == [last.key]
    assert any(last.key in p and "parameter name" in p for p in receipt2["problems"])


def test_validate_rejects_a_succeeded_entry_whose_evidence_is_invalid(golden, tmp_path):
    m = campaign_clone(golden, tmp_path)
    write_ledger(m, _all_succeeded(golden, m))
    first = m.cells()[0]
    with closing(sqlite3.connect(str(m.db_path()))) as conn:
        conn.execute("UPDATE runs SET backend_kind='mock' WHERE job_id=?", (golden.evals[first.key],))
        conn.commit()
    receipt = validate_mod.validate_campaign(m)
    assert receipt["complete"] is False
    assert receipt["missing"]["cells"] == [first.key]
    assert receipt["present"]["runs"] == 6
    assert any(first.key in p and "backend_kind" in p for p in receipt["problems"])
    assert any("classify as 'conflict'" in p for p in receipt["problems"])


def test_validate_flags_ledger_entries_outside_the_plan_and_missing_ledger(golden, tmp_path):
    m = campaign_clone(golden, tmp_path)
    receipt = validate_mod.validate_campaign(m)  # no ledger at all
    assert receipt["complete"] is False and any(p.startswith("ledger:") for p in receipt["problems"])
    write_ledger(m, _all_succeeded(golden, m) + [("llama3.2:latest|toposort", "e-stray", SUCCEEDED)])
    receipt = validate_mod.validate_campaign(m)
    assert receipt["complete"] is False
    assert any("outside the manifest" in p for p in receipt["problems"])


def test_validate_refuses_a_ledger_from_another_plan(golden, tmp_path):
    m = campaign_clone(golden, tmp_path)
    write_ledger(m, _all_succeeded(golden, m))
    changed = copy.deepcopy(m.data)
    changed["generation"]["temperature"] = 0.2  # the frozen plan was edited after launch
    receipt = validate_mod.validate_campaign(Manifest(changed))
    assert receipt["complete"] is False
    assert any("manifest changed" in p for p in receipt["problems"])


# =========================================================================== #
# Status monitor
# =========================================================================== #


def _partial_campaign(golden: Golden, tmp_path: Path) -> tuple[Manifest, dict]:
    """c0 halted as NEEDS_ATTENTION with one voided position (what the launcher
    records now that voided cells are never accepted - contract change 1), c1
    succeeded with one functional failure, c2 a real FAILED evaluation, c3
    submitted and still queued."""
    m = campaign_clone(golden, tmp_path)
    c0, c1, c2, c3 = m.cells()
    ids = {}
    with closing(app_db.connect(m.db_path())) as conn:
        ids["c2"] = run_evaluation(conn, m.job_body(c2), failing_factory)
        assert jobs.get_job(conn, ids["c2"]).status == "failed"
        ids["c3"] = jobs.create_job(conn, JobCreate(**m.job_body(c3))).id
        r0 = conn.execute("SELECT run_id FROM evaluation_trials WHERE evaluation_id=? AND idx=1",
                          (golden.evals[c0.key],)).fetchone()[0]
        r1 = conn.execute("SELECT run_id FROM evaluation_trials WHERE evaluation_id=? AND idx=1",
                          (golden.evals[c1.key],)).fetchone()[0]
        conn.execute("UPDATE runs SET status='infra_failure' WHERE id=?", (r0,))
        conn.execute("UPDATE run_scores SET voided=1, functional_pass=0 WHERE run_id=?", (r0,))
        conn.execute("UPDATE run_scores SET functional_pass=0 WHERE run_id=?", (r1,))
        conn.commit()
    write_ledger(m, [(c0, golden.evals[c0.key], NEEDS_ATTENTION), (c1, golden.evals[c1.key], SUCCEEDED),
                     (c2, ids["c2"], FAILED), (c3, ids["c3"], SUBMITTED)])
    return m, ids


def test_status_counts_on_a_partially_complete_campaign(golden, tmp_path, capsys):
    m, ids = _partial_campaign(golden, tmp_path)
    c0, c1, c2, c3 = m.cells()
    st = status_mod.campaign_status(m)
    assert st["ledger_error"] is None and st["database_present"] is True
    # contract change 10: completed/passed/failed count ONLY accepted evidence (c1);
    # round 4: a needs-attention cell's evidence can never count (it is superseded
    # and re-evaluated fresh), so its positions are EXCLUDED, not "in progress"
    assert st["totals"] == {"planned_runs": 8, "completed_runs": 2, "remaining_runs": 6,
                            "passed": 1, "failed": 1, "voided": 0, "timeouts": 0,
                            "in_progress_runs": 0, "excluded_runs": 2}
    assert st["cells"] == {"planned": 4, "complete": 1, "incomplete": 3}
    assert (st["models_complete"], st["models_total"]) == (0, 2)
    assert (st["tasks_complete"], st["tasks_total"]) == (0, 2)
    assert [r["cell"] for r in st["evaluations_running"]] == [c3.key]
    assert st["evaluations_running"][0]["evaluation_id"] == ids["c3"]
    assert st["evaluations_running"][0]["status"] == "queued"
    assert [(h["cell"], h["state"]) for h in st["evaluations_halted"]] == [
        (c0.key, NEEDS_ATTENTION), (c2.key, FAILED)]
    assert st["failed_states"] == [FAILED, NEEDS_ATTENTION]
    assert st["superseded_entries"] == 0
    first_model = st["per_model"][c0.model]
    assert first_model == {"cells": 2, "cells_complete": 1, "planned_runs": 4, "completed_runs": 2,
                           "passed": 1, "failed": 1, "voided": 0}
    assert st["per_model"][c2.model]["cells_complete"] == 0
    states = {r["cell"]: r["state"] for r in st["cells_detail"]}
    assert states == {c0.key: NEEDS_ATTENTION, c1.key: SUCCEEDED, c2.key: FAILED, c3.key: SUBMITTED}
    detail = {r["cell"]: r for r in st["cells_detail"]}
    assert (detail[c0.key]["completed"], detail[c0.key]["in_progress"], detail[c0.key]["excluded"]) == (0, 0, 2)
    # c2's real FAILED evaluation (resumable) completed no position: in progress 0
    assert (detail[c2.key]["completed"], detail[c2.key]["in_progress"], detail[c2.key]["excluded"]) == (0, 0, 0)
    text = status_mod.render(st)
    assert "HALTED" in text and "running" in text and "in progress 0, excluded 2" in text
    # the monitor and the validator agree on what is complete
    receipt = validate_mod.validate_campaign(m)
    assert receipt["present"]["cells_complete"] == st["cells"]["complete"] == 1
    assert receipt["present"]["runs"] == st["totals"]["completed_runs"] == 2
    manifest_file = tmp_path / "manifest.json"
    dump(m.data, manifest_file)
    assert cli.main(["--manifest", str(manifest_file), "status", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["totals"]["completed_runs"] == 2


def test_status_without_ledger_or_database(golden, tmp_path):
    data = copy.deepcopy(golden.data)
    data["runtime"] = {**data["runtime"], "campaign_db": str(tmp_path / "none.sqlite"),
                       "runtime_dir": str(tmp_path / "rt"), "ledger": str(tmp_path / "rt" / "ledger.json"),
                       "outputs": str(tmp_path / "rt" / "out")}
    st = status_mod.campaign_status(Manifest(data))
    assert st["ledger_error"] and st["database_present"] is False
    assert st["totals"]["completed_runs"] == 0 and st["totals"]["remaining_runs"] == 8
    assert st["cells"]["complete"] == 0


def test_status_never_counts_a_cell_complete_without_the_campaign_database(golden, tmp_path, capsys):
    # round 4: a ledger that says 'succeeded' proves nothing without the database
    # that holds the evidence; the monitor says so instead of reporting progress
    m = campaign_clone(golden, tmp_path)
    write_ledger(m, _all_succeeded(golden, m))
    assert status_mod.campaign_status(m)["cells"]["complete"] == 4  # control
    for suffix in ("", "-wal", "-shm"):
        Path(str(m.db_path()) + suffix).unlink(missing_ok=True)
    st = status_mod.campaign_status(m)
    assert st["database_present"] is False and st["ledger_error"] is None
    assert st["cells"] == {"planned": 4, "complete": 0, "incomplete": 4}
    assert (st["models_complete"], st["tasks_complete"]) == (0, 0)
    assert all(s["cells_complete"] == 0 and s["completed_runs"] == 0 for s in st["per_model"].values())
    assert st["totals"]["completed_runs"] == 0 and st["totals"]["remaining_runs"] == 8
    assert "campaign database MISSING" in status_mod.render(st)
    receipt = validate_mod.validate_campaign(m)
    assert receipt["complete"] is False and receipt["present"]["cells_complete"] == 0
    manifest_file = tmp_path / "manifest.json"
    dump(m.data, manifest_file)
    assert cli.main(["--manifest", str(manifest_file), "status"]) == 0
    assert "campaign database MISSING" in capsys.readouterr().out


def test_status_and_validator_agree_on_a_succeeded_entry_without_an_evaluation_id(golden, tmp_path):
    m = campaign_clone(golden, tmp_path)
    first = m.cells()[0]
    write_ledger(m, [(first, None, SUCCEEDED)] + _all_succeeded(golden, m, skip=(0,)))
    receipt = validate_mod.validate_campaign(m)
    assert receipt["present"]["cells_complete"] == 3 and first.key in receipt["missing"]["cells"]
    assert any(first.key in p and "no evaluation recorded" in p for p in receipt["problems"])
    st = status_mod.campaign_status(m)
    assert st["cells"]["complete"] == receipt["present"]["cells_complete"] == 3
    assert {r["cell"]: r["state"] for r in st["cells_detail"]}[first.key] != SUCCEEDED


def test_status_never_counts_evidence_that_fails_the_campaign_checks(golden, tmp_path):
    # Was a PRODUCT BUG (fixed in e2c86dc): a ledger-succeeded cell whose
    # evidence no longer passes check_cell_evaluation is shown as
    # 'succeeded-but-invalid', but its runs used to be added to
    # completed/passed/remaining - progress and passes from evidence the
    # validator and the analysis EXCLUDE (here: every run re-labelled as mock).
    m = campaign_clone(golden, tmp_path)
    write_ledger(m, _all_succeeded(golden, m))
    first = m.cells()[0]
    with closing(sqlite3.connect(str(m.db_path()))) as conn:
        conn.execute("UPDATE runs SET backend_kind='mock' WHERE job_id=?", (golden.evals[first.key],))
        conn.commit()
    st = status_mod.campaign_status(m)
    detail = {r["cell"]: r for r in st["cells_detail"]}
    assert detail[first.key]["state"] == "succeeded-but-invalid"
    assert [h["cell"] for h in st["evaluations_halted"]] == [first.key]
    assert st["cells"]["complete"] == 3
    receipt = validate_mod.validate_campaign(m)
    assert receipt["present"]["runs"] == 6
    assert st["totals"]["completed_runs"] == receipt["present"]["runs"] == 6
    assert st["totals"]["remaining_runs"] == 2
    assert st["totals"]["passed"] == sum(s["passed"] for s in receipt["per_model"].values())



# =========================================================================== #
# Contract of e2c86dc (review round 1): strict completeness, model identity,
# disown, corrupt ledgers, status accounting
# =========================================================================== #


def test_validator_marks_a_succeeded_cell_with_a_voided_position_incomplete(golden, tmp_path, capsys):
    # contract change 1: complete requires present runs == valid runs == expected;
    # a voided position makes the cell incomplete with a problem (no fail_on_voided)
    import inspect

    assert "fail_on_voided" not in inspect.signature(validate_mod.validate_campaign).parameters
    m = campaign_clone(golden, tmp_path)
    first = m.cells()[0]
    run_id = _run_of(m.db_path(), golden.evals[first.key], idx=1)
    with closing(sqlite3.connect(str(m.db_path()))) as conn:
        conn.execute("UPDATE runs SET status='infra_failure' WHERE id=?", (run_id,))
        conn.execute("UPDATE run_scores SET voided=1, functional_pass=0 WHERE run_id=?", (run_id,))
        conn.commit()
    write_ledger(m, _all_succeeded(golden, m))
    receipt = validate_mod.validate_campaign(m)
    assert receipt["complete"] is False
    # round 4: 'present' counts ONLY accepted evidence (the shared predicate), so the
    # voided cell contributes nothing and all of its positions are missing
    assert receipt["missing"] == {"cells": [first.key], "positions": 2}
    assert any(first.key in p and "infrastructure-voided" in p and "supersede" in p
               for p in receipt["problems"]), receipt["problems"]
    assert receipt["present"] == {"cells_complete": 3, "runs": 6, "valid_runs": 6, "models_complete": 1}
    row = next(r for r in receipt["cells"] if r["cell"] == first.key)
    assert row["ok"] is False and (row["runs"], row["valid"], row["voided"]) == (2, 1, 1)  # sound, but short
    manifest_file = tmp_path / "manifest.json"
    dump(m.data, manifest_file)
    assert cli.main(["--manifest", str(manifest_file), "validate", "--receipt", str(tmp_path / "r.json")]) == 1
    assert "NOT COMPLETE" in capsys.readouterr().out


def test_the_receipt_reports_voided_positions_of_a_succeeded_cell(golden, tmp_path):
    m = campaign_clone(golden, tmp_path)
    first = m.cells()[0]
    run_id = _run_of(m.db_path(), golden.evals[first.key], idx=1)
    with closing(sqlite3.connect(str(m.db_path()))) as conn:
        conn.execute("UPDATE runs SET status='infra_failure' WHERE id=?", (run_id,))
        conn.execute("UPDATE run_scores SET voided=1, functional_pass=0 WHERE run_id=?", (run_id,))
        conn.commit()
    write_ledger(m, _all_succeeded(golden, m))
    receipt = validate_mod.validate_campaign(m)
    assert next(r for r in receipt["cells"] if r["cell"] == first.key)["voided"] == 1  # the row knows
    assert receipt["voided_positions"] == 1
    assert any("infrastructure-voided position(s) in succeeded cells" in w for w in receipt["warnings"])


def _identity_case(golden, tmp_path, name, *, launches=None, submit=None, finalize=None,
                   version_submit=..., version_finalize=...):
    """All four golden cells succeeded; cell 0's recorded digests (and, round 4,
    Ollama server versions) are overridden (``...`` keeps the matching value, a
    key is removed when the value is None)."""
    m = campaign_clone(golden, tmp_path, name=name)
    ledger = write_ledger(m, _all_succeeded(golden, m), launches=launches)
    entry = ledger.active_entry(m.cells()[0].key)
    for field_name, value in (("model_digest_at_submit", submit), ("model_digest_at_finalize", finalize),
                              ("ollama_version_at_submit", version_submit),
                              ("ollama_version_at_finalize", version_finalize)):
        if value is None:
            entry.pop(field_name)
        elif value is not ...:
            entry[field_name] = value
    ledger.save()
    return m, validate_mod.validate_campaign(m)


def test_validator_requires_the_model_identity_of_every_cell(golden, tmp_path):
    # contract change 2
    models = golden.manifest.models
    first = golden.cell(0)
    other = "sha256:" + "0" * 64

    def only_cell0_flagged(receipt, fragment):
        assert receipt["complete"] is False
        assert receipt["missing"]["cells"] == [first.key], receipt["problems"]
        assert [p for p in receipt["problems"] if fragment in p] and all(
            p.startswith(first.key) for p in receipt["problems"]), receipt["problems"]

    # the matching digests (control)
    _, ok = _identity_case(golden, tmp_path, "ok", submit=..., finalize=...)
    assert ok["complete"] is True, ok["problems"]
    # at_finalize missing or different
    only_cell0_flagged(_identity_case(golden, tmp_path, "nofin", submit=..., finalize=None)[1], "model identity")
    only_cell0_flagged(_identity_case(golden, tmp_path, "fin", submit=..., finalize=other)[1], "model identity")
    # at_submit different (even with a matching at_finalize)
    only_cell0_flagged(_identity_case(golden, tmp_path, "sub", submit=other, finalize=...)[1], "model identity")
    # round 4: at_submit is REQUIRED (the launcher writes it before every POST); an
    # entry without it (older launcher, hand edit) no longer proves its identity
    only_cell0_flagged(_identity_case(golden, tmp_path, "nosub", submit=None, finalize=...)[1], "model identity")
    # no reference at all: no launch recorded an inventory
    m, receipt = _identity_case(golden, tmp_path, "noref",
                                launches=[{"started_at": "x", "inventory": None, "check_code": True}],
                                submit=..., finalize=...)
    assert receipt["complete"] is False and receipt["model_identity"]["reference_digests"] == {}
    assert receipt["model_identity"]["reference_ollama_version"] is None
    assert sorted(receipt["missing"]["cells"]) == sorted(c.key for c in m.cells())
    assert all("no first-launch model digest" in p or "no first-launch Ollama server version" in p
               for p in receipt["problems"]), receipt["problems"]
    # a reference missing for ONE model flags only that model's cells
    partial = launch_record(models, {mdl: fake_digest(mdl) for mdl in models if mdl != first.model})
    m, receipt = _identity_case(golden, tmp_path, "partial", launches=[partial], submit=..., finalize=...)
    assert sorted(receipt["missing"]["cells"]) == sorted(c.key for c in m.cells() if c.model == first.model)


@pytest.mark.parametrize("label, overrides", [
    ("version at submit differs", {"version_submit": "0.0-other"}),
    ("version at finalize differs", {"version_finalize": "0.0-other"}),
    ("version at submit missing", {"version_submit": None}),
    ("version at finalize missing", {"version_finalize": None}),
    ("both versions moved together", {"version_submit": "0.0-other", "version_finalize": "0.0-other"}),
])
def test_validator_requires_the_ollama_server_version_of_every_cell(golden, tmp_path, label, overrides):
    # round 4: the Ollama SERVER version (it supplies every inference setting the
    # campaign does not send) is part of the identity: at submission AND at
    # finalisation it must equal the first launch's - a cell that moved with it
    # consistently is still not the campaign's cohort
    first = golden.cell(0)
    m, receipt = _identity_case(golden, tmp_path, label.replace(" ", "-"), submit=..., finalize=..., **overrides)
    assert receipt["complete"] is False, label
    assert receipt["missing"]["cells"] == [first.key], receipt["problems"]
    assert receipt["problems"] and all(p.startswith(first.key) and "Ollama server version" in p
                                       for p in receipt["problems"]), receipt["problems"]
    assert receipt["model_identity"]["reference_ollama_version"] == OLLAMA_VERSION
    # the monitor and the analysis use the same predicate
    st = status_mod.campaign_status(m)
    assert st["cells"]["complete"] == 3
    assert {r["cell"]: r["state"] for r in st["cells_detail"]}[first.key] == "succeeded-but-invalid"


def test_a_first_launch_without_a_server_version_leaves_no_cell_accepted(golden, tmp_path):
    # round 4: the reference server version is REQUIRED on Ollama: an inventory that
    # recorded none (e.g. an older launcher) proves nothing about the engine
    models = golden.manifest.models
    first_launch = launch_record(models)
    first_launch["inventory"].pop("ollama_version")
    m, receipt = _identity_case(golden, tmp_path, "nover", launches=[first_launch, launch_record(models)],
                                submit=..., finalize=...)
    assert receipt["model_identity"]["reference_ollama_version"] is None  # the FIRST inventory decides
    assert receipt["complete"] is False and receipt["present"]["cells_complete"] == 0
    assert sorted(receipt["missing"]["cells"]) == sorted(c.key for c in m.cells())
    assert all("no first-launch Ollama server version recorded" in p for p in receipt["problems"])


def test_the_reference_is_the_first_launch_that_recorded_an_inventory(golden, tmp_path):
    models = golden.manifest.models
    moved = {mdl: "sha256:" + "9" * 64 for mdl in models}
    later = launch_record(models, moved)
    later["inventory"]["ollama_version"] = "9.9-later"  # round 4: a later server version never becomes the reference
    launches = [
        {"started_at": "0", "phase": "A", "outcome": "halted", "inventory": None,  # no inventory: skipped
         "check_code": True},
        launch_record(models),                                                   # the reference
        later,                                                                   # a later launch
    ]
    m = campaign_clone(golden, tmp_path)
    write_ledger(m, _all_succeeded(golden, m), launches=launches)
    receipt = validate_mod.validate_campaign(m)
    assert receipt["model_identity"]["reference_digests"] == {mdl: fake_digest(mdl) for mdl in models}
    assert receipt["model_identity"]["reference_ollama_version"] == OLLAMA_VERSION
    assert receipt["complete"] is True, receipt["problems"]
    loaded = Ledger.load(m.ledger_path())
    assert launcher.reference_digests(loaded) == {mdl: fake_digest(mdl) for mdl in models}
    assert launcher.reference_ollama_version(loaded) == OLLAMA_VERSION
    assert launcher.reference_digests(None) == {} and launcher.reference_ollama_version(None) is None


def test_validator_ignores_a_disowned_clone_but_lists_it(golden, tmp_path):
    # contract change 6
    m = campaign_clone(golden, tmp_path)
    ledger = write_ledger(m, _all_succeeded(golden, m))
    with closing(app_db.connect(m.db_path())) as conn:
        clone = jobs.retry_job(conn, golden.evals[m.cells()[0].key]).id
    assert validate_mod.validate_campaign(m)["complete"] is False  # untracked: extra
    ledger.disown(clone, "UI retry clone")
    ledger.save()
    receipt = validate_mod.validate_campaign(m)
    assert receipt["complete"] is True, receipt["problems"]
    assert receipt["extra"]["disowned_evaluations"] == [clone]
    assert receipt["extra"]["untracked_campaign_evaluations"] == []


def test_ledger_disown_rules(tmp_path):
    ledger = _ledger(tmp_path)
    _entry(ledger, "m|ok", SUCCEEDED, "e-ok")
    _entry(ledger, "m|old", REJECTED, "e-old")
    ledger.supersede("m|old", "rejected; re-run")
    for reason in ("", "   ", None):
        with pytest.raises(LedgerError, match="reason"):
            ledger.disown("e-clone", reason)
    for owned in ("e-ok", "e-old"):  # active or superseded: owned, never disowned
        with pytest.raises(LedgerError, match="owned by a ledger entry"):
            ledger.disown(owned, "not mine")
    record = ledger.disown("e-clone", "  UI retry clone  ")
    assert record["evaluation_id"] == "e-clone" and record["reason"] == "UI retry clone"
    with pytest.raises(LedgerError, match="already disowned"):
        ledger.disown("e-clone", "twice")
    assert ledger.disowned_ids() == {"e-clone"}
    assert ledger.data["events"][-1]["type"] == "disowned"
    ledger.save()
    assert Ledger.load(ledger.path).disowned_ids() == {"e-clone"}
    # an evaluation both owned and disowned is a corrupt ledger
    ledger.data["disowned"].append({"evaluation_id": "e-ok", "reason": "x"})
    with pytest.raises(LedgerError, match="both owned and disowned"):
        ledger.save()
    ledger.data["disowned"][-1] = {"evaluation_id": "e-clone", "reason": "again"}
    with pytest.raises(LedgerError, match="disowned twice"):
        ledger.save()


def test_ledger_lock_works_before_the_ledger_exists(tmp_path):
    # contract change 7: the launcher locks first and creates the ledger only
    # after a passing preflight
    path = tmp_path / "rt" / "ledger.json"
    with launcher.ledger_lock(path):
        with pytest.raises(LedgerError, match="only one launcher"):
            with launcher.ledger_lock(path):
                pass  # pragma: no cover
    assert not path.exists()
    assert path.with_name("ledger.json.lock").exists()


CORRUPTIONS = {
    "non-dict entry": lambda d: d.update(entries=["garbage"]),
    "entries not a list": lambda d: d.update(entries="not-a-list"),
    "entry missing keys": lambda d: d["entries"][0].pop("model"),
    "entry with an empty key": lambda d: d["entries"][0].update(phase=""),
    "entry with a non-string cell": lambda d: d["entries"][0].update(cell=["m", "t"]),
    "disowned not a list": lambda d: d.update(disowned={"e": "x"}),
    "disowned record not an object": lambda d: d.update(disowned=["e-x"]),
    "disowned record without reason": lambda d: d.update(disowned=[{"evaluation_id": "e-x"}]),
    "disowned record with a blank reason": lambda d: d.update(disowned=[{"evaluation_id": "e-x", "reason": " "}]),
    "disowned record without id": lambda d: d.update(disowned=[{"reason": "x"}]),
    "launches not a list": lambda d: d.update(launches={"0": {}}),
    "events not a list": lambda d: d.update(events="x"),
    "top level not an object": lambda d: [d],
    # round 3 (138c75f): launch records are checked too
    "launch record not an object": lambda d: d["launches"].insert(0, "garbage"),
    "launch inventory not an object": lambda d: d["launches"][0].update(inventory=["x"]),
    "launch inventory without models": lambda d: d["launches"][0].update(inventory={"captured_at": "x"}),
    "launch inventory models not an object": lambda d: d["launches"][0]["inventory"].update(models=["m"]),
    "launch inventory model entry not an object": lambda d: d["launches"][0]["inventory"]["models"].update(
        {GOLDEN_MODELS[0]: "sha256:x"}),
    # round 4 (7d3a444): every event is an object with a non-empty string 'type'
    # (was a PRODUCT BUG: a non-object event crashed validate_campaign)
    "event not an object": lambda d: d["events"].append("garbage"),
    "event is null": lambda d: d["events"].append(None),
    "event without a type": lambda d: d["events"].append({"at": "2026-09-26T00:00:00Z", "cell": "x"}),
    "event with an empty type": lambda d: d["events"].append({"type": ""}),
    "event with a non-string type": lambda d: d["events"].append({"type": 7}),
    # round 4: every launch has a string started_at, and a boolean check_code if any
    "launch without started_at": lambda d: d["launches"][0].pop("started_at"),
    "launch with a non-string started_at": lambda d: d["launches"][0].update(started_at=20260926),
    "launch check_code truthy but not a bool": lambda d: d["launches"][0].update(check_code="yes"),
    "launch check_code 1": lambda d: d["launches"][0].update(check_code=1),
    "launch check_code null": lambda d: d["launches"][0].update(check_code=None),
    # round 4: an entry's resume records are a list of objects
    "entry resumes not a list": lambda d: d["entries"][0].update(resumes={"at": "x", "check_code": True}),
    "entry resume record not an object": lambda d: d["entries"][0].update(resumes=["accepted"]),
    "entry resume record null": lambda d: d["entries"][0].update(resumes=[None]),
}


@pytest.mark.parametrize("label", sorted(CORRUPTIONS))
def test_a_corrupt_ledger_is_a_ledger_error_for_validate_status_and_the_cli(golden, tmp_path, capsys, label):
    # contract change 8: LedgerError, never KeyError/AttributeError
    m = campaign_clone(golden, tmp_path)
    write_ledger(m, _all_succeeded(golden, m))
    data = json.loads(m.ledger_path().read_text())
    data = CORRUPTIONS[label](data) or data  # a corruption mutates in place or returns a replacement
    m.ledger_path().write_text(json.dumps(data))
    with pytest.raises(LedgerError):
        Ledger.load(m.ledger_path())
    receipt = validate_mod.validate_campaign(m)
    assert receipt["complete"] is False and any(p.startswith("ledger:") for p in receipt["problems"])
    assert receipt["present"]["runs"] == 0
    st = status_mod.campaign_status(m)
    assert st["ledger_error"] and st["totals"]["completed_runs"] == 0
    manifest_file = tmp_path / "manifest.json"
    dump(m.data, manifest_file)
    base_argv = ["--manifest", str(manifest_file)]
    assert cli.main(base_argv + ["validate", "--receipt", str(tmp_path / "r.json")]) == 1
    assert cli.main(base_argv + ["status"]) == 0
    capsys.readouterr()
    cell = m.cells()[0].key
    assert cli.main(base_argv + ["supersede", "--cell", cell, "--reason", "x"]) == 3
    assert cli.main(base_argv + ["disown", "--evaluation", golden.foreign, "--reason", "x"]) == 3
    assert capsys.readouterr().err.count("refused:") == 2


def test_status_reports_in_progress_and_excluded_runs_separately(golden, tmp_path, capsys):
    # contract change 10: completed/passed/failed count ONLY accepted evidence;
    # in-flight/halted positions are in_progress, rejected/invalid are excluded
    m = campaign_clone(golden, tmp_path)
    c0, c1, c2, c3 = m.cells()
    with closing(sqlite3.connect(str(m.db_path()))) as conn:
        conn.execute("UPDATE runs SET backend_kind='mock' WHERE job_id=?", (golden.evals[c3.key],))
        conn.commit()
    write_ledger(m, [(c0, golden.evals[c0.key], REJECTED), (c1, golden.evals[c1.key], SUCCEEDED),
                     (c2, golden.evals[c2.key], SUBMITTED), (c3, golden.evals[c3.key], SUCCEEDED)])
    st = status_mod.campaign_status(m)
    assert st["totals"] == {"planned_runs": 8, "completed_runs": 2, "remaining_runs": 6, "passed": 2,
                            "failed": 0, "voided": 0, "timeouts": 0, "in_progress_runs": 2, "excluded_runs": 4}
    detail = {r["cell"]: r for r in st["cells_detail"]}
    # round 3: c2's entry is 'submitted' but its evaluation already SUCCEEDED in the
    # database - no launcher has accepted it yet: 'awaiting_finalize' (in progress,
    # listed with the halted cells, never counted as completed)
    assert {k: (r["state"], r["completed"], r["in_progress"], r["excluded"]) for k, r in detail.items()} == {
        c0.key: (REJECTED, 0, 0, 2), c1.key: (SUCCEEDED, 2, 0, 0),
        c2.key: ("awaiting_finalize", 0, 2, 0), c3.key: ("succeeded-but-invalid", 0, 0, 2)}
    assert st["cells"] == {"planned": 4, "complete": 1, "incomplete": 3}
    assert st["evaluations_running"] == []
    assert sorted(h["cell"] for h in st["evaluations_halted"]) == sorted([c0.key, c2.key, c3.key])
    assert st["failed_states"] == [REJECTED]
    assert st["per_model"][c0.model]["completed_runs"] == 2
    assert "in progress 2, excluded 4" in status_mod.render(st)
    receipt = validate_mod.validate_campaign(m)
    assert receipt["present"]["runs"] == st["totals"]["completed_runs"]
    assert receipt["present"]["cells_complete"] == st["cells"]["complete"]


@pytest.mark.parametrize("case", ["voided position", "model digest mismatch"])
def test_status_and_validator_agree_on_a_hand_edited_succeeded_cell(golden, tmp_path, case):
    # Was a PRODUCT BUG (fixed in 138c75f: status, validator and analysis share
    # validate.assess_cell): campaign_status accepted any 'succeeded' entry whose
    # cohort check was ok, so a cell with a voided position or a model digest
    # different from the campaign reference - rejected by validate_campaign - was
    # shown by the monitor as complete, its runs counted as completed.
    m = campaign_clone(golden, tmp_path)
    first = m.cells()[0]
    ledger = write_ledger(m, _all_succeeded(golden, m))
    if case == "voided position":
        run_id = _run_of(m.db_path(), golden.evals[first.key], idx=1)
        with closing(sqlite3.connect(str(m.db_path()))) as conn:
            conn.execute("UPDATE runs SET status='infra_failure' WHERE id=?", (run_id,))
            conn.execute("UPDATE run_scores SET voided=1, functional_pass=0 WHERE run_id=?", (run_id,))
            conn.commit()
    else:
        ledger.update(ledger.active_entry(first.key), model_digest_at_finalize="sha256:" + "0" * 64)
        ledger.save()
    receipt = validate_mod.validate_campaign(m)
    assert receipt["complete"] is False and receipt["missing"]["cells"] == [first.key]
    st = status_mod.campaign_status(m)
    assert st["cells"]["complete"] == receipt["present"]["cells_complete"] == 3
    assert {r["cell"]: r["state"] for r in st["cells_detail"]}[first.key] != SUCCEEDED


# =========================================================================== #
# Contract of 138c75f (review round 2): runtime-code audit, launch-record
# invariants, awaiting_finalize
# =========================================================================== #


def _code_check_case(golden, tmp_path, name, *, launches=None, events=(), cell0=None):
    """All four golden cells succeeded (every entry records a passing code check
    and a warm-up, as round 4's launcher writes them); ``cell0`` overrides fields
    of cell 0's entry (a value of None removes the key)."""
    m = campaign_clone(golden, tmp_path, name=name)
    ledger = write_ledger(m, _all_succeeded(golden, m), launches=launches)
    ledger.data["events"] += list(events)
    entry = ledger.active_entry(m.cells()[0].key)
    for key, value in (cell0 or {}).items():
        if value is None:
            entry.pop(key, None)
        else:
            entry[key] = value
    ledger.save()
    return m, validate_mod.validate_campaign(m)


def test_a_launch_without_the_code_check_or_warm_up_is_only_a_warning(golden, tmp_path, capsys):
    # Round 4 (was: any launch whose check_code was not True made the whole campaign
    # non-official): the audit is tied to EVIDENCE. Every accepted cell must itself
    # have been submitted and finalized under a passing code check (see below); a
    # rehearsal launch that touched no accepted cell is disclosed as a warning.
    models = golden.manifest.models
    missing_field = launch_record(models)
    missing_field.pop("check_code")  # a launcher that predates the audit
    cases = {
        "false": [launch_record(models), launch_record(models, check_code=False)],   # --no-code-check
        "missing": [launch_record(models), missing_field],
        "no warm-up": [launch_record(models), launch_record(models, warmup=False)],  # --no-warmup
        "first launch": [launch_record(models, check_code=False, warmup=False)],
    }
    for name, launches in cases.items():
        m, receipt = _code_check_case(golden, tmp_path, name.replace(" ", "-"), launches=launches)
        assert receipt["complete"] is True and receipt["problems"] == [], (name, receipt["problems"])
        assert receipt["present"]["cells_complete"] == 4 and receipt["missing"]["cells"] == [], name
        flagged = [w for w in receipt["warnings"] if "runtime-code check" in w and "warm-up" in w]
        assert len(flagged) == 1 and "is not accepted" in flagged[0], (name, receipt["warnings"])
    manifest_file = tmp_path / "manifest.json"
    dump(m.data, manifest_file)
    assert cli.main(["--manifest", str(manifest_file), "validate", "--receipt", str(tmp_path / "r.json")]) == 0
    out = capsys.readouterr().out
    assert "warning: launch" in out and "COMPLETE" in out and "NOT COMPLETE" not in out
    _, control = _code_check_case(golden, tmp_path, "control", launches=[launch_record(models)])
    assert control["complete"] is True and control["warnings"] == [], control["warnings"]


@pytest.mark.parametrize("label, cell0", [
    ("submitted without the check", {"code_check_at_submit": False}),
    ("finalized without the check", {"code_check_at_finalize": False}),
    ("submit record missing (older launcher)", {"code_check_at_submit": None}),
    ("finalize record missing", {"code_check_at_finalize": None}),
    ("truthy but not True", {"code_check_at_submit": "yes"}),
])
def test_every_accepted_cell_was_submitted_and_finalized_under_a_passing_code_check(
        golden, tmp_path, capsys, label, cell0):
    # round 4: the per-entry rule that replaces the launch-level audit
    first = golden.cell(0)
    m, receipt = _code_check_case(golden, tmp_path, label.split(" (")[0].replace(" ", "-"), cell0=cell0)
    assert receipt["complete"] is False, label
    assert receipt["present"]["cells_complete"] == 3 and receipt["missing"]["cells"] == [first.key]
    # round 5: the start (submission/resumes) and the acceptance are reported apart
    if "finaliz" in label:
        expected = (f"{first.key}: not accepted under a passing runtime-code check (--no-code-check or an older "
                    "launcher): not official evidence")
    else:
        expected = (f"{first.key}: submitted or resumed without a passing runtime-code check (--no-code-check or an "
                    "older launcher): not official evidence")
    assert receipt["problems"] == [expected], receipt["problems"]
    st = status_mod.campaign_status(m)
    assert st["cells"]["complete"] == 3 and st["totals"]["completed_runs"] == 6
    manifest_file = tmp_path / "manifest.json"
    dump(m.data, manifest_file)
    assert cli.main(["--manifest", str(manifest_file), "validate", "--receipt", str(tmp_path / "r.json")]) == 1
    assert "runtime-code check" in capsys.readouterr().out


def _resume_record(check_code=True, warmed_up=True, outcome="accepted", **extra) -> dict:
    record = {"at": "2026-09-26T01:00:00Z", "check_code": check_code, "warmed_up": warmed_up,
              "from_state": "failed", "outcome": outcome, **extra}
    return {k: v for k, v in record.items() if v is not ...}


def test_every_resume_of_an_accepted_cell_recorded_the_code_check_and_a_warm_up(golden, tmp_path):
    # round 4: each resume is a record on the ENTRY (written before POST /resume);
    # a resume that was not refused counts - accepted, requested or unknown alike.
    # Round 5: a record still 'requested'/'unknown' is unsettled (the launcher settles
    # it from the app's resume events before accepting): never accepted as is.
    first = golden.cell(0)
    code = (f"{first.key}: submitted or resumed without a passing runtime-code check (--no-code-check or an older "
            "launcher): not official evidence")
    unsettled = (f"{first.key}: a resume's outcome was never settled (a launch settles it from the app's resume "
                 "events while the evaluation is in flight; an entry already accepted by older tooling must be "
                 "superseded)")
    warm = (f"{first.key}: the model was not loaded before every start of this evaluation (--no-warmup): a cold "
            "load may have been charged to a trial's time budget; not official evidence")
    cases = {
        "checked": ([_resume_record()], []),
        "two checked resumes": ([_resume_record(), _resume_record(outcome="executed")], []),
        "an unsettled resume": ([_resume_record(), _resume_record(outcome="unknown")], [unsettled]),
        "never executed resumes never count": ([_resume_record(check_code=False, outcome="not_executed")], []),
        "skipped": ([_resume_record(check_code=False)], [code]),
        "field missing": ([_resume_record(check_code=...)], [code]),
        "truthy but not True": ([_resume_record(check_code=1)], [code]),
        "outcome unknown, skipped": ([_resume_record(check_code=False, outcome="unknown")], [unsettled, code]),
        "requested, skipped": ([_resume_record(check_code=False, outcome="requested")], [unsettled, code]),
        "one of two skipped": ([_resume_record(), _resume_record(check_code=False)], [code]),
        "refused resumes never count": ([_resume_record(check_code=False, warmed_up=False, outcome="refused"),
                                         _resume_record()], []),
        "not warmed": ([_resume_record(warmed_up=False)], [warm]),
        "warm-up field missing": ([_resume_record(warmed_up=...)], [warm]),
        "neither": ([_resume_record(check_code=False, warmed_up=False)], [code, warm]),
    }
    for name, (resumes, expected) in cases.items():
        _, receipt = _code_check_case(golden, tmp_path, name.replace(" ", "-").replace(",", ""),
                                      cell0={"resumes": resumes})
        assert receipt["problems"] == expected, (name, receipt["problems"])
        assert receipt["complete"] is (not expected), name
        assert receipt["present"]["cells_complete"] == (4 if not expected else 3), name


def test_the_event_based_resume_audit_is_gone(golden, tmp_path):
    # round 4: the verdict is tied to the entry's own records. A stray 'resumed'
    # event (e.g. of an entry since superseded) no longer taints the campaign ...
    stray = {"at": "2026-09-26T01:00:00Z", "type": "resumed", "cell": golden.cell(0).key,
             "evaluation_id": "e-resumed", "check_code": False}
    _, receipt = _code_check_case(golden, tmp_path, "stray", events=[stray])
    assert receipt["complete"] is True, receipt["problems"]
    # ... while an entry whose own record says the resume skipped the check is refused
    _, receipt = _code_check_case(golden, tmp_path, "own", cell0={"resumes": [_resume_record(check_code=False)]})
    assert receipt["complete"] is False and receipt["present"]["cells_complete"] == 3


def test_a_resume_that_recorded_no_code_check_is_not_official(golden, tmp_path):
    # Was a PRODUCT BUG (strict xfail until 7d3a444): a resume recorded WITHOUT the
    # check_code field passed the (event-based) audit. The per-entry resume record
    # must say check_code True.
    _, receipt = _code_check_case(golden, tmp_path, "no-field", cell0={"resumes": [_resume_record(check_code=...)]})
    assert receipt["complete"] is False
    assert any("runtime-code check" in p for p in receipt["problems"]), receipt["problems"]


def test_validate_reports_a_non_object_event_instead_of_crashing(golden, tmp_path):
    # Was a PRODUCT BUG (strict xfail until 7d3a444): a non-object event loaded and
    # crashed validate_campaign with AttributeError. It is now a corrupt ledger.
    m, _ = _code_check_case(golden, tmp_path, "bad-event")
    data = json.loads(m.ledger_path().read_text())
    data["events"].append("garbage")
    m.ledger_path().write_text(json.dumps(data))
    receipt = validate_mod.validate_campaign(m)
    assert receipt["complete"] is False
    assert any(p.startswith("ledger:") and "event #0 is malformed" in p for p in receipt["problems"])
    with pytest.raises(LedgerError, match="malformed"):
        Ledger.load(m.ledger_path())


def test_status_awaiting_finalize_for_a_submitted_entry_whose_evaluation_ended(golden, tmp_path, capsys):
    # round 3: 'submitted' in the ledger but terminal in the database = finished,
    # not yet judged by a launcher: in progress (never completed), listed with the
    # halted cells, never 'running' - whether the evaluation succeeded or failed
    m = campaign_clone(golden, tmp_path)
    c0, c1, c2, c3 = m.cells()
    with closing(app_db.connect(m.db_path())) as conn:
        failed = run_evaluation(conn, m.job_body(c1), failing_factory)
        queued = jobs.create_job(conn, JobCreate(**m.job_body(c2))).id
    write_ledger(m, [(c0, golden.evals[c0.key], SUBMITTED), (c1, failed, SUBMITTED), (c2, queued, SUBMITTED),
                     (c3, golden.evals[c3.key], SUCCEEDED)])
    st = status_mod.campaign_status(m)
    with closing(cohort.open_readonly(m.db_path())) as conn:
        failed_done = cohort.evaluation_progress(conn, failed)["completed"] or 0
    detail = {r["cell"]: r for r in st["cells_detail"]}
    assert {k: (r["state"], r["completed"], r["in_progress"]) for k, r in detail.items()} == {
        c0.key: ("awaiting_finalize", 0, 2), c1.key: ("awaiting_finalize", 0, failed_done),
        c2.key: (SUBMITTED, 0, 0), c3.key: (SUCCEEDED, 2, 0)}
    assert [(r["cell"], r["status"]) for r in st["evaluations_running"]] == [(c2.key, "queued")]
    assert [(h["cell"], h["state"]) for h in st["evaluations_halted"]] == [
        (c0.key, "awaiting_finalize"), (c1.key, "awaiting_finalize")]
    assert st["failed_states"] == []  # awaiting a verdict is not a failure
    assert st["totals"]["completed_runs"] == 2 and st["totals"]["in_progress_runs"] == 2 + failed_done
    assert st["cells"]["complete"] == 1
    receipt = validate_mod.validate_campaign(m)
    assert receipt["present"]["cells_complete"] == st["cells"]["complete"] == 1
    assert receipt["present"]["runs"] == st["totals"]["completed_runs"] == 2
    manifest_file = tmp_path / "manifest.json"
    dump(m.data, manifest_file)
    assert cli.main(["--manifest", str(manifest_file), "status"]) == 0
    out = capsys.readouterr().out
    assert f"HALTED: {c0.key} is awaiting_finalize" in out and f"running: {c2.key}" in out


# =========================================================================== #
# Contract of 7d3a444 (review round 3): the evidence guard hash folds an
# uncheckpointed WAL; the evidence store reads exactly the hashed file; a
# response cut off mid-body is a transport failure in both HTTP clients
# =========================================================================== #


def test_evidence_sha256_folds_an_uncheckpointed_wal_and_the_store_reads_only_the_main_file(tmp_path):
    # Everything here runs on a SCRATCH COPY of the evidence DB (the real file is
    # only read by shutil.copyfile).
    import shutil

    from afa_campaign.manifest import evidence_sha256, open_evidence_store

    copy = tmp_path / "evidence-copy.sqlite"
    shutil.copyfile(paths.EVIDENCE_DB, copy)
    wal = Path(str(copy) + "-wal")
    assert file_sha256(copy) == evidence_sha256(copy) == HISTORICAL_SHA256
    assert evidence_sha256(tmp_path / "absent.sqlite") is None
    wal.write_bytes(b"")  # an EMPTY -wal changes nothing a reader sees: ignored
    assert evidence_sha256(copy) == HISTORICAL_SHA256
    wal.unlink()
    writer = sqlite3.connect(str(copy))
    try:
        assert writer.execute("PRAGMA journal_mode").fetchone()[0] == "wal"  # the evidence DB is WAL-mode
        writer.execute("PRAGMA wal_autocheckpoint=0")
        victim, agent = writer.execute("SELECT id, agent FROM runs ORDER BY id LIMIT 1").fetchone()
        writer.execute("UPDATE runs SET agent='tampered-in-the-wal' WHERE id=?", (victim,))
        writer.commit()
        # the connection stays open: closing the last one would checkpoint the WAL
        assert wal.exists() and wal.stat().st_size > 0
        assert file_sha256(copy) == HISTORICAL_SHA256  # the main file is byte-identical ...
        folded = evidence_sha256(copy)  # ... but the guard hash is not
        assert folded == f"{HISTORICAL_SHA256}+uncheckpointed-wal:{file_sha256(wal)}" != HISTORICAL_SHA256
        # a plain read-only reader sees the WAL's change ...
        with closing(sqlite3.connect(f"{copy.as_uri()}?mode=ro", uri=True)) as reader:
            assert reader.execute("SELECT agent FROM runs WHERE id=?", (victim,)).fetchone()[0] == "tampered-in-the-wal"
        # ... the evidence store (immutable) reads exactly the hashed main file
        before_files = sorted(p.name for p in tmp_path.iterdir())
        store = open_evidence_store(copy)
        try:
            assert store.connection.execute("SELECT agent FROM runs WHERE id=?", (victim,)).fetchone()[0] == agent
            assert len(store.load_runs(agent=agent)) >= 1
            assert store.connection.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 720
        finally:
            store.close()
        with pytest.raises(sqlite3.ProgrammingError):
            store.connection.execute("SELECT 1")  # close() released the immutable connection
        assert sorted(p.name for p in tmp_path.iterdir()) == before_files  # no side files created
        with pytest.raises(FileNotFoundError):
            open_evidence_store(tmp_path / "absent.sqlite")
    finally:
        writer.close()


def test_the_evidence_store_never_writes_the_file_it_reads(tmp_path):
    import shutil

    from afa_campaign.manifest import open_evidence_store

    copy = tmp_path / "evidence-copy.sqlite"
    shutil.copyfile(paths.EVIDENCE_DB, copy)
    store = open_evidence_store(copy)
    try:
        with pytest.raises(sqlite3.OperationalError):
            store.connection.execute("UPDATE runs SET agent='x' WHERE id=(SELECT MIN(id) FROM runs)")
    finally:
        store.close()
    assert file_sha256(copy) == HISTORICAL_SHA256
    assert not Path(str(copy) + "-wal").exists() and not Path(str(copy) + "-shm").exists()


def test_preflight_and_validate_refuse_evidence_with_an_uncheckpointed_wal(golden, tmp_path, monkeypatch):
    # the frozen plan's evidence path pointed at a scratch copy with a non-empty
    # WAL beside it: the guard hash differs, so preflight and validate refuse
    import shutil

    from afa_campaign import ollama

    def offline_inventory(base_url, models):  # never the real Ollama
        raise ollama.OllamaError("offline test (simulated)")

    monkeypatch.setattr(ollama, "inventory", offline_inventory)
    copy = tmp_path / "evidence-copy.sqlite"
    shutil.copyfile(paths.EVIDENCE_DB, copy)
    m = campaign_clone(golden, tmp_path)
    data = json.loads(json.dumps(m.data))
    data["historical_evidence"]["path"] = str(copy)
    m = Manifest(data)
    write_ledger(m, _all_succeeded(golden, m))
    assert validate_mod.validate_campaign(m)["complete"] is True  # control: byte-identical copy
    Path(str(copy) + "-wal").write_bytes(b"\x00" * 64)
    receipt = validate_mod.validate_campaign(m)
    assert receipt["complete"] is False
    assert any("historical evidence DB sha256" in p and "uncheckpointed-wal" in p for p in receipt["problems"])
    assert "+uncheckpointed-wal:" in receipt["historical_evidence_sha256"]
    pf = launcher.preflight(m, None, check_code=False)
    assert any("historical evidence DB sha256" in p and "uncheckpointed-wal" in p for p in pf.problems)
    assert pf.facts["historical_evidence_sha256"].startswith(HISTORICAL_SHA256 + "+uncheckpointed-wal:")


class _TruncatingServer:
    """A one-thread HTTP server on 127.0.0.1 (ephemeral port) that answers every
    request with ``Content-Length: 100`` but sends only a few bytes of body and
    closes: the client's read raises http.client.IncompleteRead."""

    def __init__(self) -> None:
        import socket

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(8)
        self.sock.settimeout(0.2)
        self.url = f"http://127.0.0.1:{self.sock.getsockname()[1]}"
        self.requests: list[bytes] = []
        self._stop = False
        import threading

        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def _serve(self) -> None:
        import socket

        while not self._stop:
            try:
                conn, _ = self.sock.accept()
            except (socket.timeout, OSError):
                continue
            with conn:
                conn.settimeout(5)
                data = b""
                while b"\r\n\r\n" not in data:
                    chunk = conn.recv(65536)
                    if not chunk:
                        break
                    data += chunk
                head, _, body = data.partition(b"\r\n\r\n")
                length = 0
                for line in head.split(b"\r\n")[1:]:
                    name, _, value = line.partition(b":")
                    if name.strip().lower() == b"content-length":
                        length = int(value.strip())
                while len(body) < length:  # consume the request body: a clean close, never a reset
                    chunk = conn.recv(65536)
                    if not chunk:
                        break
                    body += chunk
                self.requests.append(head.split(b"\r\n")[0])
                conn.sendall(b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: 100\r\n"
                             b"Connection: close\r\n\r\n{\"status\": \"o")

    def close(self) -> None:
        self._stop = True
        self.thread.join(5)
        self.sock.close()


@pytest.fixture()
def truncating_server():
    server = _TruncatingServer()
    try:
        yield server
    finally:
        server.close()


def test_a_response_cut_off_mid_body_is_a_transport_failure_in_both_clients(truncating_server):
    # round 4: http.client.HTTPException (here IncompleteRead) is neither a URLError
    # nor an OSError; it used to escape both clients as a raw exception
    import http.client
    import urllib.request

    from afa_campaign import api as api_mod
    from afa_campaign import ollama

    assert not issubclass(http.client.IncompleteRead, OSError)
    with pytest.raises(http.client.IncompleteRead):  # the server really truncates the body
        with urllib.request.urlopen(truncating_server.url + "/probe", timeout=5) as response:
            response.read()
    client = api_mod.AgentForgeApi(truncating_server.url, timeout=5)
    for call in (client.health, client.list_jobs, lambda: client.resume("e1"),
                 lambda: client.create_job({"model": "m", "tasks": ["t"]})):
        with pytest.raises(api_mod.ApiUnreachable) as exc:  # the outcome of a mutating call is UNKNOWN
            call()
        assert exc.value.status is None
    with pytest.raises(ollama.OllamaError):
        ollama._call(truncating_server.url, "GET", "/api/version", timeout=5)
    with pytest.raises(ollama.OllamaError):
        ollama.inventory(truncating_server.url, ["qwen2.5-coder:3b"])
    with pytest.raises(ollama.OllamaError):
        ollama.warm_up(truncating_server.url, "qwen2.5-coder:3b", timeout=5)
    assert b"POST /api/v1/jobs/e1/resume HTTP/1.1" in truncating_server.requests
    assert b"POST /api/generate HTTP/1.1" in truncating_server.requests


def test_the_suite_never_reaches_a_real_model_server_or_app():
    # the conftest guard: the real Ollama port and the real app ports are refused
    from afa_campaign import api as api_mod
    from afa_campaign import ollama

    with pytest.raises(AssertionError, match="real service"):
        ollama._call("http://127.0.0.1:11434", "GET", "/api/version")
    for port in (8000, 8790, 8791):
        with pytest.raises(AssertionError, match="real service"):
            api_mod.AgentForgeApi(f"http://127.0.0.1:{port}").health()
