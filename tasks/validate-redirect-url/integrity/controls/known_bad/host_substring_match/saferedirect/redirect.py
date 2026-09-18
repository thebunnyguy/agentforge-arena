from urllib.parse import urlparse


def safe_redirect(target, allowed_host):
    """Return ``target`` if it is a safe redirect destination, else raise.

    BUG (known_bad control): matches the host with substring containment
    (``allowed_host in hostname``) instead of exact equality. This wrongly
    accepts any host that merely *contains* the allowed host as a
    substring, e.g. "app.example.com.evil.com" (a domain the attacker
    fully controls), not just the allowed host itself.
    """
    if not isinstance(target, str) or not target:
        raise ValueError("redirect target must be a non-empty string")

    if target.startswith("//"):
        raise ValueError("protocol-relative redirect is not allowed: %r" % (target,))

    parsed = urlparse(target)

    if not parsed.scheme and not parsed.netloc:
        if target.startswith("/"):
            return target
        raise ValueError("redirect target must be an absolute path: %r" % (target,))

    if parsed.scheme not in ("http", "https"):
        raise ValueError("redirect scheme is not allowed: %r" % (target,))

    if not parsed.netloc:
        raise ValueError("redirect target must have a host: %r" % (target,))

    # BUG: containment instead of exact match.
    if allowed_host not in (parsed.hostname or ""):
        raise ValueError(
            "redirect host %r does not match allowed host %r"
            % (parsed.hostname, allowed_host)
        )

    return target
