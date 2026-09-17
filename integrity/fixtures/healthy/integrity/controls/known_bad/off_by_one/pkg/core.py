def classify(n):
    """BUG (deliberate, for the integrity engine's known-bad control): uses
    <= instead of <, so 10 is misclassified as 'small'."""
    if n <= 10:
        return "small"
    return "large"


def identity(x):
    return x
