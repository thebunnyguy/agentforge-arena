def is_sorted_desc(nums):
    """Return True iff ``nums`` is sorted in non-increasing order.

    An empty list or a single-element list is trivially sorted. A small,
    already-correct helper used elsewhere in the package.
    """
    for i in range(1, len(nums)):
        if nums[i] > nums[i - 1]:
            return False
    return True
