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

    Honors subtractive notation: ``IV`` -> 4, ``IX`` -> 9, ``XL`` -> 40, etc.
    When a numeral is smaller than the numeral to its right, it is subtracted
    rather than added.
    """
    total = 0
    prev = 0
    for ch in reversed(s):
        value = _VALUES[ch]
        if value < prev:
            total -= value
        else:
            total += value
            prev = value
    return total
