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


def test_standalone_point_interval_preserved():
    # A zero-length (point) interval must be kept, not silently dropped.
    assert [tuple(x) for x in merge([(3, 3)])] == [(3, 3)]


def test_point_interval_between_disjoint_kept():
    assert [tuple(x) for x in merge([(1, 5), (5, 5), (7, 9)])] == [(1, 5), (7, 9)]


def test_merge_into_most_recent_group_not_first():
    # Semantic property: once the output already contains more than one
    # disjoint group, a later overlap must merge into whichever group it
    # actually overlaps (the most recently emitted one), not be checked
    # against the very first group ever emitted. (1, 2) is disjoint from
    # everything else and must stay untouched; (10, 15) and (14, 20)
    # overlap each other and must merge into a single (10, 20) group. An
    # implementation that (bug-for-bug) tracks only the first emitted group
    # instead of the current one would wrongly leave (10, 15) and (14, 20)
    # unmerged here, since neither overlaps (1, 2).
    assert merge([(1, 2), (10, 15), (14, 20)]) == [(1, 2), (10, 20)]


def test_multiple_independent_merge_clusters_unsorted():
    # Same property as above, exercised with unsorted input and two
    # separate merge clusters, to also rule out an implementation that
    # merges everything into (or reads its running end from) a single
    # fixed slot rather than the group each new interval actually
    # overlaps: (1, 3) & (2, 4) form one cluster, (10, 12) & (11, 13)
    # another, and the two clusters are disjoint from each other.
    assert merge([(11, 13), (2, 4), (10, 12), (1, 3)]) == [(1, 4), (10, 13)]
