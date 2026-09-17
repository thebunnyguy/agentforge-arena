def require_non_negative(n):
    if n < 0:
        raise ValueError("n must be non-negative")
    return n
