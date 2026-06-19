def most_common(items, k):
    """Return the ``k`` most frequent items in ``items``, most frequent first.

    ``items`` is a sequence of hashable values. Return a list of the ``k`` items
    that occur most often, ordered from most to least frequent. Ties (items with
    equal frequency) are broken by FIRST appearance in ``items`` — the one whose
    first occurrence comes earlier is listed first. If ``k`` is greater than the
    number of distinct items, return all of them. An empty input returns ``[]``.

    This must be EFFICIENT: roughly O(n) using a single counting pass (e.g.
    collections.Counter or a dict), NOT an O(n^2) approach such as calling
    ``items.count(x)`` for every element. A quadratic solution is cut off by the
    grader's timeout on the large hidden input.

    STUB: not implemented yet.
    """
    raise NotImplementedError("most_common is not implemented yet")
