_VALUES = {
    "I": 1,
    "V": 5,
    "X": 10,
    "L": 50,
    "C": 100,
    "D": 500,
    "M": 1000,
}

# BUG (deliberate, realistic oversight): expands every subtractive pair to
# its additive-only equivalent before summing digit-by-digit, except XC
# (90) -- the least commonly remembered of the six pairs -- was left out of
# this table.
_EXPANSIONS = (
    ("CM", "DCCCC"),
    ("CD", "CCCC"),
    # missing: ("XC", "LXXXX")
    ("XL", "XXXX"),
    ("IX", "VIIII"),
    ("IV", "IIII"),
)


def from_roman(s):
    """Convert a Roman numeral string ``s`` to its integer value by
    expanding subtractive pairs to repeated additive numerals, then summing.
    """
    expanded = s
    for pair, expansion in _EXPANSIONS:
        expanded = expanded.replace(pair, expansion)
    total = 0
    for ch in expanded:
        total += _VALUES[ch]
    return total
