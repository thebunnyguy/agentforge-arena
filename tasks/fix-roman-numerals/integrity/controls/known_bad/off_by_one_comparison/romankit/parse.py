_VALUES = {
    "I": 1,
    "V": 5,
    "X": 10,
    "L": 50,
    "C": 100,
    "D": 500,
    "M": 1000,
}


def from_roman(s):
    """Convert a Roman numeral string ``s`` to its integer value.

    Looks one character ahead: if the current numeral's value is smaller
    than (or equal to -- BUG, should be strictly smaller than) the next
    numeral's value, subtract it; otherwise add it.

    BUG: the ``<=`` should be ``<``. Two adjacent numerals of the same value
    (e.g. the repeated ``I``s in ``III``, or the repeated ``I``s in
    ``LVIII``) are incorrectly treated as a subtractive pair and cancel each
    other out instead of summing.
    """
    total = 0
    n = len(s)
    for i in range(n):
        value = _VALUES[s[i]]
        if i + 1 < n and value <= _VALUES[s[i + 1]]:
            total -= value
        else:
            total += value
    return total
