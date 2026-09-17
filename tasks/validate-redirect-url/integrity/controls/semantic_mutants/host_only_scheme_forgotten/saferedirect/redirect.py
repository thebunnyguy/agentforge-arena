from urllib.parse import urlparse


def safe_redirect(target, allowed_host):
    """Return ``target`` if it is a safe redirect destination, else raise.

    SEMANTIC MUTANT (security-relevant near-miss): a partial fix that
    validates the *netloc/host* but forgets to restrict the URL *scheme*
    to http/https. This reproduces this task's original, since-fixed
    weakness: "javascript://app.example.com/x" and
    "data://app.example.com/x" both parse with a netloc equal to the
    allowed host, so they sail through the host check and are returned
    unchanged -- even though the scheme makes them executable/dangerous,
    not safe web redirects.
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

    # MISSING: no restriction on parsed.scheme here -- any scheme with a
    # matching netloc/host is accepted, including "javascript:" and
    # "data:".
    if not parsed.netloc:
        raise ValueError("redirect target must have a host: %r" % (target,))

    if parsed.hostname != allowed_host:
        raise ValueError(
            "redirect host %r does not match allowed host %r"
            % (parsed.hostname, allowed_host)
        )

    return target
