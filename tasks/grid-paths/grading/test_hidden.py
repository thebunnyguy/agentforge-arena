"""Hidden tests: the graded correctness signal. Never mounted in the agent
workspace. These check small grids with known path counts plus a LARGE grid
whose answer only a DP/memoized/closed-form solution computes within the grader
timeout; the naive exponential recursion is cut off and fails. Fails against the
unimplemented stub (which raises immediately)."""

from gridpaths import count_paths


def test_one_by_one():
    assert count_paths(1, 1) == 1


def test_two_by_two():
    assert count_paths(2, 2) == 2


def test_three_by_three():
    assert count_paths(3, 3) == 6


def test_three_by_four():
    assert count_paths(3, 4) == 10


def test_four_by_three_is_symmetric():
    # The grid count is symmetric in its two dimensions.
    assert count_paths(4, 3) == 10


def test_single_row():
    # One row of cells: only one straight path no matter how wide.
    assert count_paths(1, 9) == 1


def test_single_column():
    assert count_paths(7, 1) == 1


def test_large_grid_requires_polynomial_solution():
    # An 18x18 grid of cells has C(34, 17) == 2333606220 monotonic paths. The
    # naive recursion count_paths(r-1, c) + count_paths(r, c-1) makes on the
    # order of 2**34 calls and is cut off by the grader timeout; a DP table /
    # memoization / closed form computes this in well under a second.
    assert count_paths(18, 18) == 2333606220
