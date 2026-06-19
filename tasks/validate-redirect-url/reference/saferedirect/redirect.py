from urllib.parse import urlparse


def safe_redirect(target, allowed_host):
    """Return ``target`` if it is a safe redirect destination, else raise.

    A redirect is safe when it is either:

    * a relative path that begins with a single ``"/"`` (e.g. ``"/dashboard"``),
      but NOT a protocol-relative ``"//evil.com"``, or
    * an absolute URL whose network location (host) equals ``allowed_host``.

    Anything else — an external absolute URL, a protocol-relative ``"//host"``,
    or a dangerous scheme such as ``"javascript:"`` or ``"data:"`` — raises
    ``ValueError``. Parsing uses ``urllib.parse.urlparse`` and pure string logic
    (no network access).
    """
    if not isinstance(target, str) or not target:
        raise ValueError("redirect target must be a non-empty string")

    # Protocol-relative URLs ("//evil.com/...") are parsed with an empty scheme
    # but a non-empty netloc; reject them explicitly before the relative check.
    if target.startswith("//"):
        raise ValueError("protocol-relative redirect is not allowed: %r" % (target,))

    parsed = urlparse(target)

    # Relative path: no scheme, no host, and an absolute-style leading slash.
    if not parsed.scheme and not parsed.netloc:
        if target.startswith("/"):
            return target
        raise ValueError("redirect target must be an absolute path: %r" % (target,))

    # A scheme without a host (e.g. "javascript:..." or "data:...") is dangerous.
    if not parsed.netloc:
        raise ValueError("redirect scheme is not allowed: %r" % (target,))

    # Absolute URL: the host must match the allowed host exactly.
    if parsed.hostname != allowed_host:
        raise ValueError(
            "redirect host %r does not match allowed host %r"
            % (parsed.hostname, allowed_host)
        )

    return target
