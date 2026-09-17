_VALUES = {
    "I": 1,
    "V": 5,
    "X": 10,
    "L": 50,
    "C": 100,
    "D": 500,
    "M": 1000,
}

# BUG (deliberate, realistic copy/paste typo): the keys for 9 and 900 have
# their two letters transposed. A coder building this table from memory
# mixed up "the smaller numeral comes first" with the visual order they
# remembered from XI/MC elsewhere, so "IX" and "CM" are misspelled as "XI"
# and "MC". Every other subtractive pair is correct.
_SUBTRACTIVE_PAIRS = {
    "IV": 4,
    "XI": 9,    # should be "IX": 9
    "XL": 40,
    "XC": 90,
    "CD": 400,
    "MC": 900,  # should be "CM": 900
}


def from_roman(s):
    """Convert a Roman numeral string ``s`` to its integer value.

    Scans for known two-letter subtractive pairs first, then falls back to
    summing individual numerals.
    """
    total = 0
    i = 0
    n = len(s)
    while i < n:
        pair = s[i : i + 2]
        if pair in _SUBTRACTIVE_PAIRS:
            total += _SUBTRACTIVE_PAIRS[pair]
            i += 2
        else:
            total += _VALUES[s[i]]
            i += 1
    return total
