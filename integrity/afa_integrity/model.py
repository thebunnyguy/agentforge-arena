"""Domain model for the Benchmark Integrity Engine.

The engine's whole job is to produce EVIDENCE about whether a task's oracle
(reference solution + hidden tests + grader) can be trusted — not a single
boolean. Every dataclass here is frozen (facts, not mutable state, matching
afa_kernel's own convention) and every status is an enum with more than two
values on purpose: a check that "didn't run", "can't be verified under the
current sandbox", or "errored" is a different fact from one that failed, and
collapsing them to a boolean throws away exactly the information a benchmark
author needs to act.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class CheckStatus(str, Enum):
    """Outcome of one IntegrityCheckResult. Never reduce this to a boolean."""

    PASS = "pass"
    FAIL = "fail"
    WARNING = "warning"
    SKIPPED = "skipped"
    UNVERIFIABLE = "unverifiable"
    ERROR = "error"


class Severity(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class HealthStatus(str, Enum):
    """A task's overall benchmark-health classification.

    Deliberately not a percentage (mission: no fake precision like
    "Benchmark Quality = 87.291%"). See afa_integrity.health for the exact,
    independently-tested precedence rule that derives this from a report's
    checks.
    """

    HEALTHY = "healthy"
    PROVISIONAL = "provisional"
    NEEDS_REVIEW = "needs_review"
    INVALID = "invalid"
    UNVERIFIABLE = "unverifiable"


class AuditMode(str, Enum):
    """QUICK: reference + no-op + declared controls + a determinism sanity
    check. FULL: QUICK plus generic mutation testing, semantic mutants,
    alternatives, and repeated grading of a wider sample. See afa_integrity.audit.
    """

    QUICK = "quick"
    FULL = "full"


class Verdict(str, Enum):
    """The one outcome vocabulary shared by every overlay this engine grades:
    a reference solution, a no-op, a known-bad control, a semantic mutant, an
    alternative solution, or a generic AST mutant. Grading any overlay reduces
    to exactly one of these five things, and callers must not conflate them —
    a control "rejected" by the regression or scope gate did NOT get caught by
    the hidden-test oracle this engine exists to validate; it is a
    control-authoring problem, not evidence about hidden-test quality.
    """

    ACCEPTED = "accepted"
    REJECTED_BY_HIDDEN_TEST = "rejected_by_hidden_test"
    REJECTED_BY_REGRESSION_GATE = "rejected_by_regression_gate"
    REJECTED_BY_SCOPE_GATE = "rejected_by_scope_gate"
    REJECTED_BY_TIMEOUT_OR_ERROR = "rejected_by_timeout_or_error"
    # Mutation-only: the candidate was never graded because its base file
    # failed the ast.unparse round-trip self-check (see mutation/engine.py).
    UNSUPPORTED = "unsupported"


class ControlKind(str, Enum):
    KNOWN_BAD = "known_bad"
    SEMANTIC_MUTANT = "semantic_mutant"
    ALTERNATIVE = "alternative"


@dataclass(frozen=True)
class IntegrityCheckResult:
    """One check's result, with the evidence that produced it preserved.

    evidence must be JSON-serializable (plain dict/list/str/int/float/bool/
    None) — it is what a benchmark author reads to understand *why*, not just
    *what*. duration_ms is wall-clock for this check alone, used to report
    QUICK vs FULL cost (mission §24).
    """

    check_id: str
    category: str
    status: CheckStatus
    severity: Severity
    description: str
    evidence: dict[str, Any] = field(default_factory=dict)
    duration_ms: int = 0


@dataclass(frozen=True)
class MutationRecord:
    """One generated mutant and what happened when it was graded."""

    mutation_id: str
    file: str
    lineno: int
    col_offset: int
    family: str
    description: str
    verdict: Verdict
    final_score: float
    functional_pass: bool
    killed_by_tests: tuple[str, ...] = ()
    declared_equivalent: bool = False
    diff_hash: str = ""
    notes: str = ""


@dataclass(frozen=True)
class ControlResult:
    """One declared control (known-bad / semantic mutant / alternative),
    graded and checked against its author-declared expectation.
    """

    name: str
    kind: ControlKind
    description: str
    expected_accept: bool   # True for ALTERNATIVE, False for the other two
    verdict: Verdict
    final_score: float
    functional_pass: bool
    matched_expectation: bool
    status: CheckStatus     # PASS / FAIL / WARNING / ERROR — see checks.controls
    notes: str = ""


@dataclass(frozen=True)
class Finding:
    """A specific, actionable observation — the thing a human reviewing this
    report actually needs to read. Checks produce findings; findings are what
    drive severity-sorted display, independent of which check emitted them.
    """

    finding_id: str
    category: str
    severity: Severity
    summary: str
    detail: str
    evidence: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class BenchmarkIntegrityReport:
    """The full evidence bundle for one task at one version, at one engine
    version, at one point in time. Nothing here is a percentage presented as
    ground truth; `status` is a classification with a human-readable `reason`,
    and `limitations` is populated whenever the engine could not establish
    something it would like to have established (isolation guarantees above
    all — see afa_integrity.checks.isolation).
    """

    schema_version: str
    engine_version: str
    task_id: str
    task_version: str
    mode: AuditMode
    status: HealthStatus
    reason: str
    created_at: str
    checks: tuple[IntegrityCheckResult, ...] = ()
    mutations: tuple[MutationRecord, ...] = ()
    controls: tuple[ControlResult, ...] = ()
    findings: tuple[Finding, ...] = ()
    limitations: tuple[str, ...] = ()
    provenance: dict[str, Any] = field(default_factory=dict)
    duration_ms: int = 0


@dataclass(frozen=True)
class PackAuditSummary:
    """Aggregate over a pack-level run (mission §21).

    failures maps task_id -> error message for any task that could not be
    audited at all (e.g. a malformed task.json) — a pack-wide run must never
    let one broken task silently swallow every other task's completed
    report, but it also must never hide that a task couldn't be audited.
    """

    schema_version: str
    engine_version: str
    mode: AuditMode
    created_at: str
    reports: tuple[BenchmarkIntegrityReport, ...]
    status_counts: dict[str, int] = field(default_factory=dict)
    common_findings: tuple[Finding, ...] = ()
    failures: dict[str, str] = field(default_factory=dict)
    duration_ms: int = 0


ENGINE_VERSION = "0.1.0"
SCHEMA_VERSION = "1.0.0"
