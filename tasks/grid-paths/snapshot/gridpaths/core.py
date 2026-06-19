def count_paths(rows, cols):
    """Count monotonic lattice paths across a ``rows`` x ``cols`` grid of cells.

    Starting in the top-left cell and moving only RIGHT or DOWN one cell at a
    time, return the number of distinct paths to the bottom-right cell. For a
    1x1 grid there is exactly one path (you are already there).

    This must be EFFICIENT: a dynamic-programming / memoized solution (or the
    closed-form binomial), NOT the naive exponential recursion
    ``count_paths(r-1, c) + count_paths(r, c-1)`` which recomputes overlapping
    subproblems and is cut off by the grader's timeout on the large hidden grid.

    STUB: not implemented yet.
    """
    raise NotImplementedError("count_paths is not implemented yet")
