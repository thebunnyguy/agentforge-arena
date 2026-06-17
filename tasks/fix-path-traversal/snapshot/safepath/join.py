import posixpath


def safe_join(base, *parts):
    """Join ``parts`` onto ``base`` and return the resulting path.

    The result must stay *within* ``base``. If any part would cause the joined
    path to escape ``base`` (for example via a ``".."`` component or an absolute
    component such as ``"/etc/passwd"``), a ``ValueError`` must be raised.

    BUG: this implementation naively delegates to ``posixpath.join`` and does no
    containment check. ``posixpath.join`` resets to the last absolute component,
    and ``".."`` segments are left in place, so callers can escape ``base``.
    """
    return posixpath.join(base, *parts)
