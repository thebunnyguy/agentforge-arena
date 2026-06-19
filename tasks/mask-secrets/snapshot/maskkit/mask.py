REDACTED = "[REDACTED]"


def mask(text):
    """Return ``text`` with secrets replaced by the literal ``"[REDACTED]"``.

    Three kinds of secret must be redacted:

    * an API key matching ``"sk-"`` followed by 20 or more alphanumeric
      characters,
    * a bearer token of the form ``"Bearer <token>"`` where ``<token>`` is 8 or
      more characters (the whole ``"Bearer <token>"`` becomes ``"[REDACTED]"``),
    * email addresses.

    Ordinary text must be returned unchanged. Use the ``re`` module only.

    STUB: not implemented yet.
    """
    raise NotImplementedError("mask is not implemented yet")
