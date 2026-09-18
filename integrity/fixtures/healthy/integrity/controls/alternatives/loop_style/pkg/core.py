def classify(n):
    """A structurally different but behaviorally equivalent implementation:
    checks the 'large' branch first instead of the 'small' branch."""
    if n >= 10:
        return "large"
    return "small"


def identity(x):
    return x
