"""Hidden tests: the graded correctness signal. Never mounted in the agent
workspace. These exercise the full most_common contract — frequency ordering,
ties broken by first appearance, k larger than the number of distinct items, and
the empty case — plus a LARGE input that only an ~O(n) counting solution handles
within the grader timeout; an O(n^2) approach (e.g. items.count per element) is
cut off and fails. Fails against the unimplemented stub (which raises
immediately)."""

from topk import most_common


def test_simple_most_frequent_first():
    # 1 appears 3x, 2 appears 2x, 3 appears 1x.
    assert most_common([1, 1, 1, 2, 2, 3], 2) == [1, 2]


def test_tie_broken_by_first_appearance():
    # "a" and "b" both appear twice; "a" appears first in the list, so it ranks
    # first. "c" appears once.
    assert most_common(["a", "b", "a", "b", "c"], 2) == ["a", "b"]


def test_tie_broken_by_first_appearance_reordered():
    # Same frequencies as above but "b" now appears first -> "b" ranks first.
    assert most_common(["b", "a", "b", "a", "c"], 2) == ["b", "a"]


def test_three_way_tie_uses_first_appearance_order():
    # x, y, z each appear twice; first-appearance order is z, y, x.
    items = ["z", "y", "x", "z", "y", "x"]
    assert most_common(items, 3) == ["z", "y", "x"]


def test_k_larger_than_distinct_returns_all():
    # Only two distinct items but k == 5 -> return both, most frequent first.
    assert most_common([4, 4, 7], 5) == [4, 7]


def test_k_equals_distinct_count():
    assert most_common([1, 2, 2, 3, 3, 3], 3) == [3, 2, 1]


def test_empty_returns_empty():
    assert most_common([], 3) == []


def test_k_zero_returns_empty():
    assert most_common([1, 1, 2], 0) == []


def test_negative_k_returns_empty():
    assert most_common([1, 1, 2], -5) == []


def test_single_distinct_item():
    assert most_common([9, 9, 9, 9], 1) == [9]


def test_partial_top_k_with_distinct_frequencies():
    # Frequencies: 5->4, 6->3, 7->2, 8->1. Top 2 are 5 then 6.
    items = [5, 5, 5, 5, 6, 6, 6, 7, 7, 8]
    assert most_common(items, 2) == [5, 6]


def test_input_sequence_is_not_mutated():
    items = [3, 1, 3, 2, 1, 3]
    before = list(items)
    assert most_common(items, 2) == [3, 1]
    assert items == before


def test_custom_hashable_values_keep_first_appearance_tiebreak():
    class Token:
        def __init__(self, value):
            self.value = value

        def __hash__(self):
            return hash(self.value)

        def __eq__(self, other):
            return isinstance(other, Token) and self.value == other.value

    second = Token("second")
    first = Token("first")
    items = [second, first, Token("second"), Token("first")]
    result = most_common(items, 2)
    assert [token.value for token in result] == ["second", "first"]
    assert result[0] is second
    assert result[1] is first


def test_distinct_items_do_not_trigger_quadratic_equality_scans():
    class Probe:
        comparisons = 0

        def __init__(self, value):
            self.value = value

        def __hash__(self):
            return self.value

        def __eq__(self, other):
            Probe.comparisons += 1
            return isinstance(other, Probe) and self.value == other.value

    items = [Probe(value) for value in range(250)]
    result = most_common(items, 5)
    assert [item.value for item in result] == [0, 1, 2, 3, 4]
    # A list.count-per-item implementation performs ~62k comparisons here;
    # dict/Counter counting with distinct hashes stays comfortably below this.
    assert Probe.comparisons < 2000


def test_large_input_requires_linear_counting():
    # Five "hot" values with strictly distinct, decreasing frequencies, followed
    # by a long tail of 300_000 unique singletons. The unambiguous top-5 (by
    # frequency) is [10, 11, 12, 13, 14]. An O(n^2) approach that recomputes a
    # per-element frequency (e.g. items.count(x)) scans ~3e5 elements ~3e5 times
    # and is cut off by the grader timeout; a single Counter/dict pass plus a
    # sort of the distinct keys finishes in well under a second.
    items = []
    items += [10] * 500
    items += [11] * 400
    items += [12] * 300
    items += [13] * 200
    items += [14] * 100
    # 300_000 unique values (disjoint from the hot values above), each freq 1.
    items += list(range(1000, 1000 + 300000))
    assert most_common(items, 5) == [10, 11, 12, 13, 14]


def test_large_input_full_ranking_is_truncated_correctly():
    # Same construction; asking for the top 3 truncates to the three most
    # frequent values, still requiring a near-linear solution to finish in time.
    items = []
    items += [10] * 500
    items += [11] * 400
    items += [12] * 300
    items += [13] * 200
    items += [14] * 100
    items += list(range(1000, 1000 + 300000))
    assert most_common(items, 3) == [10, 11, 12]


def test_tie_uses_first_not_last_appearance():
    # "b" and "a" both occur twice; first-appearance order puts "b" first. A
    # last-appearance tiebreak would return ["a", "b"].
    assert most_common(["b", "a", "a", "b"], 2) == ["b", "a"]
