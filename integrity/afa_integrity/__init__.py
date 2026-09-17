"""AgentForge Arena — Benchmark Integrity Engine.

Answers a different question than afa_kernel/afa_runner: not "how did this
agent score," but "can we trust the benchmark that produced that score."
Pure stdlib; depends on afa_kernel and afa_runner, never the reverse.

See docs/agents/ORACLE.md for the design log and docs/BENCHMARK_INTEGRITY.md
for the user-facing design doc.
"""

from __future__ import annotations

from .audit import run_audit
from .controls import Control, discover_controls, load_integrity_config
from .health import determine_health_status
from .model import (
    ENGINE_VERSION,
    SCHEMA_VERSION,
    AuditMode,
    BenchmarkIntegrityReport,
    CheckStatus,
    ControlKind,
    ControlResult,
    Finding,
    HealthStatus,
    IntegrityCheckResult,
    MutationRecord,
    PackAuditSummary,
    Severity,
    Verdict,
)
from .pack import audit_pack
from .report import (
    pack_summary_to_json,
    pack_summary_to_markdown,
    report_to_json,
    report_to_markdown,
)

__all__ = [
    "run_audit",
    "audit_pack",
    "discover_controls",
    "load_integrity_config",
    "Control",
    "determine_health_status",
    "AuditMode",
    "BenchmarkIntegrityReport",
    "CheckStatus",
    "ControlKind",
    "ControlResult",
    "Finding",
    "HealthStatus",
    "IntegrityCheckResult",
    "MutationRecord",
    "PackAuditSummary",
    "Severity",
    "Verdict",
    "report_to_json",
    "report_to_markdown",
    "pack_summary_to_json",
    "pack_summary_to_markdown",
    "ENGINE_VERSION",
    "SCHEMA_VERSION",
]

__version__ = ENGINE_VERSION
