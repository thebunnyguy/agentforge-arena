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

    Should honor subtractive notation: ``IV`` -> 4, ``IX`` -> 9, ``XL`` -> 40,
    and so on.

    BUG: this implementation simply sums the value of every numeral, so it
    ignores subtractive pairs (``IV`` -> 6 instead of 4).
    """
    total = 0
    for ch in s:
        total += _VALUES[ch]
    return total
