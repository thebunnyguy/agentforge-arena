from urllib.parse import urlparse


def safe_redirect(target, allowed_host):
    """Return ``target`` if it is a safe redirect destination, else raise.

    BUG (known_bad control): the "is this a relative path" check only
    tests ``parsed.scheme`` and forgets to also require an empty
    ``parsed.netloc``, and there is no explicit pre-check rejecting a
    protocol-relative ``"//host"`` target before that. Since
    ``urlparse("//evil.com")`` yields an empty scheme, this treats it as a
    plain relative path (it starts with "/") and returns it unchanged
    instead of raising -- a classic open-redirect bypass.
    """
    if not isinstance(target, str) or not target:
        raise ValueError("redirect target must be a non-empty string")

    parsed = urlparse(target)

    # BUG: should also require `not parsed.netloc` here (or an explicit
    # `target.startswith("//")` guard) to exclude protocol-relative URLs.
    if not parsed.scheme:
        if target.startswith("/"):
            return target
        raise ValueError("redirect target must be an absolute path: %r" % (target,))

    if parsed.scheme not in ("http", "https"):
        raise ValueError("redirect scheme is not allowed: %r" % (target,))

    if not parsed.netloc:
        raise ValueError("redirect target must have a host: %r" % (target,))

    if parsed.hostname != allowed_host:
        raise ValueError(
            "redirect host %r does not match allowed host %r"
            % (parsed.hostname, allowed_host)
        )

    return target
