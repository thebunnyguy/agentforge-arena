import posixpath


def safe_join(base, *parts):
    """Join ``parts`` onto ``base``, rejecting an absolute component or any
    part that contains a literal ``".."`` segment.

    KNOWN-BAD: this checks each *raw* part for a literal ``".."`` token
    instead of normalizing the joined path and comparing it against ``base``.
    That over-rejects a ``".."`` that still resolves within base (e.g.
    ``"reports/../public"``) and never actually verifies containment.
    """
    for part in parts:
        if posixpath.isabs(part):
            raise ValueError(
                "absolute component %r would escape base %r" % (part, base)
            )
        if ".." in part.split("/"):
            raise ValueError("component %r contains a '..' segment" % (part,))

    return posixpath.join(base, *parts)
