"""Hidden tests: the graded correctness signal. Never mounted in the agent
workspace. These exercise operator precedence, parentheses, unary minus,
whitespace handling, multi-digit numbers, and float literals. They all fail on
the unimplemented stub and pass only with a correct parser."""

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
