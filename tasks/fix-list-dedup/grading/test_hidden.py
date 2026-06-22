"""Hidden tests: the graded correctness signal. Never mounted in the agent
workspace. The order-preservation cases fail with a set()-based dedup and pass
only with a first-occurrence-order-preserving implementation."""

from listkit import dedup


def test_preserves_first_occurrence_order_ints():
    assert dedup([3, 1, 3, 2, 1]) == [3, 1, 2]


def test_preserves_first_occurrence_order_strings():
    assert dedup(["b", "a", "b", "c", "a"]) == ["b", "a", "c"]


def test_longer_sequence_order():
    assert dedup([5, 4, 5, 3, 4, 2, 1, 1]) == [5, 4, 3, 2, 1]


def test_empty_list():
    assert dedup([]) == []


def test_already_unique_preserved():
    assert dedup([10, 20, 30]) == [10, 20, 30]


def test_element_appearing_three_or_more_times():
    # A "skip the 2nd occurrence only" bug passes the at-most-twice cases but
    # lets a 3rd occurrence through.
    assert dedup([1, 2, 1, 2, 1]) == [1, 2]
    assert dedup([1, 1, 1]) == [1]
    assert dedup([1, 2, 1, 3, 1]) == [1, 2, 3]
