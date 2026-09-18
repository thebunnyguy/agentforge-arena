def bisect_left(sorted_list, target):
    """Return the leftmost index at which ``target`` can be inserted into
    ``sorted_list`` to keep it sorted.

    If ``target`` is already present, this is the index of its first
    occurrence. If absent, it is the index where ``target`` would go.
    """
    lo = 0
    # BUG: `hi` must be able to reach len(sorted_list) itself, since the
    # correct answer for a target greater than every element IS
    # len(sorted_list). Starting one short of that means the search space
    # never lets `lo` climb past len(sorted_list) - 1.
    hi = len(sorted_list) - 1
    while lo < hi:
        mid = (lo + hi) // 2
        if sorted_list[mid] < target:
            lo = mid + 1
        else:
            hi = mid
    return lo
