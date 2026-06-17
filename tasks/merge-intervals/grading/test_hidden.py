"""Hidden tests: the graded correctness signal. Never mounted in the agent
workspace. These fail with the passthrough stub and pass only with a correct
sort-then-merge implementation that also merges touching intervals."""

from intervalkit import merge


def test_overlapping():
    assert merge([(1, 4), (2, 5)]) == [(1, 5)]


def test_touching_merges():
    assert merge([(1, 2), (2, 3)]) == [(1, 3)]


def test_nested():
    assert merge([(1, 10), (3, 5)]) == [(1, 10)]


def test_unsorted_input():
    assert merge([(8, 10), (1, 3), (2, 6), (15, 18)]) == [(1, 6), (8, 10), (15, 18)]


def test_disjoint_kept_separate():
    assert merge([(1, 2), (4, 5), (7, 8)]) == [(1, 2), (4, 5), (7, 8)]


def test_single():
    assert merge([(5, 7)]) == [(5, 7)]


def test_empty():
    assert merge([]) == []


def test_all_collapse_to_one():
    assert merge([(1, 3), (2, 4), (3, 7), (6, 9)]) == [(1, 9)]


def test_large_input_chain_collapses():
    # 1000 intervals: (0,1), (1,2), ..., (999,1000). Each touches the next,
    # so the whole chain collapses to a single interval. Given in reverse to
    # force sorting.
    intervals = [(i, i + 1) for i in range(1000)]
    intervals.reverse()
    assert merge(intervals) == [(0, 1000)]


def test_large_input_alternating_gaps():
    # 1000 disjoint intervals (0,1), (2,3), (4,5), ... with gaps between them.
    # None overlap or touch, so the result is the same set, sorted ascending.
    intervals = [(2 * i, 2 * i + 1) for i in range(1000)]
    intervals.reverse()
    expected = [(2 * i, 2 * i + 1) for i in range(1000)]
    assert merge(intervals) == expected
