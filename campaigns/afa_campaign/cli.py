"""``python3 -m afa_campaign <command>`` - campaign operator commands.

Preparation     build-manifest, build-modern-manifest, derive, inventory, init-db, preflight, plan
Execution       launch (requires --confirm <campaign_id>), resume, supersede, disown
Model lifecycle storage-inventory, pull-model, smoke, model-receipt, remove-model, classify-model
                (sequential-local campaigns: one model at a time under limited storage)
Observation     status, validate
Analysis        phase-a-report, compare-baselines, baseline-report

Every command takes ``--manifest`` (default: $AFA_CAMPAIGN_MANIFEST, else the
phase0-post-integrity manifest). Phases are the manifest's own (A/B, or one per
model: M1, M2, ...).
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys

from . import paths


def _manifest(args):
    from .manifest import Manifest

    return Manifest.load(args.manifest)


def _client(args, manifest):
    from .api import AgentForgeApi

    return AgentForgeApi(args.api or manifest.api_url)


def _print_json(data) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False))


def cmd_build_manifest(args) -> int:
    from .manifest import build_manifest, dump

    target = paths.resolve(args.out)
    if target.exists() and not args.force:
        print(f"refusing to overwrite {target} (use --force before any launch; a launched plan is frozen)")
        return 2
    created = args.created_at or _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    data = build_manifest(
        created_at=created,
        runtime_tag=args.runtime_tag,
        runtime_commit=args.runtime_commit,
        repetitions=args.repetitions,
        temperature=args.temperature,
        base_seed=args.base_seed,
        request_timeout_s=args.request_timeout_s,
        backend_base_url=args.backend_url,
    )
    dump(data, target)
    print(f"wrote {paths.display(target)}: {json.dumps(data['expected'])}")
    return 0


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def cmd_build_modern_manifest(args) -> int:
    from .manifest import build_modern_manifest, dump

    target = paths.resolve(args.out)
    if target.exists() and not args.force:
        print(f"refusing to overwrite {target} (use --force before any launch; a launched plan is frozen)")
        return 2
    data = build_modern_manifest(created_at=args.created_at or _now(), runtime_tag=args.runtime_tag,
                                 runtime_commit=args.runtime_commit)
    dump(data, target)
    print(f"wrote {paths.display(target)}: {json.dumps(data['expected'])}")
    return 0


def _log(message: str) -> None:
    print(message, flush=True)


def cmd_storage_inventory(args) -> int:
    from .lifecycle import GIB, storage_inventory

    inventory, target = storage_inventory(_manifest(args), args.label)
    disk = inventory["disk"]
    print(f"disk: {disk['free_bytes'] / GIB:.1f} GiB free of {disk['total_bytes'] / GIB:.0f} GiB")
    print(f"Ollama {inventory['ollama']['version']} models ({inventory['ollama']['total_model_bytes'] / GIB:.1f} GiB):")
    for m in inventory["ollama"]["models"]:
        tag = f"target {m['campaign_target']}" if m["campaign_target"] else ("MLX" if m["mlx"] else "")
        print(f"  {m['name']:32s} {(m['size_bytes'] or 0) / GIB:6.1f} GiB  {m['quantization'] or m['format']}  {tag}")
    for w in inventory["other_model_weights"]:
        print(f"  [{w['runtime']}] {w['model']:40s} {w['bytes'] / GIB:6.1f} GiB  {w['kind']}")
    print(f"wrote {paths.display(target)}")
    return 0


def cmd_pull_model(args) -> int:
    from .lifecycle import pull_model

    manifest = _manifest(args)
    record = pull_model(manifest, _phase(manifest, args.phase, allow_all=False), client=_client(args, manifest), log=_log)
    print(json.dumps({k: v for k, v in record.items() if k != "at"}))
    return 0


def cmd_remove_model(args) -> int:
    from .lifecycle import remove_model

    manifest = _manifest(args)
    if args.confirm != manifest.campaign_id:
        print(f"remove-model deletes model weights. Re-run with --confirm {manifest.campaign_id} to proceed.")
        return 2
    record = remove_model(manifest, args.model, args.reason, client=_client(args, manifest), log=_log)
    return 0 if record["outcome"] == "removed" else 1


def cmd_remove_weights(args) -> int:
    from .lifecycle import remove_weights

    manifest = _manifest(args)
    if args.confirm != manifest.campaign_id:
        print(f"remove-weights deletes model files. Re-run with --confirm {manifest.campaign_id} to proceed.")
        return 2
    record = remove_weights(manifest, args.path, args.reason, log=_log)
    return 0 if record["outcome"] == "removed" else 1


def cmd_classify_model(args) -> int:
    from .lifecycle import classify_model

    manifest = _manifest(args)
    record = classify_model(manifest, _phase(manifest, args.phase, allow_all=False), args.status, args.reason,
                            args.evidence, after_results=args.after_results)
    print(f"classified {record['model']} ({record['phase']}) {record['status']}: {record['reason']}")
    return 0


def cmd_smoke(args) -> int:
    from .lifecycle import run_smoke

    manifest = _manifest(args)
    if args.confirm != manifest.campaign_id:
        print(f"smoke runs REAL model evaluations. Re-run with --confirm {manifest.campaign_id} to proceed.")
        return 2
    record = run_smoke(manifest, _phase(manifest, args.phase, allow_all=False), port=args.port, log=_log)
    print(json.dumps({k: record[k] for k in ("phase", "model", "operational_ok", "outcome", "failure", "passed",
                                              "valid", "scratch")}, indent=2))
    return 0 if record["operational_ok"] else 1


def cmd_model_receipt(args) -> int:
    from .lifecycle import model_receipt

    manifest = _manifest(args)
    result, target = model_receipt(manifest, _phase(manifest, args.phase, allow_all=False), reissue=args.reissue)
    print(f"model receipt {paths.display(target)}: {result['accepted_runs']}/{result['expected_runs']} accepted, "
          f"{result['totals']['passed']}/{result['totals']['valid']} passed")
    return 0


def cmd_derive(args) -> int:
    from .manifest import derive_subset, dump

    base = _manifest(args)
    data = derive_subset(
        base.data,
        campaign_id=args.campaign_id,
        models=[m for m in args.models.split(",") if m],
        task_ids=[t for t in args.tasks.split(",") if t],
        repetitions=args.repetitions,
        campaign_db=args.db,
        runtime_dir=args.runtime_dir,
        api_url=args.api_url,
        purpose=args.purpose,
    )
    dump(data, args.out)
    print(f"wrote {args.out}: {json.dumps(data['expected'])}")
    return 0


def cmd_inventory(args) -> int:
    from . import ollama

    manifest = _manifest(args)
    snap = ollama.inventory(manifest.backend["base_url"], manifest.models)
    if args.out:
        target = paths.resolve(args.out)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(snap, indent=2) + "\n")
        print(f"wrote {paths.display(target)}")
    print(f"Ollama {snap['ollama_version']} at {snap['base_url']}")
    for model, entry in snap["models"].items():
        if entry["present"]:
            print(f"  present  {model:22s} digest {entry['digest']}  size {entry['size']}  "
                  f"modified {entry['modified_at']}")
        else:
            print(f"  MISSING  {model}")
    return 1 if snap["missing"] else 0


def cmd_init_db(args) -> int:
    from .launcher import init_db

    target = init_db(_manifest(args))
    print(f"initialised clean campaign database {target}")
    return 0


def cmd_preflight(args) -> int:
    from .launcher import preflight
    from .ledger import Ledger, LedgerError

    manifest = _manifest(args)
    ledger_problem = None
    ledger = None
    if manifest.ledger_path().exists():
        try:
            ledger = Ledger.load(manifest.ledger_path(), campaign_id=manifest.campaign_id,
                                 manifest_sha256=manifest.sha256)
        except LedgerError as exc:
            ledger_problem = f"ledger: {exc}"
    pf = preflight(manifest, _client(args, manifest), ledger=ledger, check_code=not args.no_code_check,
                   phase=_phase(manifest, args.phase, allow_all=False) if args.phase else None)
    if ledger_problem:
        pf.problems.insert(0, ledger_problem)
    if args.json:
        _print_json({"ok": pf.ok, "problems": pf.problems, "warnings": pf.warnings, "facts": pf.facts})
    else:
        for problem in pf.problems:
            print(f"PROBLEM: {problem}")
        for warning in pf.warnings:
            print(f"warning: {warning}")
        print("preflight OK" if pf.ok else "preflight FAILED")
    return 0 if pf.ok else 1


def _phase(manifest, phase: str, *, allow_all: bool = True) -> str:
    from .manifest import ManifestError

    allowed = manifest.phases + (["all"] if allow_all else [])
    if phase not in allowed:
        raise ManifestError(f"unknown phase {phase!r}; this plan's phases are {allowed}")
    return phase


def cmd_plan(args) -> int:
    manifest = _manifest(args)
    cells = manifest.cells(_phase(manifest, args.phase))
    for cell in cells:
        meta = manifest.cell_meta(cell.key)
        if manifest.is_sequential:
            task = manifest.task_by_id[cell.task_id]
            print(f"{cell.phase}  {cell.key:45s} v{task['task_version']} {task['task_digest'][:19]}...")
            continue
        print(f"{cell.phase}  {cell.key:45s} historical {meta['historical_passes']}/"
              f"{meta['historical_valid']} at v{meta['historical_version']}")
    print(f"{len(cells)} cells x {manifest.repetitions} = {len(cells) * manifest.repetitions} runs")
    return 0


def cmd_launch(args) -> int:
    from .launcher import CampaignStop, Launcher

    manifest = _manifest(args)
    if args.confirm != manifest.campaign_id:
        print("launch runs REAL model evaluations. Re-run with "
              f"--confirm {manifest.campaign_id} to proceed.")
        return 2
    launcher = Launcher(manifest, _client(args, manifest), poll_s=args.poll, warmup=not args.no_warmup)
    try:
        result = launcher.run(_phase(manifest, args.phase, allow_all=False), max_evaluations=args.max_evaluations,
                              check_code=not args.no_code_check)
    except CampaignStop as exc:
        print(str(exc), file=sys.stderr)
        return 3
    print(json.dumps(result))
    return 0


def _operator(action):
    """Run an operator action; refusals print a message instead of a traceback."""
    from .launcher import CampaignStop
    from .ledger import LedgerError

    try:
        return action()
    except (CampaignStop, LedgerError) as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return None


def cmd_resume(args) -> int:
    from .launcher import resume_cell

    manifest = _manifest(args)
    entry = _operator(lambda: resume_cell(manifest, _client(args, manifest), args.cell,
                                          check_code=not args.no_code_check))
    if entry is None:
        return 3
    print(f"resumed {entry['cell']} evaluation {entry['evaluation_id']} (same id); run launch to wait for it")
    return 0


def cmd_supersede(args) -> int:
    from .launcher import supersede_cell

    entry = _operator(lambda: supersede_cell(_manifest(args), args.cell, args.reason))
    if entry is None:
        return 3
    print(f"superseded {entry['cell']} evaluation {entry['evaluation_id']}: {entry['superseded_reason']}")
    return 0


def cmd_disown(args) -> int:
    from .launcher import disown_evaluation

    record = _operator(lambda: disown_evaluation(_manifest(args), args.evaluation, args.reason))
    if record is None:
        return 3
    print(f"disowned {record['evaluation_id']}: {record['reason']} (never campaign evidence)")
    return 0


def cmd_status(args) -> int:
    from .status import campaign_status, render

    manifest = _manifest(args)
    status = campaign_status(manifest, _phase(manifest, args.phase))
    if args.json:
        _print_json(status)
    else:
        print(render(status))
    return 0


def cmd_validate(args) -> int:
    from .validate import render, validate_campaign, write_receipt

    manifest = _manifest(args)
    receipt = validate_campaign(manifest, phase=_phase(manifest, args.phase))
    target = args.receipt or str(manifest.outputs_dir() / f"completeness-receipt-{args.phase}.json")
    written = write_receipt(receipt, target)
    if args.json:
        _print_json(receipt)
    else:
        print(render(receipt))
        print(f"receipt: {paths.display(written)}")
    return 0 if receipt["complete"] else 1


def _write(result: dict, markdown: str, out_dir, stem: str) -> None:
    target = paths.resolve(out_dir)
    target.mkdir(parents=True, exist_ok=True)
    (target / f"{stem}.json").write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    (target / f"{stem}.md").write_text(markdown)
    print(f"wrote {paths.display(target / (stem + '.json'))} and .md")


def cmd_phase_a_report(args) -> int:
    from . import analysis

    manifest = _manifest(args)
    result = analysis.phase_a_comparison(manifest)
    _write(result, analysis.render_phase_a(result), args.out_dir or manifest.outputs_dir(), "phase-a-comparison")
    return 0


def cmd_compare_baselines(args) -> int:
    from . import analysis

    manifest = _manifest(args)
    result = analysis.baseline_comparison(manifest)
    _write(result, analysis.render_baseline_comparison(result), args.out_dir or manifest.outputs_dir(),
           "pre-vs-post-phase0-comparison")
    return 0


def cmd_baseline_report(args) -> int:
    from . import analysis

    manifest = _manifest(args)
    result = analysis.official_baseline(manifest, allow_incomplete=args.allow_incomplete)
    if result is None:
        print("the campaign is not complete; the OFFICIAL baseline is not produced "
              "(use --allow-incomplete for a clearly-labelled PROVISIONAL report)")
        return 1
    stem = "modern-local-leaderboard" if manifest.is_sequential else "post-phase0-baseline"
    _write(result, analysis.render_official_baseline(result), args.out_dir or manifest.outputs_dir(),
           stem if result["official"] else f"{stem}-PROVISIONAL")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="afa_campaign", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--manifest", default=os.environ.get("AFA_CAMPAIGN_MANIFEST") or str(paths.DEFAULT_MANIFEST))
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("build-manifest", help="freeze the plan from the task pack and evidence")
    p.add_argument("--out", default=str(paths.DEFAULT_MANIFEST))
    p.add_argument("--force", action="store_true")
    p.add_argument("--created-at")
    p.add_argument("--runtime-tag", required=True)
    p.add_argument("--runtime-commit", required=True)
    p.add_argument("--repetitions", type=int, default=5)
    p.add_argument("--temperature", type=float, default=0.8)
    p.add_argument("--base-seed", type=int, default=42)
    p.add_argument("--request-timeout-s", type=int, default=180)
    p.add_argument("--backend-url", default="http://127.0.0.1:11434")
    p.set_defaults(func=cmd_build_manifest)

    p = sub.add_parser("build-modern-manifest", help="freeze the sequential-local plan (one model per phase)")
    p.add_argument("--out", default=str(paths.MODERN_MANIFEST))
    p.add_argument("--force", action="store_true")
    p.add_argument("--created-at")
    p.add_argument("--runtime-tag", required=True)
    p.add_argument("--runtime-commit", required=True)
    p.set_defaults(func=cmd_build_modern_manifest)

    p = sub.add_parser("storage-inventory", help="disk space, Ollama models and other local model weights")
    p.add_argument("--label", required=True)
    p.set_defaults(func=cmd_storage_inventory)

    p = sub.add_parser("pull-model", help="install ONLY a phase's target (or reuse it); digest must match the pin")
    p.add_argument("--phase", required=True)
    p.add_argument("--api")
    p.set_defaults(func=cmd_pull_model)

    p = sub.add_parser("remove-model", help="remove Ollama model weights, recorded first (evidence is never touched)")
    p.add_argument("--model", required=True)
    p.add_argument("--reason", required=True)
    p.add_argument("--confirm", default="")
    p.add_argument("--api")
    p.set_defaults(func=cmd_remove_model)

    p = sub.add_parser("remove-weights", help="remove ONE Hugging Face / LM Studio model directory (recorded first)")
    p.add_argument("--path", required=True)
    p.add_argument("--reason", required=True)
    p.add_argument("--confirm", default="")
    p.set_defaults(func=cmd_remove_weights)

    p = sub.add_parser("classify-model", help="record a model as not benchmarked locally (reason + evidence)")
    p.add_argument("--phase", required=True)
    p.add_argument("--status", required=True, choices=["LOCAL_RESOURCE_LIMIT", "LOCAL_RUNTIME_UNSUPPORTED",
                                                        "NOT_BENCHMARKED"])
    p.add_argument("--reason", required=True)
    p.add_argument("--evidence", required=True)
    p.add_argument("--after-results", action="store_true",
                   help="classify a model that already has accepted cells (disclosed in the leaderboard)")
    p.set_defaults(func=cmd_classify_model)

    p = sub.add_parser("smoke", help="4 tasks x 1 repetition in a SCRATCH database (never campaign evidence)")
    p.add_argument("--phase", required=True)
    p.add_argument("--confirm", default="")
    p.add_argument("--port", type=int, default=8792)
    p.set_defaults(func=cmd_smoke)

    p = sub.add_parser("model-receipt", help="freeze a model's validated 120-run receipt")
    p.add_argument("--phase", required=True)
    p.add_argument("--reissue", action="store_true", help="issue a new version; the previous one is kept")
    p.set_defaults(func=cmd_model_receipt)

    p = sub.add_parser("derive", help="derive a smaller campaign (dry runs) with identical pins")
    p.add_argument("--out", required=True)
    p.add_argument("--campaign-id", required=True)
    p.add_argument("--models", required=True)
    p.add_argument("--tasks", required=True)
    p.add_argument("--repetitions", type=int, default=1)
    p.add_argument("--db", required=True)
    p.add_argument("--runtime-dir", required=True)
    p.add_argument("--api-url")
    p.add_argument("--purpose", default="dry run of the campaign tooling (NOT campaign evidence)")
    p.set_defaults(func=cmd_derive)

    p = sub.add_parser("inventory", help="snapshot the Ollama model inventory for the roster")
    p.add_argument("--out")
    p.set_defaults(func=cmd_inventory)

    p = sub.add_parser("init-db", help="create the CLEAN campaign database")
    p.set_defaults(func=cmd_init_db)

    for name, func in (("preflight", cmd_preflight),):
        p = sub.add_parser(name, help="check every launch precondition without launching")
        p.add_argument("--phase", help="the model phase to check (sequential-local plans)")
        p.add_argument("--api")
        p.add_argument("--no-code-check", action="store_true")
        p.add_argument("--json", action="store_true")
        p.set_defaults(func=func)

    p = sub.add_parser("plan", help="print the cells of a phase")
    p.add_argument("--phase", default="all")
    p.set_defaults(func=cmd_plan)

    p = sub.add_parser("launch", help="execute a phase (resumable; one evaluation at a time)")
    p.add_argument("--phase", required=True)
    p.add_argument("--confirm", default="")
    p.add_argument("--api")
    p.add_argument("--max-evaluations", type=int)
    p.add_argument("--poll", type=float, default=5.0)
    p.add_argument("--no-warmup", action="store_true",
                   help="ONLY for rehearsals; recorded, and the cells it submits are not official evidence")
    p.add_argument("--no-code-check", action="store_true",
                   help="ONLY for rehearsals; recorded, and the cells it submits, resumes or finalizes are not "
                        "official evidence")
    p.set_defaults(func=cmd_launch)

    p = sub.add_parser("resume", help="same-id resume of a failed/canceled campaign evaluation")
    p.add_argument("--cell", required=True)
    p.add_argument("--api")
    p.add_argument("--no-code-check", action="store_true",
                   help="ONLY for rehearsals; recorded, and the resumed cell is not official evidence")
    p.set_defaults(func=cmd_resume)

    p = sub.add_parser("supersede", help="replace a halted cell's evaluation (reason required)")
    p.add_argument("--cell", required=True)
    p.add_argument("--reason", required=True)
    p.set_defaults(func=cmd_supersede)

    p = sub.add_parser("disown", help="record an untracked campaign-named evaluation as NOT evidence (reason required)")
    p.add_argument("--evaluation", required=True)
    p.add_argument("--reason", required=True)
    p.set_defaults(func=cmd_disown)

    p = sub.add_parser("status", help="progress monitor")
    p.add_argument("--phase", default="all")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("validate", help="completeness validator; writes a receipt")
    p.add_argument("--phase", default="all")
    p.add_argument("--receipt")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_validate)

    p = sub.add_parser("phase-a-report", help="Phase-A early-warning comparison vs historical evidence")
    p.add_argument("--out-dir")
    p.set_defaults(func=cmd_phase_a_report)

    p = sub.add_parser("compare-baselines", help="pre-Phase-0 vs post-Phase-0 per cell")
    p.add_argument("--out-dir")
    p.set_defaults(func=cmd_compare_baselines)

    p = sub.add_parser("baseline-report", help="official post-Phase-0 leaderboard, matrix, domains, provenance")
    p.add_argument("--out-dir")
    p.add_argument("--allow-incomplete", action="store_true")
    p.set_defaults(func=cmd_baseline_report)
    return parser


def _analysis_error():
    from .analysis import AnalysisError

    return AnalysisError


def main(argv: list[str] | None = None) -> int:
    import urllib.error

    from .launcher import CampaignStop
    from .ledger import LedgerError
    from .manifest import ManifestError
    from .ollama import OllamaError

    args = build_parser().parse_args(argv)
    try:
        return int(args.func(args) or 0)
    except (CampaignStop, LedgerError, ManifestError, FileNotFoundError, OllamaError, urllib.error.URLError,
            _analysis_error()) as exc:
        # Refusals are expected operator-facing outcomes, not crashes.
        print(f"refused: {exc}", file=sys.stderr)
        return 3
