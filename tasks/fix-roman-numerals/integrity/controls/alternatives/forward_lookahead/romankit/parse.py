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

    Scans left-to-right with one character of lookahead: if the current
    numeral's value is strictly smaller than the numeral immediately
    following it, it is part of a subtractive pair and is subtracted;
    otherwise it is added. This is a forward-scanning alternative to the
    reference's backward scan (which tracks the largest value seen so far),
    but produces identical results for every well-formed Roman numeral (the
    two approaches can diverge on malformed/ambiguous input, which is
    outside this task's spec).
    """
    total = 0
    n = len(s)
    for i in range(n):
        value = _VALUES[s[i]]
        if i + 1 < n and value < _VALUES[s[i + 1]]:
            total -= value
        else:
            total += value
    return total
