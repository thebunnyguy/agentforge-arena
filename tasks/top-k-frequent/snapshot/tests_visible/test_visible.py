"""Visible tests: the agent's feedback signal (NOT scored).

These provide useful small-case feedback while leaving scale, mutation, custom
objects, and adversarial complexity checks to the hidden grading suite.
"""

from topk import most_common


def test_returns_list():
    assert isinstance(most_common([1, 1, 2], 1), list)


def test_picks_most_frequent():
    assert most_common([1, 1, 2], 1) == [1]


def test_tie_uses_first_appearance():
    assert most_common(["b", "a", "a", "b"], 2) == ["b", "a"]


def test_k_larger_than_distinct_returns_all_items():
    assert most_common([3, 3, 2], 10) == [3, 2]
