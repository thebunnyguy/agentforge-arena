"""Campaign analysis is computed from the campaign-owned cohort ONLY.

A small derived campaign (2 models x 2 tasks x 3 repetitions) runs offline through
the real ATLAS lifecycle (create_job -> evaluation snapshot -> trials -> worker ->
raw runs) with agent factories that DECLARE the ollama backend, so its runs are
provenance-real exactly like a genuine campaign's. ``qwen2.5-coder:7b`` overlays
the reference solution (passes); ``qwen3.5:9b`` makes no change (fails).

Two decoys live in the same campaign database, each producing the OPPOSITE outcome
of the cohort cell for its model/task so any leak would change the numbers:
an unrelated real evaluation with no ledger entry, and a superseded ledger entry.

Repetitions are 3, not 2: a fresh 0/2 has Wilson high 0.658 > the historical 5/5
Wilson low 0.566, so 'regressed' is unreachable with 2; 0/3 gives 0.5615 < 0.5655.

Tests that assert behaviour the product does not (yet) have are marked
``xfail(strict=True, reason="PRODUCT BUG: ...")``.
"""

from __future__ import annotations

import copy
import hashlib
import json

import pytest

import afa_runner as afa
from afa_api import db as app_db
from afa_api import jobs, worker
from afa_api.schemas import JobCreate
from afa_campaign import analysis, launcher, paths
from afa_campaign.analysis import INSUFFICIENT, IMPROVED, REGRESSED, STABLE, phase_a_status
from afa_campaign.ledger import REJECTED, SUCCEEDED, Ledger
from afa_campaign.manifest import Manifest, derive_subset
from afa_kernel.confidence import wilson_interval

GOOD = "qwen2.5-coder:7b"   # historical 5/5 on both tasks
BAD = "qwen3.5:9b"          # historical 5/5 on both tasks
BUMPED = "fix-list-dedup"   # ORACLE-bumped 1.0.1 -> 1.0.2; Phase-A prior-pass for both models
SAME = "escape-html"        # unchanged 1.0.1 (Phase B in the real plan; derive_subset makes it 'A')
REPS = 3
EVIDENCE_SHA = "42b6dad85ee662d6d5d7f75ffbda5a3b95d50837837f81c875730a8987838ced"
LAST = f"{BAD}|{SAME}"      # the cell completed last (incomplete -> complete)
# Keys whose run ids come from reports/runs.sqlite (a different id space).
HISTORICAL_KEYS = {"historical", "historical_run_ids", "old", "old_by_version"}


def _passing(model, task, params):
    return worker.mock_agent_factory(model, task, params)


def _failing(model, task, params):
    return afa.MockAgent(name=model)


_passing.backend_kind = "ollama"
_failing.backend_kind = "ollama"


def _sha(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _evaluate(conn, body: dict, factory) -> str:
    job = jobs.create_job(conn, JobCreate(**body))
    assert worker.claim_and_run(conn, agent_factory=factory) == job.id
    return job.id


def _launch(m: Manifest) -> dict:
    """The first launch record, as the launcher writes it: its Ollama inventory's
    digests are the campaign's model-identity reference, and (round 3) it records
    a passing runtime-code check - without it the campaign is never official."""
    return {
        "started_at": "2026-09-26T00:00:00Z", "phase": "A", "outcome": "phase-complete", "check_code": True,
        "warmup": True, "tooling_head": "0123456789ab", "runtime_release_tag": m.data["code"]["runtime_release_tag"],
        "runtime_release_commit": m.data["code"]["runtime_release_commit"],
        "api_url": "http://testserver/api/v1", "api_db_path": str(m.db_path()),
        "inventory": {"captured_at": "2026-09-26T00:00:00Z", "ollama_version": "0.99.0-test",
                      "source": "fake inventory (test)",
                      "models": {GOOD: {"present": True, "digest": "dae161e27b0e" + "0" * 52},
                                 BAD: {"present": True, "digest": "f" * 64}}},
    }


def _record(ledger: Ledger, manifest: Manifest, cell, evaluation_id: str, state: str = SUCCEEDED) -> None:
    entry = ledger.new_entry(key=cell.key, model=cell.model, task_id=cell.task_id, phase=cell.phase,
                             evaluation_name=manifest.evaluation_name(cell),
                             positions=list(range(manifest.repetitions)))
    # contract change 2: the launcher records the model digest at submission and
    # at finalisation; both must equal the first launch's (reference) digest.
    # Round 4: likewise the Ollama server version, and the entry itself carries
    # the runtime-code check (submit + finalize) and the warm-up it was made under.
    inventory = ledger.data["launches"][0]["inventory"]
    digest = inventory["models"][cell.model]["digest"]
    ledger.update(entry, evaluation_id=evaluation_id, state=state,
                  model_digest_at_submit=digest, model_digest_at_finalize=digest,
                  ollama_version_at_submit=inventory["ollama_version"],
                  ollama_version_at_finalize=inventory["ollama_version"],
                  code_check_at_submit=True, code_check_at_finalize=True, warmed_up_at_submit=True)
    ledger.save()


def _run_ids(conn, evaluation_id: str) -> set[int]:
    return {int(r[0]) for r in conn.execute("SELECT id FROM runs WHERE job_id=?", (evaluation_id,))}


def _collect(obj, keys: set[str], skip: set[str], out: list | None = None) -> list:
    """Every value stored under ``keys`` (lists flattened), not descending into ``skip``."""
    out = [] if out is None else out
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in skip:
                continue
            if k in keys:
                out.extend(v if isinstance(v, list) else [v])
            else:
                _collect(v, keys, skip, out)
    elif isinstance(obj, list):
        for v in obj:
            _collect(v, keys, skip, out)
    return out


def _fresh_run_ids(result: dict) -> set[int]:
    return {int(v) for v in _collect(result, {"run_ids", "run_id"}, HISTORICAL_KEYS) if v is not None}


def _evaluation_ids(result: dict) -> set[str]:
    keys = {"evaluation_id", "evaluation_ids", "fresh_evaluation_id"}
    return {v for v in _collect(result, keys, {"superseded_entries"}) if v}


def _analyse(manifest: Manifest) -> dict:
    return {
        "strict": analysis.official_baseline(manifest),
        "provisional": analysis.official_baseline(manifest, allow_incomplete=True),
        "phase_a": analysis.phase_a_comparison(manifest),
        "baseline": analysis.baseline_comparison(manifest),
    }


@pytest.fixture(scope="module")
def campaign(tmp_path_factory):
    before = _sha(paths.EVIDENCE_DB)
    tmp = tmp_path_factory.mktemp("analysis")
    data = derive_subset(Manifest.load().data, campaign_id="analysis-test", models=[GOOD, BAD],
                         task_ids=[BUMPED, SAME], repetitions=REPS, campaign_db=str(tmp / "c.sqlite"),
                         runtime_dir=str(tmp / "rt"), purpose="analysis test (NOT campaign evidence)")
    m = Manifest(data)
    launcher.init_db(m)
    ledger = Ledger.new(m.ledger_path(), campaign_id=m.campaign_id, manifest_sha256=m.sha256, manifest_path="")
    ledger.data["launches"].append(_launch(m))
    ledger.save()
    cells = {c.key: c for c in m.cells()}
    factory = {GOOD: _passing, BAD: _failing}
    conn = app_db.connect(m.db_path())
    try:
        for key, cell in cells.items():
            if key != LAST:
                _record(ledger, m, cell, _evaluate(conn, m.job_body(cell), factory[cell.model]))
        # Decoy 1: a campaign-named evaluation (passing) whose entry an operator superseded.
        superseded = _evaluate(conn, m.job_body(cells[LAST]), _passing)
        _record(ledger, m, cells[LAST], superseded, state=REJECTED)
        ledger.supersede(LAST, "test: operator replaced this evaluation")
        ledger.save()
        # Decoy 2: an unrelated REAL evaluation (passing) for a cohort model/task, never in the ledger.
        body = {**m.job_body(cells[f"{BAD}|{BUMPED}"]), "name": "ui-experiment"}
        unrelated = _evaluate(conn, body, _passing)
        incomplete = _analyse(m)
        final = _evaluate(conn, m.job_body(cells[LAST]), _failing)
        _record(ledger, m, cells[LAST], final)
        complete = _analyse(m)
        owned = {e["cell"]: e["evaluation_id"] for e in ledger.active_entries()}
        yield {
            "manifest": m, "tmp": tmp, "incomplete": incomplete, "complete": complete,
            "owned": owned, "owned_runs": {k: _run_ids(conn, v) for k, v in owned.items()},
            "superseded": superseded, "unrelated": unrelated,
            "decoy_runs": _run_ids(conn, superseded) | _run_ids(conn, unrelated),
            "evidence_sha_before": before,
        }
    finally:
        conn.close()


# --------------------------------------------------------------------------- #


def _side(c: int, n: int) -> dict:
    lo, hi = wilson_interval(c, n)
    return {"n_valid": n, "wilson_low": lo, "wilson_high": hi}


def test_phase_a_status_rule_covers_every_branch():
    assert phase_a_status(_side(0, 5), _side(3, 3), 3)[0] == IMPROVED      # 0.4385 > 0.4345
    assert phase_a_status(_side(5, 5), _side(0, 3), 3)[0] == REGRESSED     # 0.5615 < 0.5655
    assert phase_a_status(_side(5, 5), _side(0, 2), 2)[0] == STABLE        # why REPS is 3
    assert phase_a_status(_side(5, 5), _side(3, 3), 3)[0] == STABLE
    assert phase_a_status(_side(5, 5), _side(2, 2), 5)[0] == INSUFFICIENT  # fresh n_valid < reps
    assert phase_a_status(_side(2, 3), _side(3, 5), 5)[0] == INSUFFICIENT  # historical n_valid < reps
    assert phase_a_status(_side(0, 0), _side(3, 3), 0)[0] == INSUFFICIENT  # n_valid == 0
    assert phase_a_status(_side(5, 5), None, 3)[0] == INSUFFICIENT         # missing / invalid cell


def test_decoys_and_superseded_evidence_never_appear(campaign):
    owned_evals = set(campaign["owned"].values())
    owned_runs = set().union(*campaign["owned_runs"].values())
    assert campaign["decoy_runs"] and not campaign["decoy_runs"] & owned_runs
    for stage in ("incomplete", "complete"):
        for name, result in campaign[stage].items():
            if result is None:
                continue
            render = {"phase_a": analysis.render_phase_a, "baseline": analysis.render_baseline_comparison}.get(
                name, analysis.render_official_baseline)
            text = json.dumps(result) + render(result)
            assert campaign["unrelated"] not in text, (stage, name)
            assert _evaluation_ids(result) <= owned_evals, (stage, name)
            assert campaign["superseded"] not in _evaluation_ids(result)
            assert not _fresh_run_ids(result) & campaign["decoy_runs"], (stage, name)
            assert _fresh_run_ids(result) <= owned_runs, (stage, name)
            scrubbed = copy.deepcopy(result)
            scrubbed.get("provenance", {}).pop("superseded_entries", None)
            assert campaign["superseded"] not in json.dumps(scrubbed), (stage, name)
    evidence = campaign["complete"]["strict"]["evidence"]
    assert evidence["evaluation_ids"] == sorted(owned_evals)
    assert evidence["run_ids"] == sorted(owned_runs)
    assert evidence["runs_verified_owned"] == len(owned_runs) == 4 * REPS
    for key, runs in campaign["owned_runs"].items():
        assert evidence["by_cell"][key] == {"evaluation_id": campaign["owned"][key], "run_ids": sorted(runs)}


def test_official_baseline_none_then_provisional_then_official(campaign):
    inc, done = campaign["incomplete"], campaign["complete"]
    assert inc["strict"] is None
    prov = inc["provisional"]
    assert prov["official"] is False and prov["label"] == "PROVISIONAL - campaign incomplete"
    assert prov["missing_cells"] == [LAST]
    assert prov["task_matrix"][[r["task_id"] for r in prov["task_matrix"]].index(SAME)]["cells"][BAD] == {
        "evidence": None, "note": "no fresh evidence yet"}
    board = {e["agent"]: e for e in prov["leaderboard"]}
    assert (board[GOOD]["n"], board[BAD]["n"]) == (2 * REPS, REPS)
    assert board[BAD]["coverage"]["cells_with_fresh_evidence"] == 1
    md = analysis.render_official_baseline(prov)
    assert md.startswith("# PROVISIONAL - campaign incomplete")
    assert "**PROVISIONAL - campaign incomplete.**" in md and LAST in md

    for result in (done["strict"], done["provisional"]):
        assert result["official"] is True and result["label"] == "OFFICIAL post-Phase-0 baseline"
        assert result["missing_cells"] == [] and result["models_without_evidence"] == []
        assert result["provenance"]["completeness_receipt"]["complete"] is True
    assert "PROVISIONAL" not in analysis.render_official_baseline(done["strict"])


def test_official_leaderboard_matrix_and_domains_are_the_cohort(campaign):
    result, m = campaign["complete"]["strict"], campaign["manifest"]
    assert result["evidence_scope"]["class"] == "real"
    board = {e["agent"]: e for e in result["leaderboard"]}
    # n == the cohort's valid runs; a leak of either (passing) decoy would change BAD's numbers.
    assert {a: (e["n"], round(e["pass_rate"], 6)) for a, e in board.items()} == {
        GOOD: (2 * REPS, 1.0), BAD: (2 * REPS, 0.0)}
    assert board[GOOD]["rank_low"] is not None and board[GOOD]["rank_low"] < board[BAD]["rank_low"]
    for e in board.values():
        assert e["coverage"] == {"cells_with_fresh_evidence": 2, "manifest_tasks": 2, "fraction": 1.0}
        assert e["voided_runs"] == 0
    assert [r["task_id"] for r in result["task_matrix"]] == m.task_ids
    for row in result["task_matrix"]:
        assert row["task_version"] == m.task_by_id[row["task_id"]]["task_version"]
        for model, cell in row["cells"].items():
            key = f"{model}|{row['task_id']}"
            agg = cell["aggregate"]
            assert cell["evaluation_id"] == campaign["owned"][key]
            assert cell["run_ids"] == sorted(campaign["owned_runs"][key])
            assert (agg["n_valid"], agg["n_pass"]) == (REPS, REPS if model == GOOD else 0)
            assert agg["provisional"] is True and set(agg["pass_at_k"]) == {"1", "2", "3"}
            assert agg["wilson_low"] == pytest.approx(wilson_interval(agg["n_pass"], REPS)[0])
    for model, rate in ((GOOD, 1.0), (BAD, 0.0)):
        domains = {d["domain"]: d for d in result["domain_profiles"][model]}
        assert set(domains) == {"backend", "security"}
        assert (domains["backend"]["n_runs"], domains["backend"]["n_tasks"]) == (2 * REPS, 2)
        assert (domains["security"]["n_runs"], domains["security"]["n_tasks"]) == (REPS, 1)
        assert domains["backend"]["pooled_pass_rate"] == rate


def test_official_provenance_summary(campaign):
    prov, m = campaign["complete"]["strict"]["provenance"], campaign["manifest"]
    assert prov["campaign_id"] == m.campaign_id and prov["manifest_sha256"] == m.sha256
    assert prov["generation"]["seed_policy"] == m.generation["seed_policy"] and prov["repetitions"] == REPS
    assert {t["task_id"]: (t["task_version"], t["task_digest"]) for t in prov["tasks"]} == {
        t["task_id"]: (t["task_version"], t["task_digest"]) for t in m.data["tasks"]}
    assert prov["evaluation_per_cell"] == campaign["owned"]
    assert prov["superseded_entries"] == [{
        "cell": LAST, "evaluation_id": campaign["superseded"],
        "reason": "test: operator replaced this evaluation",
        "superseded_at": prov["superseded_entries"][0]["superseded_at"]}]
    launch = prov["launches"][0]
    assert launch["ollama_version"] == "0.99.0-test" and launch["tooling_head"] == "0123456789ab"
    assert launch["api_db_path"] == str(m.db_path()) and set(launch["digests"]) == {GOOD, BAD}
    assert (launch["check_code"], launch["warmup"]) == (True, True)  # round 4: disclosed per launch
    assert prov["model_identity"]["reference_ollama_version"] == "0.99.0-test"  # round 4: the engine too
    assert prov["historical_evidence"]["sha256"] == EVIDENCE_SHA
    md = analysis.render_official_baseline(campaign["complete"]["strict"])
    assert "Superseded (never counted)" in md and "0.99.0-test" in md


def test_phase_a_statuses_follow_the_rule(campaign):
    inc = {r["cell"]: r for r in campaign["incomplete"]["phase_a"]["cells"]}
    assert inc[LAST]["status"] == INSUFFICIENT and inc[LAST]["fresh"] is None
    assert inc[LAST]["fresh_state"] == "not_started"  # the superseded entry does not count
    result = campaign["complete"]["phase_a"]
    cells = {r["cell"]: r for r in result["cells"]}
    expected = {f"{GOOD}|{BUMPED}": STABLE, f"{GOOD}|{SAME}": STABLE,
                f"{BAD}|{BUMPED}": REGRESSED, f"{BAD}|{SAME}": REGRESSED}
    assert {k: r["status"] for k, r in cells.items()} == expected
    for key, r in cells.items():
        model, task = key.split("|")
        assert r["prior_pass"] is (task == BUMPED)
        assert (r["old_task_version"], r["new_task_version"]) == (
            ("1.0.1", "1.0.2") if task == BUMPED else ("1.0.1", "1.0.1"))
        assert r["task_version_changed"] is (task == BUMPED)
        hist, fresh = r["historical"], r["fresh"]
        assert (hist["n_runs"], hist["n_valid"], hist["passes"], hist["task_version"]) == (5, 5, 5, "1.0.1")
        assert (fresh["n_valid"], fresh["passes"]) == (REPS, REPS if model == GOOD else 0)
        assert fresh["evaluation_id"] == campaign["owned"][key]
        assert fresh["run_ids"] == sorted(campaign["owned_runs"][key])
        assert set(fresh["scores"]) == {"mean_s", "median_s", "min_s", "max_s", "std_s"}
        assert r["status_label"].startswith(("observed difference", "no observed difference"))
    assert result["summary"]["by_status"] == {IMPROVED: 0, REGRESSED: 2, STABLE: 2, INSUFFICIENT: 0}
    assert result["summary"]["by_model"][BAD][REGRESSED] == 2
    assert "too lenient" in result["interpretation"] and result["wording"] == "observed difference"
    md = analysis.render_phase_a(result)
    head = md.split("## Summary")[0]
    assert "observed difference" in head.lower() and result["interpretation"] in head
    assert "qwen3.5:9b\\|fix-list-dedup" in md  # the cell key's '|' does not break the table


def test_baseline_comparison_labels_pooling_and_disclosure(campaign):
    result = campaign["complete"]["baseline"]
    cells = {r["cell"]: r for r in result["cells"]}
    for model in (GOOD, BAD):
        bumped, same = cells[f"{model}|{BUMPED}"], cells[f"{model}|{SAME}"]
        assert (bumped["old_versions"], bumped["new_version"], bumped["versions_differ"]) == (["1.0.1"], "1.0.2", True)
        assert bumped["comparability"] == "NOT DIRECTLY COMPARABLE"
        assert (same["old_versions"], same["new_version"], same["versions_differ"]) == (["1.0.1"], "1.0.1", False)
        assert same["comparability"] == ("SAME TASK VERSION - direct comparison more defensible; "
                                         "execution stack differs")
        for r in (bumped, same):
            assert (r["old"]["runs"], r["old"]["valid"], r["old"]["passes"]) == (5, 5, 5)
            assert (r["new"]["valid"], r["new"]["passes"]) == (REPS, REPS if model == GOOD else 0)
        pooled = result["same_version_pooled_by_model"][model]
        assert pooled["tasks"] == [SAME] and pooled["version_changed_tasks_excluded"] == 1
        assert (pooled["old"]["n_valid"], pooled["old"]["passes"]) == (5, 5)
        assert (pooled["new"]["n_valid"], pooled["new"]["passes"]) == (REPS, REPS if model == GOOD else 0)
    pending = {r["cell"]: r for r in campaign["incomplete"]["baseline"]["cells"]}[LAST]
    assert pending["new"] is None and pending["new_status"] == "no fresh evidence yet"
    assert campaign["incomplete"]["baseline"]["same_version_pooled_by_model"][BAD]["same_version_tasks_pending"] == [SAME]

    stack = result["execution_stack"]
    hist = stack["historical"]
    # round 3: corrected to what README.md and the Sept-17 qwen3.5:9b report document
    assert hist["sources"] == ["README.md, section 'Evaluation provenance'",
                               "reports/qwen3.5-9b-evaluation-2026-09-17.md"]
    p0 = hist["p0_completion_runs"]
    assert (p0["ollama_version"], p0["temperature"], p0["base_seed"], p0["request_timeout_s"]) == (
        "0.17.4", 0.8, 42, None)
    assert p0["recorded_digests"] == {"qwen2.5-coder:7b": "dae161e27b0e", "llama3.2:latest": "a80c4f17acd5"}
    assert "examples/eval_persist.py" in p0["evaluation_path"] and p0["models"] == "not enumerated by the README"
    q35 = hist["per_model_exceptions"]["qwen3.5:9b"]
    assert (q35["temperature"], q35["base_seed"], q35["request_timeout_s"], q35["ollama_version"], q35["digest"]) == (
        0.6, 42, 180, None, None)
    assert "eb54c065c0b84d099a82570f4aeee83c" in q35["evaluation_path"] and "1101-1220" in q35["evaluation_path"]
    assert "which models' runs were the P0 completion runs" in hist["not_documented"]
    assert hist["persisted_facts"]["runs"] == hist["persisted_facts"]["runs_without_evaluation"] == 720
    assert any("app job whose linkage was not preserved" in d for d in stack["differences"])
    fresh = stack["fresh"]
    assert (fresh["temperature"], fresh["base_seed"]) == (0.8, 42) and fresh["ollama_versions"] == ["0.99.0-test"]
    assert stack["per_model"][GOOD]["digest"] == "same digest prefix dae161e27b0e"
    assert stack["per_model"][GOOD]["temperature"] == "same"
    assert stack["per_model"][BAD]["digest"].startswith("historical digest not recorded")
    assert stack["per_model"][BAD]["temperature"].startswith("DIFFERENT")
    assert stack["per_model"][GOOD]["ollama_version"].startswith("DIFFERENT Ollama version")


def test_baseline_comparison_markdown_renders_the_disclosure(campaign):
    # Was a PRODUCT BUG (strict xfail until 7d3a444): the render still read
    # HISTORICAL_STACK keys 138c75f removed and raised KeyError. It now renders
    # the corrected (documented) historical stack.
    for stage in ("incomplete", "complete"):
        result = campaign[stage]["baseline"]
        md = analysis.render_baseline_comparison(result)
        assert md.index("Read this first") < md.index("## EXECUTION-STACK DISCLOSURE") < md.index("## Per cell")
        for needle in ("NOT DIRECTLY COMPARABLE", "SAME TASK VERSION", "0.17.4", "dae161e27b0e", "a80c4f17acd5",
                       "SAME-TASK-VERSION tasks only", "eval_persist.py", "`qwen3.5:9b`: ",
                       "temperature 0.6, base seed 42, request timeout 180 s",
                       "eb54c065c0b84d099a82570f4aeee83c", "README.md, section 'Evaluation provenance'",
                       "app job whose linkage was not preserved"):
            assert needle in md, needle
        # round 4: each fresh launch discloses its runtime-code check and warm-up policy
        assert "Ollama 0.99.0-test, runtime-code check True, warm-up True." in md
        # the decoys never appear in the rendered comparison either
        assert campaign["unrelated"] not in md and campaign["superseded"] not in md


def test_cli_compare_baselines_writes_both_reports(campaign, tmp_path):
    """The operator command end to end: ``compare-baselines`` writes .json and
    .md; it never dies with a traceback. (Was a PRODUCT BUG - KeyError('producer') -
    until 7d3a444.)"""
    from afa_campaign import cli
    from afa_campaign.manifest import dump

    manifest_file = tmp_path / "manifest.json"
    dump(campaign["manifest"].data, manifest_file)
    out = tmp_path / "out"
    rc = cli.main(["--manifest", str(manifest_file), "compare-baselines", "--out-dir", str(out)])
    assert rc == 0
    assert json.loads((out / "pre-vs-post-phase0-comparison.json").read_text())["campaign_id"] == "analysis-test"
    assert "EXECUTION-STACK DISCLOSURE" in (out / "pre-vs-post-phase0-comparison.md").read_text()


def test_ledger_pointing_at_a_non_conforming_evaluation_is_excluded(campaign):
    """Same campaign id and database, another ledger: a 'succeeded' entry that names
    the unrelated evaluation fails the campaign checks and contributes nothing."""
    m, tmp = campaign["manifest"], campaign["tmp"]
    data = copy.deepcopy(m.data)
    data["runtime"] = {**data["runtime"], "runtime_dir": str(tmp / "rt2"), "ledger": str(tmp / "rt2/ledger.json")}
    m2 = Manifest(data)
    ledger = Ledger.new(m2.ledger_path(), campaign_id=m2.campaign_id, manifest_sha256=m2.sha256, manifest_path="")
    ledger.data["launches"].append(_launch(m2))
    wrong = f"{BAD}|{BUMPED}"
    for cell in m2.cells():
        _record(ledger, m2, cell, campaign["unrelated"] if cell.key == wrong else campaign["owned"][cell.key])
    co = analysis.load_cohort(m2)
    assert not co.cells[wrong].ok and any("ui-experiment" in p for p in co.cells[wrong].problems)
    assert analysis.official_baseline(m2) is None
    prov = analysis.official_baseline(m2, allow_incomplete=True)
    assert prov["official"] is False and prov["missing_cells"] == [wrong]  # only the wrong cell
    board = {e["agent"]: e for e in prov["leaderboard"]}
    assert (board[BAD]["n"], board[BAD]["pass_rate"]) == (REPS, 0.0)
    unrelated_runs = campaign["decoy_runs"] - _run_ids_of(campaign, "superseded")
    assert not _fresh_run_ids(prov) & unrelated_runs
    assert {r["cell"]: r["status"] for r in analysis.phase_a_comparison(m2)["cells"]}[wrong] == INSUFFICIENT


def _run_ids_of(campaign, which: str) -> set[int]:
    conn = app_db.connect_readonly(campaign["manifest"].db_path())
    try:
        return _run_ids(conn, campaign[which])
    finally:
        conn.close()


def test_real_manifest_before_launch_reports_nothing_fresh():
    m = Manifest.load()
    if m.ledger_path().exists() or m.db_path().exists():
        pytest.skip("the real campaign has started in this checkout")
    phase_a = analysis.phase_a_comparison(m)
    assert phase_a["summary"]["cells"] == 51 and phase_a["summary"]["prior_pass_cells"] == 51
    assert phase_a["summary"]["by_status"][INSUFFICIENT] == 51
    assert all(r["task_version_changed"] for r in phase_a["cells"])
    baseline = analysis.baseline_comparison(m)
    assert baseline["summary"] == {"cells": 144, "versions_differ": 108, "same_version": 36, "no_history": 0,
                                   "with_fresh_evidence": 0}
    assert analysis.official_baseline(m) is None


def test_historical_evidence_is_never_written(campaign):
    assert campaign["evidence_sha_before"] == EVIDENCE_SHA
    assert _sha(paths.EVIDENCE_DB) == EVIDENCE_SHA
    for stage in ("incomplete", "complete"):
        for name in ("phase_a", "baseline"):
            meta = campaign[stage][name]["historical_evidence"]
            assert meta["sha256"] == EVIDENCE_SHA and meta["matches_manifest"] is True


@pytest.mark.parametrize("change", ["uncheckpointed WAL", "main file changed"])
def test_the_comparisons_refuse_historical_evidence_that_is_not_the_frozen_file(campaign, tmp_path, monkeypatch,
                                                                                 capsys, change):
    # round 4: analysis._historical_store checks the guard hash (main file + any
    # non-empty WAL) against the frozen plan BEFORE reading, and then reads the
    # file immutably. Exercised on a SCRATCH COPY registered as the evidence DB.
    import shutil
    from pathlib import Path

    from afa_campaign import cli
    from afa_campaign.manifest import dump

    m = campaign["manifest"]
    stand_in = tmp_path / "evidence-stand-in.sqlite"
    shutil.copyfile(paths.EVIDENCE_DB, stand_in)
    monkeypatch.setattr(paths, "EVIDENCE_DB", stand_in)
    control = analysis.phase_a_comparison(m)  # a byte-identical copy is the frozen evidence
    assert control["historical_evidence"]["sha256"] == EVIDENCE_SHA
    assert control["historical_evidence"]["matches_manifest"] is True
    if change == "uncheckpointed WAL":
        Path(str(stand_in) + "-wal").write_bytes(b"\x00" * 64)
        fragment = "+uncheckpointed-wal:"
    else:
        with stand_in.open("r+b") as handle:  # one byte of the COPY
            handle.seek(200)
            byte = handle.read(1)
            handle.seek(200)
            handle.write(bytes([byte[0] ^ 0xFF]))
        fragment = "the frozen plan pins"
    for compare in (analysis.phase_a_comparison, analysis.baseline_comparison):
        with pytest.raises(analysis.AnalysisError, match="refusing to compare") as refused:
            compare(m)
        assert fragment in str(refused.value) and EVIDENCE_SHA in str(refused.value)
    manifest_file = tmp_path / "manifest.json"
    dump(m.data, manifest_file)
    for command in ("phase-a-report", "compare-baselines"):
        assert cli.main(["--manifest", str(manifest_file), command, "--out-dir", str(tmp_path / "out")]) == 3
        assert "refused:" in capsys.readouterr().err
    assert not (tmp_path / "out").exists() or not any((tmp_path / "out").iterdir())
    # a WAL changes what a reader would see without changing the main file's bytes
    assert (_sha(stand_in) == EVIDENCE_SHA) is (change == "uncheckpointed WAL")
