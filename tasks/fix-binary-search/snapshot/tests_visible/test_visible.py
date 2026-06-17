"""Visible tests: the agent's feedback signal (NOT scored).

These are deliberately weak — they pass even with the buggy implementation
(they only exercise an absent target with no duplicates) — to demonstrate why
the hidden tests are what actually grade.
"""

from searchkit import bisect_left


def test_insertion_point_in_middle():
    assert bisect_left([10, 20, 30], 25) == 2


def test_returns_int():
    assert isinstance(bisect_left([1, 2, 3], 5), int)
