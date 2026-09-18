import posixpath


def safe_join(base, *parts):
    """Join ``parts`` onto ``base``, rejecting an absolute component or a
    normalized result that still contains a literal ``".."`` token.

    KNOWN-BAD: normalizing first and then checking for a leftover ``".."``
    token is not a containment check. ``posixpath.normpath`` resolves every
    ``".."`` it can for an absolute path, so a traversal like
    ``"../etc/passwd"`` normalizes cleanly to an in-tree-looking path with no
    ``".."`` left to detect, and this silently accepts it -- it never compares
    the result against ``base`` at all.
    """
    for part in parts:
        if posixpath.isabs(part):
            raise ValueError(
                "absolute component %r would escape base %r" % (part, base)
            )

    joined = posixpath.join(base, *parts)
    normalized = posixpath.normpath(joined)

    if ".." in normalized.split("/"):
        raise ValueError("joined path %r still contains '..'" % (normalized,))

    return normalized
