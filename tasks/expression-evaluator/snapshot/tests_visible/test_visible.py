"""Visible tests: the agent's feedback signal (NOT scored).

These are deliberately weak — they cover only a couple of trivial cases — to
demonstrate that the hidden suite (precedence, parentheses, unary minus,
whitespace, floats) is what actually grades the implementation.
"""

from calckit import evaluate


def test_simple_addition():
    assert evaluate("1+1") == 2.0


def test_returns_float():
    assert isinstance(evaluate("3*2"), float)
