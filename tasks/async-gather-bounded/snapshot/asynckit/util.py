def chunk(seq, size):
    """Split ``seq`` into consecutive lists of length ``size``.

    The final chunk may be shorter if ``len(seq)`` is not a multiple of
    ``size``. ``size`` must be a positive integer.
    """
    if size <= 0:
        raise ValueError("size must be a positive integer")
    return [list(seq[i:i + size]) for i in range(0, len(seq), size)]
