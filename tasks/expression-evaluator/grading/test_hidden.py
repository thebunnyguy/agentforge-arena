"""Hidden tests: the graded correctness signal. Never mounted in the agent
workspace. These exercise operator precedence, parentheses, unary minus,
unary plus, whitespace handling, multi-digit numbers, float literals, and
rejection of malformed input (invalid characters, mismatched parentheses,
trailing tokens, missing operands). They all fail on the unimplemented stub
and pass only with a correct parser.

Note on the pytest.raises(ValueError) tests below: an implementation that
shells out to Python's own eval() (see
integrity/controls/semantic_mutants/eval_based_implementation) happens to get
incidentally rejected by these too, since eval() raises SyntaxError/NameError/
TypeError for this same malformed input rather than ValueError. That is a
side effect, not deliberate enforcement of the task's "Do NOT use eval()"
rule: a two-line try/except wrapper that catches eval()'s exceptions and
re-raises ValueError would satisfy every assertion here while still using
eval() internally. A purely behavioral hidden suite cannot distinguish "uses
eval()" from "does not use eval()" when both produce the same observable
input/output behavior — see the benchmark integrity audit's classification of
that control as a GRADER_INFRASTRUCTURE_LIMITATION, not something this test
file can close."""

import pytest

from calckit import evaluate


def test_precedence_mul_over_add():
    assert evaluate("2+3*4") == 14.0


def test_parens_override_precedence():
    assert evaluate("(2+3)*4") == 20.0


def test_parens_and_subtraction():
    assert evaluate("2*(3+4)-1") == 13.0


def test_unary_minus_leading():
    assert evaluate("-3+2") == -1.0


def test_division_produces_float():
    assert evaluate("7/2") == 3.5


def test_arbitrary_whitespace():
    assert evaluate(" 10  -  2 *3 ") == 4.0


def test_nested_parentheses():
    assert evaluate("((1+2)*(3+4))") == 21.0


def test_multi_digit_numbers():
    assert evaluate("12*12") == 144.0


def test_float_literal_multiplication():
    assert evaluate("1.5*2") == 3.0


def test_unary_minus_in_parens():
    assert evaluate("3*(-2)") == -6.0


def test_left_associative_subtraction():
    # (10-2)-3 = 5, NOT 10-(2-3) = 11. Catches a right-folding parser.
    assert evaluate("10-2-3") == 5.0


def test_left_associative_division():
    # (8/2)/2 = 2, NOT 8/(2/2) = 8. Catches a right-folding parser.
    assert evaluate("8/2/2") == 2.0


def test_chained_subtraction():
    assert evaluate("2-3-4") == -5.0


def test_unary_minus_after_operator():
    # division by a negative literal: 6/(-2) = -3.
    assert evaluate("6/-2") == -3.0


def test_unary_minus_after_binary_minus():
    # 2 - (-3) = 5.
    assert evaluate("2--3") == 5.0


def test_unary_plus_supported():
    # SEMANTIC PROPERTY: '+' is one of the four listed operators with no
    # restriction to binary use, and the task description explicitly treats
    # unary '+' as a no-op sign symmetric with the already-required unary
    # minus. A parser that only special-cases a leading/post-operator '-'
    # (implemented unary minus but never wired up the symmetric unary plus
    # case) must still evaluate a redundant leading or post-operator '+'
    # correctly instead of raising or dropping the operand. Two independent
    # positions (leading, and right after a binary operator) are checked so
    # a fix that only special-cases position 0 doesn't accidentally pass.
    assert evaluate("+3*2") == 6.0
    assert evaluate("3+ +2") == 5.0


def test_invalid_character_is_rejected():
    # SEMANTIC PROPERTY: a character that is not whitespace, one of the four
    # operators, a parenthesis, a digit, or '.' is not part of this task's
    # supported syntax and must be reported as a ValueError, never silently
    # dropped, never mis-scanned into an infinite loop, and never leaked as
    # some other exception type. This is its own test function (not sharing
    # a body with other pytest.raises checks) precisely because a defective
    # tokenizer can hang on this input rather than raising promptly -- a
    # hang here must not prevent the other hidden tests from running.
    with pytest.raises(ValueError):
        evaluate("2+a")


def test_trailing_tokens_are_rejected():
    # SEMANTIC PROPERTY: once a complete expression has been parsed, any
    # left-over token (a second number with no operator between it and the
    # first, or an unmatched closing parenthesis) means the input as a whole
    # was not a single valid arithmetic expression. A correct implementation
    # must raise ValueError for it rather than silently evaluating just the
    # prefix it managed to parse and discarding the rest.
    with pytest.raises(ValueError):
        evaluate("1 2")
    with pytest.raises(ValueError):
        evaluate("1+2)")


def test_missing_operand_raises_value_error():
    # SEMANTIC PROPERTY: a trailing operator with nothing after it is not a
    # valid expression under this contract. The exception type matters here,
    # not just that *some* exception occurs: evaluate() is documented to
    # signal an invalid expression with ValueError specifically (matching
    # every other malformed-input case above), so a caller that catches
    # ValueError to report "invalid expression" to its own caller must not
    # be surprised by a different, undocumented exception type (e.g. a
    # TypeError leaking from an internal float(None) conversion) escaping
    # instead.
    with pytest.raises(ValueError):
        evaluate("3+")
