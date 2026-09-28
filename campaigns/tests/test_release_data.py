"""The web UI's benchmark release datasets (``python3 -m afa_campaign release-data``).

The committed datasets must be exactly what the generator derives from the
frozen evidence, the generator must refuse inconsistent evidence, and it must
never write anything but the web dataset.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from afa_campaign import cli, paths, release_data
from afa_campaign.release_data import ReleaseDataError

REPO = paths.REPO
MODERN = "phase0-modern-local-v1"
HISTORICAL = "historical-pre-phase0"
RESULTS = REPO / "campaigns" / MODERN / "results"
NOT_COMPARABLE = ("Historical results are not directly comparable with Modern Local v1. Eighteen of the 24 task "
                  "definitions changed and the historical runs predate the current evaluation-integrity system.")

# every file a release reads (and the evidence links it checks exist)
SOURCES = [
    "campaigns/releases",
    f"campaigns/{MODERN}",
    "campaigns/phase0-post-integrity/manifest.json",
    "integrity/pack-audit/remediation-manifest.json",
    "reports/runs.sqlite",
    "reports/qwen3.5-9b-evaluation-2026-09-17.md",
    "README.md",
    "docs/campaigns/PHASE0_MODERN_LOCAL_CAMPAIGN.md",
    "docs/release/PHASE0_MODERN_LOCAL_PROMOTION.md",
]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dataset(release_id: str) -> dict:
    return json.loads(release_data.output_path(release_id).read_text(encoding="utf-8"))


@pytest.fixture
def copy_root(tmp_path: Path) -> Path:
    for rel in SOURCES:
        source, target = REPO / rel, tmp_path / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_dir():
            shutil.copytree(source, target)
        else:
            shutil.copy2(source, target)
    return tmp_path


def rewrite(path: Path, edit) -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    edit(data)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def reseal(root: Path, rel: str) -> None:
    """Update a result file's SHA256SUMS row, so a test reaches the cross-checks behind the hash check."""
    sums = root / "campaigns" / MODERN / "results" / "SHA256SUMS"
    lines = []
    for line in sums.read_text(encoding="utf-8").splitlines():
        if line.endswith(f"committed {rel}"):
            line = f"{sha(root / 'campaigns' / MODERN / 'results' / rel)}  committed {rel}"
        lines.append(line)
    sums.write_text("\n".join(lines) + "\n", encoding="utf-8")


# --------------------------------------------------------------------------- #
# the committed datasets are exactly the generator's output
# --------------------------------------------------------------------------- #


def test_the_committed_datasets_match_their_sources():
    messages = release_data.generate(check=True)
    assert sorted(messages) == sorted(f"web/src/data/benchmark-releases/{r}.json matches its sources"
                                      for r in (MODERN, HISTORICAL))


def test_cli_release_data_check_passes(capsys):
    assert cli.main(["release-data", "--check"]) == 0
    assert "matches its sources" in capsys.readouterr().out


def test_every_release_definition_has_a_dataset_and_no_machine_paths():
    ids = [d["id"] for d in release_data.definitions()]
    assert sorted(ids) == sorted([MODERN, HISTORICAL])
    for release_id in ids:
        text = release_data.output_path(release_id).read_text(encoding="utf-8")
        assert "/Users/" not in text and "/private/" not in text and "/home/" not in text
        assert "generated_at" not in text  # deterministic: no timestamp of its own


# --------------------------------------------------------------------------- #
# Modern Local v1 carries the frozen campaign result
# --------------------------------------------------------------------------- #


def test_modern_local_v1_is_the_frozen_official_result():
    release = dataset(MODERN)
    board = json.loads((RESULTS / "outputs" / "modern-local-leaderboard.json").read_text())
    manifest = json.loads((REPO / "campaigns" / MODERN / "manifest.json").read_text())
    assert release["id"] == MODERN and release["campaign_id"] == MODERN == board["campaign_id"]
    assert release["status"] == "OFFICIAL" and release["ranked"] is True and release["comparable"] is True
    assert release["counts"] == {"models": 5, "models_ranked": 5, "tasks": 24, "repetitions": 5, "evaluations": 120,
                                 "runs": 600, "runs_per_model": 120}
    expected = [("gpt-oss:20b", 1, 96), ("devstral-small-2:24b", 2, 71), ("qwen3.5:9b", 3, 40),
                ("qwen3-coder:30b", 4, 18), ("qwen3.6:27b", 5, 11)]
    assert [(m["id"], m["rank"]["low"], m["totals"]["passes"]) for m in release["models"]] == expected
    assert [m["id"] for m in release["models"]] == [row["agent"] for row in board["leaderboard"]]
    pins = {r["model"]: r["expected_identity"]["digest"] for r in manifest["roster"]}
    for model, row in zip(release["models"], board["leaderboard"]):
        assert model["totals"]["runs"] == 120 and model["coverage"] == {"tasks_with_evidence": 24, "tasks_total": 24}
        assert (model["totals"]["pass_rate"], model["totals"]["wilson_low"], model["totals"]["wilson_high"]) == \
               (row["pass_rate"], row["wilson_low"], row["wilson_high"])
        assert model["identity"]["digest"] == pins[model["id"]]
        assert model["identity"]["digest_verified_cells"] == 24
        assert len(model["tasks"]) == 24 and sum(t["passes"] for t in model["tasks"]) == model["totals"]["passes"]
        assert [(t["task_id"], t["task_version"]) for t in model["tasks"]] == \
               [(t["task_id"], t["task_version"]) for t in manifest["tasks"]]
        assert [d["domain"] for d in model["domains"]] == release["domains"]
    assert [(t["task_id"], t["task_version"], t["task_digest"]) for t in release["task_pack"]] == \
           [(t["task_id"], t["task_version"], t["task_digest"]) for t in manifest["tasks"]]
    assert sum(t["version_changed_since_pre_phase0"] for t in release["task_pack"]) == 18


def test_modern_local_v1_integrity_counts_come_from_the_receipts():
    integrity = dataset(MODERN)["integrity"]
    assert integrity["complete"] is True and integrity["official"] is True and integrity["problems"] == []
    assert (integrity["accepted_runs"], integrity["planned_runs"]) == (600, 600)
    assert (integrity["accepted_evaluations"], integrity["planned_evaluations"]) == (120, 120)
    assert (integrity["models_complete"], integrity["models_total"], integrity["task_coverage_min"]) == (5, 5, 24)
    assert integrity["evidence_classes"] == {"real": 600, "synthetic": 0, "legacy": 0, "conflict": 0}
    for key in ("missing_runs", "missing_evaluations", "extra_runs", "untracked_evaluations", "disowned_evaluations",
                "superseded_entries", "voided_runs"):
        assert integrity[key] == 0, key
    assert integrity["backend_kind"] == "ollama"
    assert integrity["model_identity"] == {"cells_at_pinned_digest": 120, "cells_total": 120, "ollama_version": "0.31.1"}
    assert integrity["historical_evidence_unchanged"] is True
    # isolation is disclosed as not claimed, never as a verified property
    assert [(c["property"], c["status"]) for c in integrity["not_claimed"]] == [("Hidden-test isolation", "UNVERIFIABLE")]


def test_modern_local_v1_caveats_attach_to_the_right_models():
    release = dataset(MODERN)
    caveats = {c["id"]: c for c in release["caveats"]}
    coder = caveats["qwen3-coder-protocol-sensitivity"]
    assert coder["model"] == "qwen3-coder:30b" and coder["label"] == "Protocol sensitivity"
    assert coder["summary"] == ("Protocol sensitivity was demonstrated in a diagnosed case; the overall result reflects "
                                "both coding performance and compliance with AgentForge v1's output contract.")
    latency = caveats["qwen3.6-latency-constrained"]
    assert latency["model"] == "qwen3.6:27b" and latency["label"] == "Latency constrained"
    assert latency["summary"] == "Performance under the fixed local latency budget was heavily constrained."
    assert latency["verified_fields"] == ["timeouts", "request_timeout_hits", "runs"]
    assert caveats["historical-not-comparable"]["model"] is None
    assert caveats["historical-not-comparable"]["summary"] == NOT_COMPARABLE
    by_model = {m["id"]: m["caveat_ids"] for m in release["models"]}
    assert by_model == {"gpt-oss:20b": [], "devstral-small-2:24b": [], "qwen3.5:9b": [],
                        "qwen3-coder:30b": ["qwen3-coder-protocol-sensitivity"],
                        "qwen3.6:27b": ["qwen3.6-latency-constrained"]}
    qwen36 = next(m for m in release["models"] if m["id"] == "qwen3.6:27b")
    assert (qwen36["totals"]["timeouts"], qwen36["totals"]["request_timeout_hits"]) == (105, 83)


def test_modern_local_v1_links_to_existing_evidence():
    release = dataset(MODERN)
    for link in release["evidence_links"]:
        assert (REPO / link["path"]).exists(), link
    receipts = [link["path"] for link in release["evidence_links"] if link["kind"] == "receipt" and "model" in link]
    assert len(receipts) == 5
    assert release["repository"] == {"url": "https://github.com/thebunnyguy/agentforge-arena",
                                     "ref": "phase0-modern-local-v1",
                                     "commit": "92a3b0c6195d7bc9c5856ad0788e8cfd1fdaf230"}
    for source in release["sources"]:
        assert sha(REPO / source["path"]) == source["sha256"]


# --------------------------------------------------------------------------- #
# the pre-Phase-0 release shows only what the database holds
# --------------------------------------------------------------------------- #


def test_the_historical_release_is_unranked_counts_only():
    release = dataset(HISTORICAL)
    text = json.dumps(release)
    assert release["status"] == "HISTORICAL" and release["ranked"] is False and release["comparable"] is False
    assert release["comparability"] == NOT_COMPARABLE
    assert release["counts"]["runs"] == 720 and release["counts"]["models"] == 6
    assert "wilson" not in text and "pass_rate" not in text  # no manufactured statistics
    assert {m["id"] for m in release["models"]}.isdisjoint({"oracle", "noop"})
    assert all(m["rank"] is None and m["identity"]["digest"] is None for m in release["models"])
    assert release["integrity"] is None and release["environment"] is None
    assert release["methodology"]["task_versions_changed"] == 18
    assert sum(t["version_changed_since_pre_phase0"] for t in release["task_pack"]) == 18
    # an unranked record is listed in a neutral order (alphabetical by tag), never by result
    assert [m["id"] for m in release["models"]] == sorted(m["id"] for m in release["models"])
    qwen = next(m for m in release["models"] if m["id"] == "qwen3.5:9b")
    assert (qwen["totals"]["passes"], qwen["totals"]["timeouts"]) == (40, 36)
    assert qwen["generation"]["temperature"] == 0.6
    assert all(m["generation"] is None for m in release["models"] if m["id"] != "qwen3.5:9b")


# --------------------------------------------------------------------------- #
# inconsistent evidence is refused; frozen evidence is never written
# --------------------------------------------------------------------------- #


def test_generation_writes_only_the_web_datasets(copy_root: Path):
    before = {p: sha(p) for p in copy_root.rglob("*") if p.is_file()}
    release_data.generate(copy_root)
    after = {p: sha(p) for p in copy_root.rglob("*") if p.is_file()}
    changed = {p.relative_to(copy_root).as_posix() for p in set(after) if before.get(p) != after[p]}
    assert changed == {f"web/src/data/benchmark-releases/{r}.json" for r in (MODERN, HISTORICAL)}
    for rel in changed:  # and the copy's output is byte-identical to the committed dataset
        assert (copy_root / rel).read_bytes() == (REPO / rel).read_bytes()


def test_a_result_file_that_no_longer_matches_sha256sums_is_refused(copy_root: Path):
    rewrite(copy_root / "campaigns" / MODERN / "results" / "receipts" / "M2-gpt-oss-20b.json",
            lambda r: r["totals"].__setitem__("passed", 97))
    with pytest.raises(ReleaseDataError, match="M2-gpt-oss-20b.json does not match its SHA256SUMS hash"):
        release_data.build_release(json.loads((copy_root / "campaigns/releases" / f"{MODERN}.json").read_text()),
                                   copy_root)


def test_disagreeing_artifacts_are_refused_even_when_resealed(copy_root: Path):
    rel = "outputs/modern-local-leaderboard.json"
    rewrite(copy_root / "campaigns" / MODERN / "results" / rel,
            lambda b: b["leaderboard"][0].__setitem__("wilson_low", 0.70))
    reseal(copy_root, rel)
    with pytest.raises(ReleaseDataError, match="gpt-oss:20b pass rate / Wilson disagrees"):
        release_data.build_release(json.loads((copy_root / "campaigns/releases" / f"{MODERN}.json").read_text()),
                                   copy_root)


def test_a_caveat_number_the_evidence_contradicts_is_refused(copy_root: Path):
    definition = copy_root / "campaigns" / "releases" / f"{MODERN}.json"
    rewrite(definition, lambda d: d["caveats"][1]["checks"][0].__setitem__("equals", 104))
    with pytest.raises(ReleaseDataError, match="qwen3.6:27b timeouts is 105, the caveat says 104"):
        release_data.build_release(json.loads(definition.read_text()), copy_root)


def test_an_unofficial_or_incomplete_campaign_is_refused(copy_root: Path):
    rel = "outputs/completeness-receipt-all.json"
    rewrite(copy_root / "campaigns" / MODERN / "results" / rel,
            lambda c: (c.__setitem__("complete", False), c.__setitem__("problems", ["a missing cell"])))
    reseal(copy_root, rel)
    with pytest.raises(ReleaseDataError, match="the completeness receipt is not complete"):
        release_data.build_release(json.loads((copy_root / "campaigns/releases" / f"{MODERN}.json").read_text()),
                                   copy_root)


def test_the_historical_database_is_never_read_when_its_hash_is_wrong(copy_root: Path):
    db = copy_root / "reports" / "runs.sqlite"
    db.write_bytes(db.read_bytes() + b"\0")
    with pytest.raises(ReleaseDataError, match="is not the recorded 42b6dad8"):
        release_data.build_release(json.loads((copy_root / "campaigns/releases" / f"{HISTORICAL}.json").read_text()),
                                   copy_root)


def test_an_unknown_status_is_refused(copy_root: Path):
    definition = copy_root / "campaigns" / "releases" / f"{MODERN}.json"
    rewrite(definition, lambda d: d.__setitem__("status", "BEST"))
    with pytest.raises(ReleaseDataError, match="status must be one of"):
        release_data.build_release(json.loads(definition.read_text()), copy_root)


def test_a_stale_committed_dataset_is_drift(copy_root: Path):
    release_data.generate(copy_root)
    target = copy_root / "web" / "src" / "data" / "benchmark-releases" / f"{MODERN}.json"
    rewrite(target, lambda d: d["models"][0]["totals"].__setitem__("passes", 95))
    with pytest.raises(ReleaseDataError, match="out of date with their sources"):
        release_data.generate(copy_root, check=True)


def test_the_frozen_results_still_verify_against_sha256sums():
    rows = [line.split(None, 2) for line in (RESULTS / "SHA256SUMS").read_text().splitlines()
            if line.strip() and not line.startswith("#")]
    committed = [(digest, rel) for digest, kind, rel in rows if kind == "committed"]
    assert len(committed) == 20
    for digest, rel in committed:
        assert sha(RESULTS / rel) == digest, rel


def _modern_definition(root: Path) -> dict:
    return json.loads((root / "campaigns" / "releases" / f"{MODERN}.json").read_text())


def test_a_rate_that_disagrees_with_its_counts_is_refused(copy_root: Path):
    rel = "outputs/modern-local-leaderboard.json"
    board = copy_root / "campaigns" / MODERN / "results" / rel
    rewrite(board, lambda b: b["task_matrix"][0]["cells"]["gpt-oss:20b"]["aggregate"].__setitem__("pass_rate", 0.6))
    reseal(copy_root, rel)
    with pytest.raises(ReleaseDataError, match=r"gpt-oss:20b\|escape-html: pass rate 0.6 disagrees with 5/5"):
        release_data.build_release(_modern_definition(copy_root), copy_root)


def test_a_leaderboard_out_of_the_kernel_order_is_refused(copy_root: Path):
    rel = "outputs/modern-local-leaderboard.json"
    board = copy_root / "campaigns" / MODERN / "results" / rel

    def swap(b):
        rows = b["leaderboard"]
        rows[0], rows[1] = rows[1], rows[0]
    rewrite(board, swap)
    reseal(copy_root, rel)
    with pytest.raises(ReleaseDataError, match="not the kernel's Wilson-lower-bound order"):
        release_data.build_release(_modern_definition(copy_root), copy_root)


def test_status_and_source_kind_must_agree(copy_root: Path):
    historical = copy_root / "campaigns" / "releases" / f"{HISTORICAL}.json"
    rewrite(historical, lambda d: d.__setitem__("status", "OFFICIAL"))
    with pytest.raises(ReleaseDataError, match="historical-db release must have status HISTORICAL"):
        release_data.build_release(json.loads(historical.read_text()), copy_root)
    modern = copy_root / "campaigns" / "releases" / f"{MODERN}.json"
    rewrite(modern, lambda d: d.__setitem__("status", "HISTORICAL"))
    with pytest.raises(ReleaseDataError, match="historical-db release must have status HISTORICAL"):
        release_data.build_release(json.loads(modern.read_text()), copy_root)


def test_released_at_must_be_an_iso_date(copy_root: Path):
    modern = copy_root / "campaigns" / "releases" / f"{MODERN}.json"
    rewrite(modern, lambda d: d.__setitem__("released_at", "Sep 28, 2026"))
    with pytest.raises(ReleaseDataError, match="released_at must be an ISO date"):
        release_data.build_release(json.loads(modern.read_text()), copy_root)


def test_unknown_release_ids_and_orphan_datasets_are_refused(copy_root: Path):
    release_data.generate(copy_root)
    with pytest.raises(ReleaseDataError, match="unknown release id"):
        release_data.generate(copy_root, check=True, release_ids=["no-such-release"])
    orphan = copy_root / "web" / "src" / "data" / "benchmark-releases" / "stray-release.json"
    orphan.write_text("{}", encoding="utf-8")
    with pytest.raises(ReleaseDataError, match="without a release definition: web/src/data/benchmark-releases/stray"):
        release_data.generate(copy_root, check=True)


def test_a_malformed_definition_is_a_refusal_not_a_crash(copy_root: Path):
    modern = copy_root / "campaigns" / "releases" / f"{MODERN}.json"
    rewrite(modern, lambda d: d["source"].pop("leaderboard"))
    with pytest.raises(ReleaseDataError, match="malformed definition or evidence"):
        release_data.build_release(json.loads(modern.read_text()), copy_root)


def _working_git() -> str | None:
    """A git that runs here (an Intel Homebrew git on Apple silicon does not) and knows the release tag."""
    for candidate in ("git", "/usr/bin/git"):
        try:
            probe = subprocess.run([candidate, "-C", str(REPO), "rev-parse", "--verify", "-q",
                                    "phase0-modern-local-v1^{commit}"], capture_output=True, text=True)
        except OSError:
            continue
        if probe.returncode == 0:
            return candidate
    return None


def test_the_evidence_is_the_evidence_at_the_frozen_tag():
    """Every source a release was generated from (apart from its own definition) is byte-identical to that file
    at the git ref its evidence links point at, so the links show exactly what produced the numbers."""
    git = _working_git()
    if git is None:
        pytest.skip("no working git, or the release tag is not available in this checkout")
    for release_id in (MODERN, HISTORICAL):
        release = dataset(release_id)
        ref, commit = release["repository"]["ref"], release["repository"]["commit"]
        resolved = subprocess.run([git, "-C", str(REPO), "rev-parse", f"{ref}^{{commit}}"], capture_output=True, text=True)
        assert resolved.stdout.strip() == commit
        for source in release["sources"]:
            if source["path"].startswith("campaigns/releases/"):
                continue
            blob = subprocess.run([git, "-C", str(REPO), "show", f"{ref}:{source['path']}"], capture_output=True)
            assert blob.returncode == 0, source["path"]
            assert hashlib.sha256(blob.stdout).hexdigest() == source["sha256"], source["path"]
        for link in release["evidence_links"]:  # every link the UI renders resolves at the ref it points at
            exists = subprocess.run([git, "-C", str(REPO), "cat-file", "-e", f"{ref}:{link['path']}"], capture_output=True)
            assert exists.returncode == 0, link["path"]


def test_caveat_prose_must_state_the_numbers_it_is_checked_against(copy_root: Path):
    modern = copy_root / "campaigns" / "releases" / f"{MODERN}.json"
    rewrite(modern, lambda d: d["caveats"][1]["points"].__setitem__(0, "104 of 120 runs were classified as timeouts."))
    with pytest.raises(ReleaseDataError, match="does not state the checked timeouts 105"):
        release_data.build_release(json.loads(modern.read_text()), copy_root)
    rewrite(modern, lambda d: (d["caveats"][1]["points"].__setitem__(0, "105 of 120 runs were classified as timeouts."),
                               d["caveats"][0]["points"].__setitem__(0, "95 of 120 campaign runs produced no applied edit.")))
    with pytest.raises(ReleaseDataError, match="does not state the documented 96 of 120"):
        release_data.build_release(json.loads(modern.read_text()), copy_root)


def test_an_invalid_definition_file_or_a_missing_git_ref_is_refused(copy_root: Path):
    modern = copy_root / "campaigns" / "releases" / f"{MODERN}.json"
    rewrite(modern, lambda d: d["git"].pop("tag"))
    with pytest.raises(ReleaseDataError, match="definition needs git.tag"):
        release_data.build_release(json.loads(modern.read_text()), copy_root)
    modern.write_text("{ not json", encoding="utf-8")
    with pytest.raises(ReleaseDataError, match=f"{MODERN}.json: not valid JSON"):
        release_data.generate(copy_root, check=True)


def test_a_historical_release_is_dated_by_its_last_recorded_run(copy_root: Path):
    historical = copy_root / "campaigns" / "releases" / f"{HISTORICAL}.json"
    rewrite(historical, lambda d: d.__setitem__("released_at", "2026-09-18"))
    with pytest.raises(ReleaseDataError, match="released_at vs the last recorded run"):
        release_data.build_release(json.loads(historical.read_text()), copy_root)
