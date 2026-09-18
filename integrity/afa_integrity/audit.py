"""The audit orchestrator: composes every check into one
BenchmarkIntegrityReport (mission §4/§24).

QUICK mode: reference (3x repeat) + no-op + hidden-import-closure (static,
cheap) + protected-path probes + declared controls + a determinism sanity
check (repeat-grade the no-op). FULL mode adds: reference at 5x repeat,
generic AST mutation testing, a determinism sample over declared controls
too, and the isolation probe. Every expensive operation is explicit — see
each check module's own cost notes — nothing here silently downgrades FULL to
QUICK behavior to save time.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone

from afa_runner.diffing import capture_diff
from afa_runner.sandbox import LocalSandbox, Sandbox
from afa_runner.task import Task

from .checks.controls_check import run_controls_check
from .checks.determinism import DeterminismSample, run_determinism_check
from .checks.hidden_import_closure import run_hidden_import_closure_check
from .checks.isolation import run_isolation_probe
from .checks.noop import run_noop_check
from .checks.protected_paths import run_protected_paths_check
from .checks.reference import FULL_REPEATS, QUICK_REPEATS, run_reference_check
from .controls import discover_controls, load_integrity_config
from .health import determine_health_status
from .model import (
    ENGINE_VERSION,
    SCHEMA_VERSION,
    AuditMode,
    BenchmarkIntegrityReport,
    IntegrityCheckResult,
)
from .mutation.engine import DEFAULT_MAX_MUTANTS, run_mutation_check
from .overlay import overlay_files_diff
from .provenance import collect_provenance

BLANKET_ISOLATION_LIMITATION = (
    "Grading executes submitted/mutated code via LocalSandbox, which provides "
    "per-run workspace isolation and timeouts but NOT untrusted-agent security "
    "isolation (runner/afa_runner/sandbox.py's own module docstring). Every "
    "check in this report assumes the code being graded is trying to game the "
    "SCORE, not attack the HOST — see isolation.hidden_test_readability for a "
    "concrete, always-present consequence of that assumption."
)


def run_audit(
    task: Task,
    *,
    mode: AuditMode = AuditMode.QUICK,
    sandbox: Sandbox | None = None,
    force_mutation: bool = False,
    max_mutants: int = DEFAULT_MAX_MUTANTS,
) -> BenchmarkIntegrityReport:
    start = time.monotonic()
    created_at = datetime.now(timezone.utc).isoformat()
    sandbox = sandbox or LocalSandbox()
    config = load_integrity_config(task)

    checks: list[IntegrityCheckResult] = []
    findings = []
    limitations = [BLANKET_ISOLATION_LIMITATION]

    repeats = FULL_REPEATS if mode == AuditMode.FULL else QUICK_REPEATS
    checks.append(run_reference_check(task, sandbox, repeats=repeats))
    checks.append(run_noop_check(task, sandbox))
    checks.append(run_hidden_import_closure_check(task))

    protected_check, protected_findings = run_protected_paths_check(task)
    checks.append(protected_check)
    findings.extend(protected_findings)

    controls_check, control_results = run_controls_check(task, sandbox)
    checks.append(controls_check)
    if not control_results:
        limitations.append(
            "No known-bad solutions, semantic mutants, or alternative "
            "solutions declared for this task "
            "(tasks/<id>/integrity/controls/) — absence of evidence here, "
            "not evidence of absence."
        )

    determinism_samples = [
        DeterminismSample(
            label="noop",
            diff=capture_diff(
                task.snapshot_dir,
                task.snapshot_dir,
                protected_globs=task.protected_paths,
                editable_globs=task.editable_paths,
            ),
        )
    ]

    run_mutation = mode == AuditMode.FULL or force_mutation
    mutations = []
    if run_mutation:
        for c in discover_controls(task):
            # No artificial timeout override: declared controls are
            # human-authored, specific implementations, not randomly-mutated
            # code most likely to infinite-loop — grade against the task's
            # own timeout_s, the real bound every other grade call uses.
            determinism_samples.append(
                DeterminismSample(
                    label=f"control:{c.kind.value}:{c.name}",
                    diff=overlay_files_diff(task, c.overlay_files()),
                )
            )
        mutation_check, mutations = run_mutation_check(
            task, sandbox, config, max_mutants=max_mutants
        )
        checks.append(mutation_check)
    else:
        limitations.append(
            "Mutation testing and a determinism sample over declared "
            "controls were not run — pass --full or --mutation for "
            "stronger evidence."
        )

    checks.append(run_determinism_check(task, determinism_samples, sandbox))

    # Independent of run_mutation/force_mutation: the isolation probe is
    # gated on FULL mode alone, so `--quick --mutation` runs mutation testing
    # but NOT the isolation probe — each limitation below is tied to exactly
    # the condition that gates the check it describes, not to the audit mode
    # as a whole, so the two can never contradict each other.
    if mode == AuditMode.FULL:
        isolation_check = run_isolation_probe(task, sandbox)
        checks.append(isolation_check)
        limitations.append(
            "Hidden-test readability during grading could not be ruled out "
            "(see the isolation.hidden_test_readability check) — this "
            "finding is deliberately excluded from the status precedence "
            "(afa_integrity.health) because it is a constant, documented "
            "property of the current LocalSandbox threat model, not "
            "something this specific task can fix."
        )
    else:
        limitations.append(
            "The isolation probe was not run (FULL mode only) — pass "
            "--full to check whether the hidden test source is readable "
            "by code being graded."
        )

    limitations.append(
        "Mutation equivalence is undecidable in general; a surviving "
        "mutant is reported as-is unless explicitly declared equivalent in "
        "tasks/<id>/integrity/integrity.json. A mutation kill rate is never "
        "treated as a correctness probability (mission §16)."
    )

    status, reason = determine_health_status(checks, control_results)
    provenance = collect_provenance(task)
    duration_ms = int((time.monotonic() - start) * 1000)

    return BenchmarkIntegrityReport(
        schema_version=SCHEMA_VERSION,
        engine_version=ENGINE_VERSION,
        task_id=task.id,
        task_version=task.version,
        mode=mode,
        status=status,
        reason=reason,
        created_at=created_at,
        checks=tuple(checks),
        mutations=tuple(mutations),
        controls=tuple(control_results),
        findings=tuple(findings),
        limitations=tuple(limitations),
        provenance=provenance,
        duration_ms=duration_ms,
    )
