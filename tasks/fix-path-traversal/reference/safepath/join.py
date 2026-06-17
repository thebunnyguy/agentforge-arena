import posixpath


def safe_join(base, *parts):
    """Join ``parts`` onto ``base`` and return the resulting path, guaranteeing
    the result stays within ``base``.

    Containment is enforced with pure ``posixpath`` string logic (no real
    filesystem access):

    * An absolute component (e.g. ``"/etc/passwd"``) would reset the join and
      escape ``base`` — rejected with ``ValueError``.
    * After normalizing the joined path, it must equal ``base`` or live strictly
      beneath it; otherwise ``".."`` segments escaped ``base`` — ``ValueError``.

    ``".."`` segments that resolve back to somewhere still under ``base`` (e.g.
    ``"reports/../public"``) are allowed.
    """
    norm_base = posixpath.normpath(base)

    for part in parts:
        if posixpath.isabs(part):
            raise ValueError(
                "absolute component %r would escape base %r" % (part, base)
            )

    joined = posixpath.join(norm_base, *parts)
    norm_joined = posixpath.normpath(joined)

    if norm_joined != norm_base and not norm_joined.startswith(norm_base + "/"):
        raise ValueError(
            "joined path %r escapes base %r" % (norm_joined, norm_base)
        )

    return norm_joined
