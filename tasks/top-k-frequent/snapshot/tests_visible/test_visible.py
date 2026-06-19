"""Visible tests: the agent's feedback signal (NOT scored).

These are deliberately weak — they only check a coarse property and one tiny
case — to demonstrate why the hidden tests are what actually grade.
"""

from topk import most_common


def test_returns_list():
    assert isinstance(most_common([1, 1, 2], 1), list)


def test_picks_most_frequent():
    assert most_common([1, 1, 2], 1) == [1]
