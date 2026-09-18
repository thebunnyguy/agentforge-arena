import posixpath


def safe_join(base, *parts):
    """Join ``parts`` onto ``base``, enforcing containment.

    SEMANTIC MUTANT: containment is checked with a naive
    ``norm_joined.startswith(norm_base)`` and no trailing-separator guard.
    This reintroduces the historical prefix-collision bug: a sibling
    directory that merely shares base's name as a string prefix (e.g.
    ``"/srv/data-other"`` against base ``"/srv/data"``) is wrongly accepted
    as "under" base, because the string comparison alone can't tell a real
    subdirectory from a same-prefix sibling.
    """
    norm_base = posixpath.normpath(base)

    for part in parts:
        if posixpath.isabs(part):
            raise ValueError(
                "absolute component %r would escape base %r" % (part, base)
            )

    joined = posixpath.join(norm_base, *parts)
    norm_joined = posixpath.normpath(joined)

    if norm_joined != norm_base and not norm_joined.startswith(norm_base):
        raise ValueError(
            "joined path %r escapes base %r" % (norm_joined, norm_base)
        )

    return norm_joined
