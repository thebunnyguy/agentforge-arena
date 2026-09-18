import posixpath


def safe_join(base, *parts):
    """Join ``parts`` onto ``base``, guaranteeing containment -- but signal an
    escape with the wrong exception type.

    KNOWN-BAD: the containment check itself is correct (equivalent to the
    reference), but this raises ``PermissionError`` instead of the
    ``ValueError`` the task spec requires. Callers (and hidden tests) doing
    ``pytest.raises(ValueError)`` will not catch it, so it propagates as an
    unhandled error instead of being treated as an expected rejection.
    """
    norm_base = posixpath.normpath(base)

    for part in parts:
        if posixpath.isabs(part):
            raise PermissionError(
                "absolute component %r would escape base %r" % (part, base)
            )

    joined = posixpath.join(norm_base, *parts)
    norm_joined = posixpath.normpath(joined)

    sep_prefix = norm_base if norm_base == "/" else norm_base + "/"
    if norm_joined != norm_base and not norm_joined.startswith(sep_prefix):
        raise PermissionError(
            "joined path %r escapes base %r" % (norm_joined, norm_base)
        )

    return norm_joined
