"""Stable sibling module: small, already-correct money helpers used by the
order pipeline. These are NOT part of the refactoring task and must keep
behaving identically."""


def to_cents(dollars):
    """Convert a whole/decimal dollar amount to an integer number of cents,
    rounding to the nearest cent."""
    return int(round(dollars * 100))


def format_cents(cents):
    """Format an integer number of cents as a ``$D.CC`` string."""
    return "${0}.{1:02d}".format(cents // 100, cents % 100)
