"""Developer-facing integrity CLI (mission §18).

No CLI framework (click/typer/argparse app) exists anywhere else in this repo
— dev tooling is a standalone script under examples/ doing sys.path injection
then positional-argv parsing (see examples/diagnose_task.py, eval_pack.py).
Positional argv can't express --quick/--full/--json/--markdown cleanly, so
this module uses stdlib argparse (still zero third-party dependencies) and is
invoked either as `python -m afa_integrity ...` or via the thin
examples/benchmark_audit.py launcher that matches house style.

    python -m afa_integrity audit fix-binary-search --full
    python -m afa_integrity audit --all --quick --json-dir reports/integrity
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from afa_runner.task import load_task

from .audit import run_audit
from .model import AuditMode
from .pack import audit_pack
from .report import (
    pack_summary_to_json,
    pack_summary_to_markdown,
    report_to_json,
    report_to_markdown,
)

EXIT_OK = 0
EXIT_NEEDS_REVIEW = 1
EXIT_INVALID = 2


def _status_exit_code(status_value: str) -> int:
    if status_value == "invalid":
        return EXIT_INVALID
    if status_value in ("needs_review", "unverifiable"):
        return EXIT_NEEDS_REVIEW
    return EXIT_OK


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="afa_integrity",
        description="AgentForge Benchmark Integrity Engine: validate that a "
        "task's oracle (reference solution + hidden tests + grader) can be "
        "trusted, separate from any agent's score on it.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    audit_p = sub.add_parser("audit", help="Audit one task or the whole pack.")
    target = audit_p.add_mutually_exclusive_group(required=True)
    target.add_argument("task_id", nargs="?", help="Task id (directory name under tasks/).")
    target.add_argument("--all", action="store_true", help="Audit every task in tasks/manifest.json.")

    mode_group = audit_p.add_mutually_exclusive_group()
    mode_group.add_argument("--quick", action="store_true", help="QUICK mode (default).")
    mode_group.add_argument("--full", action="store_true", help="FULL mode: adds mutation testing, a wider determinism sample, and the isolation probe.")

    audit_p.add_argument("--mutation", action="store_true", help="Force mutation testing even in QUICK mode.")
    audit_p.add_argument("--max-mutants", type=int, default=60, help="Cap on generated mutants per task (default 60).")
    audit_p.add_argument("--workers", type=int, default=4, help="Thread pool size for --all (default 4).")
    audit_p.add_argument("--tasks-root", default="tasks", help="Path to the tasks/ directory (default: tasks).")
    audit_p.add_argument("--json", metavar="PATH", help="Write the JSON report to PATH (single task) or PATH is used as-is for --all's pack summary.")
    audit_p.add_argument("--markdown", metavar="PATH", help="Write the Markdown report to PATH (single task) or the pack summary for --all.")
    audit_p.add_argument("--json-dir", metavar="DIR", help="With --all: write one JSON report per task into DIR.")
    audit_p.add_argument("--markdown-dir", metavar="DIR", help="With --all: write one Markdown report per task into DIR.")

    return parser


def _write(path_str: str | None, content: str) -> None:
    if not path_str:
        return
    path = Path(path_str)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    print(f"wrote {path}  ({len(content)} bytes)")


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command != "audit":
        parser.print_help()
        return EXIT_OK

    mode = AuditMode.FULL if args.full else AuditMode.QUICK

    if args.all:
        summary = audit_pack(
            tasks_root=args.tasks_root,
            mode=mode,
            workers=args.workers,
            force_mutation=args.mutation,
            max_mutants=args.max_mutants,
        )
        md = pack_summary_to_markdown(summary)
        print(md)
        _write(args.json, pack_summary_to_json(summary))
        _write(args.markdown, md)
        if args.json_dir:
            for r in summary.reports:
                _write(str(Path(args.json_dir) / f"{r.task_id}.json"), report_to_json(r))
        if args.markdown_dir:
            for r in summary.reports:
                _write(str(Path(args.markdown_dir) / f"{r.task_id}.md"), report_to_markdown(r))
        worst = max((r.status.value for r in summary.reports), key=_status_exit_code, default="healthy")
        exit_code = _status_exit_code(worst)
        if summary.failures:
            # A task that couldn't be audited at all is at least as bad as
            # an INVALID one — never let it silently pass through as if
            # every task's status was healthy just because none of the
            # *successfully audited* tasks were invalid.
            exit_code = max(exit_code, EXIT_INVALID)
        return exit_code

    task = load_task(Path(args.tasks_root) / args.task_id)
    report = run_audit(
        task,
        mode=mode,
        force_mutation=args.mutation,
        max_mutants=args.max_mutants,
    )
    print(report_to_markdown(report))
    _write(args.json, report_to_json(report))
    _write(args.markdown, report_to_markdown(report))
    return _status_exit_code(report.status.value)


if __name__ == "__main__":
    sys.exit(main())
