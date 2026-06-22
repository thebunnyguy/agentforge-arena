"""Hidden tests: the graded correctness signal. Never mounted in the agent
workspace. These exercise the full two_sum contract — correct indices, the
no-solution case, duplicates — and a LARGE input whose unique answer sits at the
very end, so only an O(n) hash-map solution finishes within the grader timeout;
an O(n^2) double loop is cut off and fails. Fails against the unimplemented
stub (which raises immediately)."""

from twosum import two_sum


def test_basic_example():
    assert two_sum([2, 7, 11, 15], 9) == (0, 1)


def test_indices_are_ordered_and_correct():
    # 11 + 15 == 26 -> indices (2, 3).
    assert two_sum([2, 7, 11, 15], 26) == (2, 3)


def test_no_solution_returns_none():
    assert two_sum([1, 2, 3], 100) is None


def test_empty_returns_none():
    assert two_sum([], 0) is None


def test_single_element_returns_none():
    # A pair requires two DISTINCT indices.
    assert two_sum([5], 10) is None


def test_does_not_reuse_same_index():
    # Only one 4; 4 + 4 would reuse index 0, which is not allowed.
    assert two_sum([4, 1, 2], 8) is None


def test_duplicates_resolved_correctly():
    # 3 + 3 == 6 using the two distinct 3's at indices 0 and 3.
    assert two_sum([3, 1, 2, 3], 6) == (0, 3)


def test_negative_numbers():
    # -3 + 8 == 5 -> indices (1, 3).
    assert two_sum([10, -3, 7, 8], 5) == (1, 3)


def test_pair_at_the_front():
    assert two_sum([5, 5, 0, 0, 0], 10) == (0, 1)


def test_large_input_answer_at_end_requires_linear():
    # nums = [0, 1, 2, ..., 299999]. The unique pair summing to
    # 299999 + 299998 == 599997 is the last two elements: indices
    # (299998, 299999). A naive O(n^2) scan would examine ~4.5e10 pairs before
    # reaching the end and be cut off by the grader timeout; an O(n) hash-map
    # pass finds it in well under a second.
    n = 300000
    nums = list(range(n))
    target = (n - 1) + (n - 2)  # 599997
    assert two_sum(nums, target) == (n - 2, n - 1)


def test_large_input_no_solution_requires_linear():
    # 0..299999 are all even-spaced consecutive integers; an odd target larger
    # than the maximum possible sum has no pair. The linear solution scans once
    # and returns None; a quadratic scan over every pair is cut off by timeout.
    n = 300000
    nums = list(range(0, 2 * n, 2))  # 0, 2, 4, ..., even numbers
    target = 7  # odd -> impossible from a sum of two even numbers
    assert two_sum(nums, target) is None


def test_both_addends_negative():
    # A pair whose two elements are both negative must still be found.
    assert two_sum([-3, -5], -8) == (0, 1)
    assert two_sum([-10, 3, -7], -17) == (0, 2)
