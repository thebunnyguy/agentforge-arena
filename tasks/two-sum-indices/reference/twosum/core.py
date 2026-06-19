def two_sum(nums, target):
    """Return the indices of two distinct elements of ``nums`` that sum to ``target``.

    ``nums`` is a sequence of integers. Returns a tuple ``(i, j)`` with ``i < j``
    such that ``nums[i] + nums[j] == target``; returns ``None`` if no such pair
    exists.

    O(n) single pass: walk the list once, and for each value remember the index
    at which it was first seen. When we encounter a value whose complement
    (``target - value``) has already been seen, we have found the pair. Because
    the complement was seen at an earlier index, the returned tuple is naturally
    ordered ``(i, j)`` with ``i < j``.
    """
    seen = {}  # value -> earliest index at which it appeared
    for j, value in enumerate(nums):
        complement = target - value
        i = seen.get(complement)
        if i is not None:
            return (i, j)
        # Only record the first occurrence so the smallest index is kept.
        if value not in seen:
            seen[value] = j
    return None
