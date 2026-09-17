def bisect_left(sorted_list, target):
    """Return the leftmost index at which ``target`` can be inserted into
    ``sorted_list`` to keep it sorted.

    If ``target`` is already present, this is the index of its first
    occurrence. If absent, it is the index where ``target`` would go.

    Structurally different from the reference: a plain left-to-right linear
    scan for the first element that is not smaller than ``target``, rather
    than a binary search. Behaviorally identical for every input -- O(n)
    instead of O(log n), which the contract does not forbid.
    """
    for index, value in enumerate(sorted_list):
        if value >= target:
            return index
    return len(sorted_list)
