from collections import Counter


def most_common(items, k):
    """Return the ``k`` most frequent items in ``items``, most frequent first.

    Ties (equal frequency) are broken by FIRST appearance in ``items``. If ``k``
    exceeds the number of distinct items, all of them are returned; an empty
    input returns ``[]``.

    Near-linear: a single ``Counter`` pass tallies every frequency in O(n), and
    we record each item's first-appearance index in the same spirit. We then
    sort the DISTINCT items (there are at most n of them) by ``(-count, index)``
    — descending frequency, ties by earliest first occurrence — which costs
    O(d log d). No per-element rescans, so it stays fast on large inputs.
    """
    if k <= 0:
        return []

    counts = Counter(items)

    # Record the first index at which each distinct value appears, so ties in
    # frequency can be resolved by earliest appearance. One pass, O(n).
    first_index = {}
    for i, x in enumerate(items):
        if x not in first_index:
            first_index[x] = i

    # Sort distinct items by descending count, then by earliest first appearance.
    ordered = sorted(counts, key=lambda x: (-counts[x], first_index[x]))
    return ordered[:k]
