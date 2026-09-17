"""Mutation generation, self-checking, and grading orchestration.

One AST node mutated per mutant (classic mutation-testing practice), applied
only to files matching the task's editable_paths (mutating outside it can't
teach us anything about hidden-test quality — it would just fail the scope
gate for reasons unrelated to test adequacy). ast.unparse reformats the whole
file it touches, so before trusting any mutant generated from a file, this
module first grades that file's own unparse(parse(source)) round-trip and
marks the whole file UNSUPPORTED if that no longer scores (1.0, True) —
otherwise a reformatting-induced behavior change would be silently reported as
a real mutation-testing result.
"""

from __future__ import annotations

import ast
import time
from dataclasses import dataclass

from afa_runner.diffing import path_is_protected
from afa_runner.sandbox import Sandbox
from afa_runner.task import Task

from ..controls import TaskIntegrityConfig, is_declared_equivalent
from ..model import CheckStatus, IntegrityCheckResult, MutationRecord, Severity, Verdict
from ..overlay import (
    classify_verdict,
    diff_hash,
    grade_diff,
    killed_by_tests,
    overlay_files_diff,
    read_overlay_files,
)
from .operators import OPERATORS

DEFAULT_MUTATION_TIMEOUT_S = 20
DEFAULT_MAX_MUTANTS = 60


@dataclass(frozen=True)
class _Candidate:
    relpath: str
    operator_index: int
    walk_index: int
    lineno: int
    col_offset: int
    family: str
    op_id: str
    original_snippet: str


def _walk_with_parents(node, parent=None, field=None, index=None):
    yield node, parent, field, index
    for f, value in ast.iter_fields(node):
        if isinstance(value, list):
            for i, item in enumerate(value):
                if isinstance(item, ast.AST):
                    yield from _walk_with_parents(item, node, f, i)
        elif isinstance(value, ast.AST):
            yield from _walk_with_parents(value, node, f, None)


def _enumerate_candidates(tree: ast.AST, relpath: str, source: str) -> list[_Candidate]:
    candidates: list[_Candidate] = []
    walk_index = 0
    for node, _parent, _field, _index in _walk_with_parents(tree):
        for op_idx, op in enumerate(OPERATORS):
            if op.matches(node):
                snippet = ast.get_source_segment(source, node) or ""
                candidates.append(
                    _Candidate(
                        relpath=relpath,
                        operator_index=op_idx,
                        walk_index=walk_index,
                        lineno=getattr(node, "lineno", -1),
                        col_offset=getattr(node, "col_offset", -1),
                        family=op.family,
                        op_id=op.op_id,
                        original_snippet=snippet.strip()[:200],
                    )
                )
        walk_index += 1
    return candidates


def _materialize_mutant(source: str, relpath: str, candidate: _Candidate) -> tuple[str, str]:
    """Re-parse source fresh and apply exactly the operator identified by
    candidate (located by its position in a deterministic re-walk), returning
    (mutated_source, human-readable change description).
    """
    tree = ast.parse(source, filename=relpath)
    op = OPERATORS[candidate.operator_index]
    target = None
    walk_index = 0
    for node, parent, field, index in _walk_with_parents(tree):
        if walk_index == candidate.walk_index:
            target = (node, parent, field, index)
            break
        walk_index += 1
    if target is None or not op.matches(target[0]):
        raise RuntimeError(
            f"could not relocate mutation candidate {candidate.op_id} at "
            f"{relpath}:{candidate.walk_index} on re-parse"
        )
    node, parent, field, index = target
    change = op.apply(node, parent, field, index)
    ast.fix_missing_locations(tree)
    return ast.unparse(tree), change


def _select_editable_files(task: Task, files: dict[str, str], exclude: tuple[str, ...]) -> dict[str, str]:
    """Only mutate .py files an agent could actually change: matching
    editable_paths when an allow-list is configured (mutating outside it
    can't teach us anything about hidden-test quality — capture_diff would
    just fail the scope gate, unrelated to test adequacy), using the exact
    same glob-matching afa_runner's own scope gate uses (path_is_protected
    works for any glob list, not just a "protected" one).
    """
    selected = {}
    for rel, text in files.items():
        if not rel.endswith(".py"):
            continue
        if exclude and path_is_protected(rel, exclude):
            continue
        if task.editable_paths and not path_is_protected(rel, task.editable_paths):
            continue
        selected[rel] = text
    return selected


def generate_and_grade_mutants(
    task: Task,
    sandbox: Sandbox,
    config: TaskIntegrityConfig,
    *,
    max_mutants: int = DEFAULT_MAX_MUTANTS,
) -> tuple[list[MutationRecord], list[str]]:
    """Returns (records, limitation_notes). Never raises for an expected-shape
    problem (missing reference, unparseable file, self-check failure) —
    those become UNSUPPORTED records and/or limitation notes instead.
    """
    notes: list[str] = []
    if task.reference_dir is None:
        return [], ["mutation testing requires task.reference_dir; none configured"]

    reference_files = read_overlay_files(task.reference_dir)
    target_files = _select_editable_files(task, reference_files, config.mutation_exclude_files)
    if not target_files:
        return [], [
            "no reference file matched editable_paths for mutation "
            "(nothing to mutate that an agent could actually change)"
        ]

    effective_timeout = min(
        task.timeout_s, config.mutation_timeout_s or DEFAULT_MUTATION_TIMEOUT_S
    )

    per_file_candidates: dict[str, list[_Candidate]] = {}
    unsupported_files: dict[str, str] = {}

    for relpath, source in sorted(target_files.items()):
        try:
            tree = ast.parse(source, filename=relpath)
        except SyntaxError as exc:
            notes.append(f"{relpath}: SyntaxError parsing reference file, skipped ({exc})")
            continue

        normalized = ast.unparse(tree)
        normalized_files = dict(reference_files)
        normalized_files[relpath] = normalized
        norm_diff = overlay_files_diff(task, normalized_files)
        norm_report, norm_score = grade_diff(task, norm_diff, sandbox, timeout_s=effective_timeout)
        candidates = _enumerate_candidates(tree, relpath, source)

        if not (norm_score.final_score == 1.0 and norm_score.functional_pass):
            reason = (
                f"{relpath}: ast.unparse round-trip of the reference no "
                "longer scores (1.0, True) — all mutants for this file are "
                "marked unsupported rather than reported as real results "
                f"(round-trip: final_score={norm_score.final_score}, "
                f"functional_pass={norm_score.functional_pass})."
            )
            notes.append(reason)
            unsupported_files[relpath] = reason
        per_file_candidates[relpath] = candidates

    all_candidates = [c for cs in per_file_candidates.values() for c in cs]
    all_candidates.sort(key=lambda c: (c.relpath, c.lineno, c.col_offset, c.op_id))

    dropped = 0
    if len(all_candidates) > max_mutants:
        dropped = len(all_candidates) - max_mutants
        notes.append(
            f"mutation candidate cap reached: generated {len(all_candidates)} "
            f"candidates, graded only the first {max_mutants} (deterministic "
            f"order by file/line/operator); {dropped} candidate(s) NOT graded "
            "this run."
        )
        all_candidates = all_candidates[:max_mutants]

    records: list[MutationRecord] = []
    for c in all_candidates:
        mutation_id = f"{c.relpath}:{c.lineno}:{c.col_offset}:{c.op_id}"
        if c.relpath in unsupported_files:
            records.append(
                MutationRecord(
                    mutation_id=mutation_id,
                    file=c.relpath,
                    lineno=c.lineno,
                    col_offset=c.col_offset,
                    family=c.family,
                    description=f"{c.op_id}: {c.original_snippet}",
                    verdict=Verdict.UNSUPPORTED,
                    final_score=0.0,
                    functional_pass=False,
                    notes=unsupported_files[c.relpath],
                )
            )
            continue

        source = target_files[c.relpath]
        mutated_source, change = _materialize_mutant(source, c.relpath, c)
        mutated_files = dict(reference_files)
        mutated_files[c.relpath] = mutated_source
        diff = overlay_files_diff(task, mutated_files)
        report, score = grade_diff(task, diff, sandbox, timeout_s=effective_timeout)
        verdict = classify_verdict(report, score)
        dh = diff_hash(diff)
        declared = is_declared_equivalent(config, c.relpath, dh)

        records.append(
            MutationRecord(
                mutation_id=mutation_id,
                file=c.relpath,
                lineno=c.lineno,
                col_offset=c.col_offset,
                family=c.family,
                description=f"{c.op_id}: {c.original_snippet} ({change})",
                verdict=verdict,
                final_score=score.final_score,
                functional_pass=score.functional_pass,
                killed_by_tests=killed_by_tests(report) if verdict == Verdict.REJECTED_BY_HIDDEN_TEST else (),
                declared_equivalent=declared is not None,
                diff_hash=dh,
                notes=f"declared equivalent: {declared.reason}" if declared else "",
            )
        )

    return records, notes


def summarize_mutants(records: list[MutationRecord]) -> dict:
    generated = len(records)
    unsupported = sum(1 for r in records if r.verdict == Verdict.UNSUPPORTED)
    declared_equivalent = sum(1 for r in records if r.declared_equivalent)
    relevant = generated - unsupported - declared_equivalent
    killed_by_hidden = sum(
        1 for r in records if r.verdict == Verdict.REJECTED_BY_HIDDEN_TEST and not r.declared_equivalent
    )
    killed_by_regression = sum(
        1 for r in records if r.verdict == Verdict.REJECTED_BY_REGRESSION_GATE and not r.declared_equivalent
    )
    killed_by_error = sum(
        1 for r in records if r.verdict == Verdict.REJECTED_BY_TIMEOUT_OR_ERROR and not r.declared_equivalent
    )
    killed_by_scope = sum(
        1 for r in records if r.verdict == Verdict.REJECTED_BY_SCOPE_GATE and not r.declared_equivalent
    )
    survived = [
        r for r in records
        if r.verdict == Verdict.ACCEPTED and not r.declared_equivalent
    ]
    killed_total = killed_by_hidden + killed_by_regression + killed_by_error + killed_by_scope
    return {
        "mutants_generated": generated,
        "mutants_unsupported": unsupported,
        "mutants_declared_equivalent": declared_equivalent,
        "mutants_relevant": relevant,
        "killed_total": killed_total,
        "killed_by_hidden_test": killed_by_hidden,
        "killed_by_regression_gate": killed_by_regression,
        "killed_by_scope_gate": killed_by_scope,
        "killed_by_timeout_or_error": killed_by_error,
        "survived_count": len(survived),
        "survived": [
            {
                "mutation_id": r.mutation_id,
                "file": r.file,
                "lineno": r.lineno,
                "family": r.family,
                "description": r.description,
            }
            for r in survived
        ],
        "kill_rate": (killed_total / relevant) if relevant else None,
    }


def run_mutation_check(
    task: Task, sandbox: Sandbox, config: TaskIntegrityConfig, *, max_mutants: int = DEFAULT_MAX_MUTANTS
) -> tuple[IntegrityCheckResult, list[MutationRecord]]:
    start = time.monotonic()
    records, notes = generate_and_grade_mutants(task, sandbox, config, max_mutants=max_mutants)
    duration_ms = int((time.monotonic() - start) * 1000)

    if task.reference_dir is None:
        return (
            IntegrityCheckResult(
                check_id="mutation.generic_ast_mutants",
                category="mutation",
                status=CheckStatus.UNVERIFIABLE,
                severity=Severity.MEDIUM,
                description="No reference_dir; mutation testing requires one.",
                evidence={"notes": notes},
                duration_ms=duration_ms,
            ),
            records,
        )

    summary = summarize_mutants(records)
    summary["notes"] = notes

    if summary["mutants_relevant"] == 0:
        return (
            IntegrityCheckResult(
                check_id="mutation.generic_ast_mutants",
                category="mutation",
                status=CheckStatus.WARNING,
                severity=Severity.MEDIUM,
                description=(
                    "No relevant mutants were generated (all candidates were "
                    "unsupported or declared-equivalent, or no editable file "
                    "had any mutable construct). Mutation adequacy could not "
                    "be assessed this run."
                ),
                evidence=summary,
                duration_ms=duration_ms,
            ),
            records,
        )

    if summary["survived_count"] > 0:
        kr = summary["kill_rate"]
        kr_str = f"{kr:.2f}" if kr is not None else "n/a"
        return (
            IntegrityCheckResult(
                check_id="mutation.generic_ast_mutants",
                category="mutation",
                status=CheckStatus.WARNING,
                severity=Severity.MEDIUM,
                description=(
                    f"{summary['survived_count']}/{summary['mutants_relevant']} "
                    f"relevant mutant(s) survived (kill_rate={kr_str} over "
                    f"{summary['mutants_relevant']} relevant of "
                    f"{summary['mutants_generated']} generated). A surviving "
                    "mutant is not automatic proof of a broken oracle — "
                    "review whether each represents behavior the task "
                    "contract actually promises to reject (mission §8); see "
                    "evidence.survived for exact locations."
                ),
                evidence=summary,
                duration_ms=duration_ms,
            ),
            records,
        )

    return (
        IntegrityCheckResult(
            check_id="mutation.generic_ast_mutants",
            category="mutation",
            status=CheckStatus.PASS,
            severity=Severity.INFO,
            description=(
                f"All {summary['mutants_relevant']} relevant mutant(s) were "
                f"killed (kill_rate=1.00 over "
                f"{summary['mutants_generated']} generated, "
                f"{summary['mutants_unsupported']} unsupported, "
                f"{summary['mutants_declared_equivalent']} declared-equivalent)."
            ),
            evidence=summary,
            duration_ms=duration_ms,
        ),
        records,
    )
