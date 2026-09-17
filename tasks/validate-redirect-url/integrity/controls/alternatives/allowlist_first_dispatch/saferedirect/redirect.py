from urllib.parse import urlparse

_SAFE_SCHEMES = frozenset({"http", "https"})


def _is_relative_path(target, parsed):
    """A same-app relative path: no scheme, no host, single leading slash
    (not the protocol-relative "//...")."""
    return (
        not parsed.scheme
        and not parsed.netloc
        and target[:1] == "/"
        and target[:2] != "//"
    )


def safe_redirect(target, allowed_host):
    """Return ``target`` if it is a safe redirect destination, else raise.

    ALTERNATIVE (structurally different, behaviorally equivalent to the
    reference): classifies the target into "relative" vs "absolute" up
    front using a small predicate helper and a set-based scheme
    allow-list, instead of the reference's sequential guard clauses.
    """
    if not isinstance(target, str) or not target:
        raise ValueError("redirect target must be a non-empty string")

    parsed = urlparse(target)

    if _is_relative_path(target, parsed):
        return target

    if not parsed.scheme and not parsed.netloc:
        # e.g. "" (already excluded above) or a relative path missing its
        # leading slash.
        raise ValueError("redirect target must be an absolute path: %r" % (target,))

    if target.startswith("//"):
        raise ValueError("protocol-relative redirect is not allowed: %r" % (target,))

    if parsed.scheme.lower() not in _SAFE_SCHEMES:
        raise ValueError("redirect scheme is not allowed: %r" % (target,))

    host = parsed.hostname
    if not host or host != allowed_host:
        raise ValueError(
            "redirect host %r does not match allowed host %r" % (host, allowed_host)
        )

    return target
