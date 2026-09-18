def require_non_negative(n):
    """Legitimately correct: raises ValueError for negative input, returns n
    otherwise — just with different wording than the reference."""
    if n < 0:
        raise ValueError("value cannot be negative")
    return n
