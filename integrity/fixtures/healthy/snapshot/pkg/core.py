def classify(n):
    """Return 'small' for n < 10, 'large' for n >= 10.

    BUG: uses <= instead of <, so 10 is misclassified as 'small'.
    """
    if n <= 10:
        return "small"
    return "large"


def identity(x):
    """Stable helper unaffected by the bug above (used by the regression
    suite to confirm pre-existing behavior)."""
    return x
