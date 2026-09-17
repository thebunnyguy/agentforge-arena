"""Benchmark-health status: a pure, independently-tested precedence function
(mission §15/§6), never scattered if/else across individual checks.

Precedence (highest wins): INVALID > NEEDS_REVIEW > UNVERIFIABLE >
PROVISIONAL > HEALTHY. Evidence-backed states, not a fabricated percentage
(mission §15: no "Benchmark Quality = 87.291%").

One check is deliberately EXCLUDED from this function entirely:
isolation.hidden_test_readability (checks/isolation.py) always reports
UNVERIFIABLE under the current LocalSandbox threat model — including it here
would make every task in the pack UNVERIFIABLE and the status field would
carry no information (docs/agents/ORACLE.md, "Isolation UNVERIFIABLE must not
become contagious"). It is still surfaced in the report's limitations and
findings, just not folded into the status precedence.
"""

from __future__ import annotations

from .model import (
    AuditMode,
    CheckStatus,
    ControlKind,
    ControlResult,
    HealthStatus,
    IntegrityCheckResult,
)

EXCLUDED_FROM_STATUS = frozenset({"isolation.hidden_test_readability"})

# controls.declared_controls' own aggregate FAIL/ERROR is deliberately not
# read generically below — the per-control loop derives a more precise reason
# (which KIND failed, and how) from the same underlying ControlResults, so
# reading both would double up near-duplicate reasons for one root cause.
_CONTROLS_AGGREGATE_CHECK_ID = "controls.declared_controls"


def determine_health_status(
    checks: list[IntegrityCheckResult],
    controls: list[ControlResult],
    mode: AuditMode,
) -> tuple[HealthStatus, str]:
    invalid: list[str] = []
    needs_review: list[str] = []
    unverifiable: list[str] = []
    provisional: list[str] = []

    for c in checks:
        if c.check_id in EXCLUDED_FROM_STATUS:
            continue
        if c.status == CheckStatus.FAIL:
            if c.check_id == _CONTROLS_AGGREGATE_CHECK_ID:
                continue
            invalid.append(f"{c.check_id}: {c.description}")
        elif c.status == CheckStatus.ERROR:
            if c.check_id == _CONTROLS_AGGREGATE_CHECK_ID:
                continue
            invalid.append(f"{c.check_id}: {c.description}")
        elif c.status == CheckStatus.WARNING:
            needs_review.append(f"{c.check_id}: {c.description}")
        elif c.status == CheckStatus.UNVERIFIABLE:
            unverifiable.append(f"{c.check_id}: {c.description}")
        elif c.status == CheckStatus.SKIPPED:
            provisional.append(f"{c.check_id}: {c.description}")

    for cr in controls:
        if cr.status == CheckStatus.FAIL:
            if cr.kind == ControlKind.KNOWN_BAD:
                invalid.append(
                    f"known-bad control '{cr.name}' was ACCEPTED "
                    "(should have been rejected by the hidden suite)"
                )
            elif cr.kind == ControlKind.SEMANTIC_MUTANT:
                needs_review.append(
                    f"semantic mutant '{cr.name}' survived "
                    "(should have been rejected by the hidden suite)"
                )
            elif cr.kind == ControlKind.ALTERNATIVE:
                needs_review.append(
                    f"alternative solution '{cr.name}' was rejected by the "
                    "hidden suite (overly narrow oracle)"
                )
        elif cr.status == CheckStatus.ERROR:
            needs_review.append(
                f"control '{cr.name}' ({cr.kind.value}) rejected by scope or "
                "regression gate, not the hidden suite — control-authoring "
                "issue, fix the control"
            )

    if mode == AuditMode.QUICK and not (invalid or needs_review or unverifiable or provisional):
        provisional.append(
            "audit mode is QUICK: mutation testing, semantic mutants beyond "
            "declared controls, and a wider determinism sample were not run "
            "— run --full for stronger evidence"
        )

    if invalid:
        return HealthStatus.INVALID, "; ".join(invalid)
    if needs_review:
        return HealthStatus.NEEDS_REVIEW, "; ".join(needs_review)
    if unverifiable:
        return HealthStatus.UNVERIFIABLE, "; ".join(unverifiable)
    if provisional:
        return HealthStatus.PROVISIONAL, "; ".join(provisional)
    return HealthStatus.HEALTHY, "All checks passed with no outstanding findings."
