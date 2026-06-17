"""Visible tests: the agent's feedback signal (NOT scored).

These are deliberately weak — they pass even with the buggy summing
implementation (no subtractive pairs are exercised) — to demonstrate why hidden
tests are what actually grade.
"""

from romankit import from_roman


def test_single_numeral():
    assert from_roman("X") == 10


def test_additive_only():
    assert from_roman("VIII") == 8
