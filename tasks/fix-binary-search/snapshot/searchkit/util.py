def is_sorted(seq):
    """Return ``True`` if ``seq`` is in non-decreasing order, else ``False``.

    An empty sequence and a single-element sequence are considered sorted.
    """
    for i in range(1, len(seq)):
        if seq[i - 1] > seq[i]:
            return False
    return True
