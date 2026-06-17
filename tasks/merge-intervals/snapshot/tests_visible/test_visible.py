"""Visible tests: the agent's feedback signal (NOT scored).

These are deliberately weak — they pass even with the stub that returns the
input unchanged — to demonstrate why hidden tests are what actually grade.
"""

from intervalkit import merge


def test_returns_a_list():
    assert isinstance(merge([(1, 3)]), list)


def test_single_interval_passthrough():
    # A single already-non-overlapping interval is unchanged.
    assert merge([(1, 3)]) == [(1, 3)]
