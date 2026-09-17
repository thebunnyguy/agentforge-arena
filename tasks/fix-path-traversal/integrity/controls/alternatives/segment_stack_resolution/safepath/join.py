import posixpath


def safe_join(base, *parts):
    """Join ``parts`` onto ``base``, guaranteeing the result stays within
    ``base``.

    ALTERNATIVE IMPLEMENTATION: structurally different from the reference.
    Instead of normalizing the *whole joined string* with
    ``posixpath.normpath`` and then string-comparing it against ``base`` as a
    prefix, this resolves ``base``'s own segments plus every part's segments
    onto one explicit list-stack, left to right (the same walk
    ``posixpath.normpath`` performs internally, just spelled out). Only the
    FINAL resolved position is compared against ``base`` -- as a list-prefix
    comparison, not a string ``.startswith`` -- so a transient climb above
    base that comes back down before the walk ends (e.g. ``"..", "data",
    "x"`` against base ``"/srv/data"``, which climbs to ``/srv`` and back
    into ``data/x``) is allowed, exactly like the reference, while a genuine
    net escape (or landing on a same-prefix sibling like ``"/srv/data-other"``)
    is rejected -- and a list-prefix check can never be fooled by a sibling
    directory sharing base's name as a string prefix, the way a bare
    ``str.startswith(base)`` can.

    * An absolute component (e.g. ``"/etc/passwd"``) escapes ``base`` --
      rejected with ``ValueError``, exactly as before.
    * ``".."`` segments that resolve back to somewhere still under ``base``
      are allowed, including a transient climb-out-and-back-in.
    * When ``base`` itself is root (``"/"``), a ``".."`` at/below the floor
      clamps to root (a no-op) rather than erroring, matching
      ``posixpath.normpath``'s ``"/.."`` -> ``"/"`` semantics. For a relative
      base, a ``".."`` that climbs above the floor is tracked and always
      escapes, matching ``posixpath.normpath`` leaving an unresolvable
      leading ``".."`` in a relative result.
    """
    for part in parts:
        if posixpath.isabs(part):
            raise ValueError(
                "absolute component %r would escape base %r" % (part, base)
            )

    norm_base = posixpath.normpath(base)
    is_abs = norm_base.startswith("/")
    base_segments = [s for s in norm_base.split("/") if s and s != "."]

    # Seed the stack with base's own (already-resolved) segments -- they are
    # opaque here, never popped by a part's "..", exactly as the reference
    # never re-resolves base against itself either. Only parts' segments are
    # walked.
    stack = list(base_segments)
    above = 0  # a ".." past the floor, for a relative base with no more to pop
    part_segments = [seg for part in parts for seg in part.split("/")]
    for segment in part_segments:
        if segment in ("", "."):
            continue
        if segment == "..":
            if stack:
                stack.pop()
            elif is_abs:
                pass  # root clamp: ".." at/below "/" is a no-op
            else:
                above += 1
        else:
            stack.append(segment)

    escapes = above > 0 or stack[: len(base_segments)] != base_segments
    if escapes:
        raise ValueError(
            "joined path %r escapes base %r" % ("/".join(stack), base)
        )

    return ("/" if is_abs else "") + "/".join(stack)
