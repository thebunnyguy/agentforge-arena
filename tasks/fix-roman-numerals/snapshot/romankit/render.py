_NUMERALS = [
    (1000, "M"),
    (900, "CM"),
    (500, "D"),
    (400, "CD"),
    (100, "C"),
    (90, "XC"),
    (50, "L"),
    (40, "XL"),
    (10, "X"),
    (9, "IX"),
    (5, "V"),
    (4, "IV"),
    (1, "I"),
]


def to_roman(n):
    """Convert a positive integer ``n`` to its Roman numeral string.

    Uses subtractive notation: ``4 -> "IV"``, ``1994 -> "MCMXCIV"``.
    """
    out = []
    for value, symbol in _NUMERALS:
        while n >= value:
            out.append(symbol)
            n -= value
    return "".join(out)
