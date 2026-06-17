"""Hidden tests: the graded correctness signal. Never mounted in the agent
workspace. The present-target and duplicate cases fail with the buggy
(upper-bound) implementation and pass only with a correct leftmost-insertion
bisect_left."""

from searchkit import bisect_left


def test_target_present_returns_leftmost():
    assert bisect_left([1, 2, 4, 4, 4, 7], 4) == 2


def test_target_present_no_duplicates():
    assert bisect_left([1, 3, 5, 7, 9], 5) == 2


def test_target_absent_insertion_point():
    assert bisect_left([1, 3, 5, 7, 9], 6) == 3


def test_first_element():
    assert bisect_left([2, 4, 6], 2) == 0


def test_last_element_present():
    assert bisect_left([2, 4, 6], 6) == 2


def test_before_first_and_after_last():
    assert bisect_left([2, 4, 6], 1) == 0
    assert bisect_left([2, 4, 6], 9) == 3


def test_all_equal_returns_zero():
    assert bisect_left([5, 5, 5, 5], 5) == 0


def test_empty_list():
    assert bisect_left([], 1) == 0


def test_single_element():
    assert bisect_left([4], 4) == 0
    assert bisect_left([4], 1) == 0
    assert bisect_left([4], 9) == 1
