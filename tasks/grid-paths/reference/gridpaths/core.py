def count_paths(rows, cols):
    """Count monotonic lattice paths across a ``rows`` x ``cols`` grid of cells.

    Starting in the top-left cell and moving only RIGHT or DOWN, return the
    number of distinct paths to the bottom-right cell.

    Dynamic programming: ``dp[r][c]`` is the number of paths to reach cell
    ``(r, c)``. The top row and left column each have exactly one path (you can
    only arrive by moving straight). Every interior cell is reached either from
    above or from the left, so ``dp[r][c] = dp[r-1][c] + dp[r][c-1]``. This runs
    in O(rows * cols) time with no repeated work, unlike the naive exponential
    recursion.
    """
    # A grid with a non-positive dimension has no cells and thus no path.
    if rows <= 0 or cols <= 0:
        return 0

    # First row: a single straight path to every cell.
    dp = [1] * cols
    for _ in range(1, rows):
        # Walk left to right, folding in the path count from the row above
        # (already stored in dp[c]) plus the cell to the left (dp[c-1], just
        # updated). dp[0] stays 1 (left column has one path).
        for c in range(1, cols):
            dp[c] = dp[c] + dp[c - 1]
    return dp[-1]
