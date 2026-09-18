"""The generic mutation operator catalog (mission §8).

Each Operator matches a specific AST node shape and, given (node, parent,
field, index) from mutation.engine's parent-tracking walk, mutates a FRESHLY
PARSED tree in place (either by rewriting the node's own attributes, or by
replacing the node within its parent container when the mutation changes the
node's type) and returns a short human-readable description of the change.

One operator application = one mutant (classic mutation-testing practice:
never compound multiple mutations into a single candidate). Deliberately a
short, curated list of semantically meaningful families rather than an
exhaustive syntactic operator set (mission §8: "optimize for meaningful
semantic mutations," not mutant count).
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import Callable

NodeRef = tuple[ast.AST, "ast.AST | None", "str | None", "int | None"]


def _replace(parent: ast.AST | None, field: str | None, index: int | None, new_node: ast.AST) -> None:
    """Replace a node within its parent container (list slot or direct field).
    Used when a mutation changes the node's own type (e.g. Break -> Continue),
    as opposed to rewriting an attribute in place (e.g. flipping a compare op).
    """
    if parent is None or field is None:
        raise ValueError("cannot replace the module root node")
    if index is not None:
        getattr(parent, field)[index] = new_node
    else:
        setattr(parent, field, new_node)


@dataclass(frozen=True)
class Operator:
    family: str
    op_id: str
    description: str
    matches: Callable[[ast.AST], bool]
    apply: Callable[[ast.AST, "ast.AST | None", "str | None", "int | None"], str]


_INVERT_COMPARE = {
    ast.Eq: ast.NotEq, ast.NotEq: ast.Eq,
    ast.Is: ast.IsNot, ast.IsNot: ast.Is,
    ast.In: ast.NotIn, ast.NotIn: ast.In,
}
_BOUNDARY_COMPARE = {
    ast.Lt: ast.LtE, ast.LtE: ast.Lt,
    ast.Gt: ast.GtE, ast.GtE: ast.Gt,
}


def _is_single_compare(node: ast.AST, table: dict) -> bool:
    return isinstance(node, ast.Compare) and len(node.ops) == 1 and type(node.ops[0]) in table


def _apply_compare_swap(table: dict):
    def apply(node, parent, field, index) -> str:
        old_op = node.ops[0]
        new_cls = table[type(old_op)]
        node.ops = [new_cls()]
        return f"{type(old_op).__name__} -> {new_cls.__name__}"
    return apply


def _is_bool_op(node: ast.AST) -> bool:
    return isinstance(node, ast.BoolOp)


def _apply_bool_op_swap(node, parent, field, index) -> str:
    old = type(node.op).__name__
    node.op = ast.Or() if isinstance(node.op, ast.And) else ast.And()
    return f"{old} -> {type(node.op).__name__}"


def _is_bool_literal(node: ast.AST) -> bool:
    return isinstance(node, ast.Constant) and isinstance(node.value, bool)


def _apply_bool_literal_flip(node, parent, field, index) -> str:
    old = node.value
    node.value = not old
    return f"{old!r} -> {node.value!r}"


def _is_numeric_literal(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Constant)
        and isinstance(node.value, (int, float))
        and not isinstance(node.value, bool)
    )


def _apply_numeric_increment(node, parent, field, index) -> str:
    old = node.value
    node.value = old + 1
    return f"{old!r} -> {node.value!r}"


def _is_nonzero_numeric_literal(node: ast.AST) -> bool:
    return _is_numeric_literal(node) and node.value != 0


def _apply_numeric_zero(node, parent, field, index) -> str:
    old = node.value
    node.value = 0
    return f"{old!r} -> 0"


def _is_raise_guard_if(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.If)
        and len(node.body) > 0
        and isinstance(node.body[0], ast.Raise)
    )


def _apply_remove_validation(node, parent, field, index) -> str:
    node.body = [ast.Pass()]
    return "if-guard's raise removed (body -> pass)"


def _is_nontrivial_except(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.ExceptHandler)
        and not (len(node.body) == 1 and isinstance(node.body[0], ast.Pass))
    )


def _apply_drop_exception_handling(node, parent, field, index) -> str:
    node.body = [ast.Pass()]
    return "except-handler body replaced with pass (error swallowed silently)"


def _is_if(node: ast.AST) -> bool:
    return isinstance(node, ast.If) and not (
        isinstance(node.test, ast.Constant) and isinstance(node.test.value, bool)
    )


def _apply_force_true(node, parent, field, index) -> str:
    node.test = ast.Constant(value=True)
    return "if-condition forced to True (branch always taken)"


def _apply_force_false(node, parent, field, index) -> str:
    node.test = ast.Constant(value=False)
    return "if-condition forced to False (branch never taken)"


def _is_nontrivial_return(node: ast.AST) -> bool:
    return isinstance(node, ast.Return) and node.value is not None and not (
        isinstance(node.value, ast.Constant) and node.value.value is None
    )


def _apply_return_none(node, parent, field, index) -> str:
    node.value = ast.Constant(value=None)
    return "return <expr> -> return None"


def _is_state_update(node: ast.AST) -> bool:
    return isinstance(node, (ast.Assign, ast.AugAssign))


def _apply_delete_state_update(node, parent, field, index) -> str:
    _replace(parent, field, index, ast.Pass())
    return "assignment/state-update statement deleted (replaced with pass)"


def _is_not(node: ast.AST) -> bool:
    return isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not)


def _apply_drop_not(node, parent, field, index) -> str:
    _replace(parent, field, index, node.operand)
    return "unary 'not' dropped"


def _is_break_or_continue(node: ast.AST) -> bool:
    return isinstance(node, (ast.Break, ast.Continue))


def _apply_break_continue_swap(node, parent, field, index) -> str:
    new_node = ast.Continue() if isinstance(node, ast.Break) else ast.Break()
    old_name = type(node).__name__
    _replace(parent, field, index, new_node)
    return f"{old_name} -> {type(new_node).__name__}"


OPERATORS: tuple[Operator, ...] = (
    Operator(
        family="invert_comparison",
        op_id="invert_comparison",
        description="Invert an equality/identity/membership comparison "
        "(== <-> !=, is <-> is not, in <-> not in).",
        matches=lambda n: _is_single_compare(n, _INVERT_COMPARE),
        apply=_apply_compare_swap(_INVERT_COMPARE),
    ),
    Operator(
        family="boundary_operator",
        op_id="boundary_operator",
        description="Swap an ordering comparison across its boundary "
        "(< <-> <=, > <-> >=) — the classic off-by-one mutant.",
        matches=lambda n: _is_single_compare(n, _BOUNDARY_COMPARE),
        apply=_apply_compare_swap(_BOUNDARY_COMPARE),
    ),
    Operator(
        family="swap_boolean_condition",
        op_id="swap_boolean_condition",
        description="Swap a boolean 'and'/'or' in a compound condition.",
        matches=_is_bool_op,
        apply=_apply_bool_op_swap,
    ),
    Operator(
        family="swap_boolean_literal",
        op_id="swap_boolean_literal",
        description="Flip a literal True/False constant.",
        matches=_is_bool_literal,
        apply=_apply_bool_literal_flip,
    ),
    Operator(
        family="change_constant",
        op_id="change_constant_increment",
        description="Increment a numeric literal by 1 (off-by-one constant).",
        matches=_is_numeric_literal,
        apply=_apply_numeric_increment,
    ),
    Operator(
        family="change_constant",
        op_id="change_constant_zero",
        description="Zero out a nonzero numeric literal.",
        matches=_is_nonzero_numeric_literal,
        apply=_apply_numeric_zero,
    ),
    Operator(
        family="remove_validation",
        op_id="remove_validation",
        description="Remove a raise-based validation guard "
        "(if <cond>: raise ... -> pass).",
        matches=_is_raise_guard_if,
        apply=_apply_remove_validation,
    ),
    Operator(
        family="drop_exception_handling",
        op_id="drop_exception_handling",
        description="Replace an except-handler's body with pass "
        "(silently swallow the error).",
        matches=_is_nontrivial_except,
        apply=_apply_drop_exception_handling,
    ),
    Operator(
        family="remove_branch",
        op_id="remove_branch_force_true",
        description="Force an if-condition to always be True.",
        matches=_is_if,
        apply=_apply_force_true,
    ),
    Operator(
        family="remove_branch",
        op_id="remove_branch_force_false",
        description="Force an if-condition to always be False.",
        matches=_is_if,
        apply=_apply_force_false,
    ),
    Operator(
        family="return_constant",
        op_id="return_constant",
        description="Replace a non-trivial return value with None.",
        matches=_is_nontrivial_return,
        apply=_apply_return_none,
    ),
    Operator(
        family="delete_state_update",
        op_id="delete_state_update",
        description="Delete an assignment/augmented-assignment statement.",
        matches=_is_state_update,
        apply=_apply_delete_state_update,
    ),
    Operator(
        family="drop_not",
        op_id="drop_not",
        description="Drop a unary 'not'.",
        matches=_is_not,
        apply=_apply_drop_not,
    ),
    Operator(
        family="break_continue_swap",
        op_id="break_continue_swap",
        description="Swap 'break' and 'continue'.",
        matches=_is_break_or_continue,
        apply=_apply_break_continue_swap,
    ),
)
