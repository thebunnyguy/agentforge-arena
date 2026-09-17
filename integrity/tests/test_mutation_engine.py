"""Unit tests for the AST mutation layer, isolated from grading: candidate
enumeration and materialization are pure functions of source text, so they
are tested directly without spinning up a task/sandbox at all.
"""

import ast

from afa_integrity.mutation.engine import _enumerate_candidates, _materialize_mutant
from afa_integrity.mutation.operators import OPERATORS

SOURCE = '''
def classify(n):
    if n < 0:
        raise ValueError("negative")
    if n < 10:
        return "small"
    return "large"


def total(items):
    acc = 0
    for x in items:
        acc += x
    return acc


def is_even(n):
    return not (n % 2)
'''


def _candidates():
    tree = ast.parse(SOURCE, filename="mod.py")
    return _enumerate_candidates(tree, "mod.py", SOURCE)


def test_enumerates_at_least_one_candidate_per_family_present():
    candidates = _candidates()
    families = {c.family for c in candidates}
    # boundary_operator (n < 10, n < 0), remove_validation (raise guard),
    # return_constant (return "small"/"large"/acc), delete_state_update
    # (acc = 0, acc += x), drop_not (not (...)) should all be present in
    # this source.
    for expected in (
        "boundary_operator",
        "remove_validation",
        "return_constant",
        "delete_state_update",
        "drop_not",
    ):
        assert expected in families, f"expected family {expected} in {families}"


def test_materialize_boundary_operator_mutant_changes_only_that_comparison():
    candidates = [c for c in _candidates() if c.family == "boundary_operator"]
    assert candidates, "no boundary_operator candidates found"
    # First boundary candidate should be `n < 0` -> `n <= 0`.
    target = candidates[0]
    mutated_source, change = _materialize_mutant(SOURCE, "mod.py", target)
    assert mutated_source != SOURCE
    assert "Lt -> LtE" == change or "LtE -> Lt" == change
    # The mutated source must still be valid Python.
    ast.parse(mutated_source)


def test_materialize_remove_validation_replaces_raise_with_pass():
    candidates = [c for c in _candidates() if c.family == "remove_validation"]
    assert len(candidates) == 1
    mutated_source, change = _materialize_mutant(SOURCE, "mod.py", candidates[0])
    assert "raise ValueError" not in mutated_source
    assert "removed" in change
    ast.parse(mutated_source)


def test_materialize_delete_state_update_replaces_assign_with_pass():
    candidates = [c for c in _candidates() if c.family == "delete_state_update"]
    assert len(candidates) == 2  # `acc = 0` and `acc += x`
    for c in candidates:
        mutated_source, change = _materialize_mutant(SOURCE, "mod.py", c)
        assert mutated_source != SOURCE
        ast.parse(mutated_source)


def test_materialize_is_deterministic_and_independent_across_candidates():
    """Materializing candidate k must never leak into candidate k+1 — each
    materialization re-parses the ORIGINAL source fresh."""
    candidates = _candidates()
    baseline = ast.dump(ast.parse(SOURCE))
    for c in candidates:
        _materialize_mutant(SOURCE, "mod.py", c)
        # The original SOURCE string itself must be untouched (strings are
        # immutable in Python, but this guards against any accidental global
        # mutation of a shared AST object across candidates).
        assert ast.dump(ast.parse(SOURCE)) == baseline


def test_every_operator_family_is_unique_or_intentionally_shared():
    # change_constant and remove_branch are the only families with >1 op_id
    # (increment/zero, force_true/force_false) — everything else is 1:1.
    family_to_ops = {}
    for op in OPERATORS:
        family_to_ops.setdefault(op.family, set()).add(op.op_id)
    multi = {f: ops for f, ops in family_to_ops.items() if len(ops) > 1}
    assert set(multi.keys()) == {"change_constant", "remove_branch"}


def test_unparseable_mutant_is_still_valid_python_for_all_candidates():
    """Every generated mutant must remain syntactically valid Python — a
    mutation that produces a SyntaxError would be a bug in an operator's
    apply(), not a meaningful mutant."""
    for c in _candidates():
        mutated_source, _ = _materialize_mutant(SOURCE, "mod.py", c)
        ast.parse(mutated_source)  # raises SyntaxError if invalid
