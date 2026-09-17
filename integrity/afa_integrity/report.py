"""JSON (machine-readable) and Markdown (human-readable) report rendering
(mission §19/§20), following the house convention already established by
audit/audit-N/{AUDIT_FINDINGS.json, AUDIT_REPORT.md}: a versioned JSON schema
plus a narrative Markdown rendering of the same evidence, never prose-only.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

from .model import BenchmarkIntegrityReport, PackAuditSummary


def _enum_safe(obj: Any) -> Any:
    """json.dumps default= hook: render Enum members by their .value."""
    if hasattr(obj, "value") and hasattr(obj, "name") and not isinstance(obj, (int, str)):
        return obj.value
    raise TypeError(f"not JSON serializable: {obj!r}")


def report_to_json(report: BenchmarkIntegrityReport, *, indent: int = 2) -> str:
    return json.dumps(asdict(report), indent=indent, default=_enum_safe, sort_keys=False)


def pack_summary_to_json(summary: PackAuditSummary, *, indent: int = 2) -> str:
    return json.dumps(asdict(summary), indent=indent, default=_enum_safe, sort_keys=False)


def _status_badge(status: str) -> str:
    return {
        "pass": "PASS",
        "fail": "FAIL",
        "warning": "WARNING",
        "skipped": "SKIPPED",
        "unverifiable": "UNVERIFIABLE",
        "error": "ERROR",
    }.get(status, status.upper())


def report_to_markdown(report: BenchmarkIntegrityReport) -> str:
    lines: list[str] = []
    a = lines.append

    a("# AgentForge Benchmark Integrity Report")
    a("")
    a(f"**Task**: `{report.task_id}`  ")
    a(f"**Version**: `{report.task_version}`  ")
    a(f"**Mode**: `{report.mode.value}`  ")
    a(f"**Engine version**: `{report.engine_version}` (schema `{report.schema_version}`)  ")
    a(f"**Timestamp**: {report.created_at}  ")
    a(f"**Duration**: {report.duration_ms} ms")
    a("")
    a(f"## Status: {report.status.value.upper()}")
    a("")
    a(f"**Reason**: {report.reason}")
    a("")

    a("## Checks")
    a("")
    a("| Check | Category | Status | Severity | Description |")
    a("|---|---|---|---|---|")
    for c in report.checks:
        desc = c.description.replace("\n", " ").replace("|", "\\|")
        a(f"| `{c.check_id}` | {c.category} | {_status_badge(c.status.value)} | {c.severity.value} | {desc} |")
    a("")

    if report.controls:
        a("## Controls")
        a("")
        a("| Name | Kind | Expected | Verdict | Status | Notes |")
        a("|---|---|---|---|---|---|")
        for cr in report.controls:
            expected = "accept" if cr.expected_accept else "reject"
            a(
                f"| `{cr.name}` | {cr.kind.value} | {expected} | "
                f"{cr.verdict.value} | {_status_badge(cr.status.value)} | "
                f"{cr.notes} |"
            )
        a("")

    if report.mutations:
        a("## Mutation analysis")
        a("")
        generated = len(report.mutations)
        survived = [m for m in report.mutations if m.verdict.value == "accepted" and not m.declared_equivalent]
        unsupported = [m for m in report.mutations if m.verdict.value == "unsupported"]
        equivalent = [m for m in report.mutations if m.declared_equivalent]
        killed = generated - len(survived) - len(unsupported) - len(equivalent)
        a(f"- Generated: {generated}")
        a(f"- Unsupported (base file failed the unparse round-trip self-check): {len(unsupported)}")
        a(f"- Declared equivalent: {len(equivalent)}")
        a(f"- Killed: {killed}")
        a(f"- **Survived: {len(survived)}**")
        a("")
        if survived:
            a("Survived mutants (review whether the task contract actually promises to reject each):")
            a("")
            a("| File | Line | Family | Description |")
            a("|---|---|---|---|")
            for m in survived:
                a(f"| `{m.file}` | {m.lineno} | {m.family} | {m.description} |")
            a("")

    if report.findings:
        a("## Findings")
        a("")
        for f in sorted(report.findings, key=lambda x: x.severity.value):
            a(f"- **[{f.severity.value.upper()}] {f.summary}** (`{f.finding_id}`)")
            a(f"  {f.detail}")
        a("")

    if report.limitations:
        a("## Limitations")
        a("")
        for lim in report.limitations:
            a(f"- {lim}")
        a("")

    a("## Provenance")
    a("")
    for k, v in report.provenance.items():
        a(f"- `{k}`: {v}")
    a("")

    return "\n".join(lines)


def pack_summary_to_markdown(summary: PackAuditSummary) -> str:
    lines: list[str] = []
    a = lines.append

    a("# AgentForge Benchmark Integrity — Pack Audit")
    a("")
    a(f"**Mode**: `{summary.mode.value}`  ")
    a(f"**Engine version**: `{summary.engine_version}` (schema `{summary.schema_version}`)  ")
    a(f"**Timestamp**: {summary.created_at}  ")
    a(f"**Duration**: {summary.duration_ms} ms  ")
    a(f"**Tasks audited**: {len(summary.reports)}")
    a("")

    a("## Status counts")
    a("")
    a("| Status | Count |")
    a("|---|---|")
    for status, count in sorted(summary.status_counts.items()):
        a(f"| {status.upper()} | {count} |")
    a("")

    a("## Per-task results")
    a("")
    a("| Task | Version | Status | Reason |")
    a("|---|---|---|---|")
    for r in sorted(summary.reports, key=lambda r: r.task_id):
        reason = r.reason.replace("\n", " ").replace("|", "\\|")
        if len(reason) > 140:
            reason = reason[:137] + "..."
        a(f"| `{r.task_id}` | {r.task_version} | {r.status.value.upper()} | {reason} |")
    a("")

    if summary.common_findings:
        a("## Common findings across the pack")
        a("")
        for f in summary.common_findings:
            a(f"- **[{f.severity.value.upper()}] {f.summary}** (`{f.finding_id}`)")
            a(f"  {f.detail}")
        a("")

    return "\n".join(lines)
