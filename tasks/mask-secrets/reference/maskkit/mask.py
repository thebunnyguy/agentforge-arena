import re

REDACTED = "[REDACTED]"

# An API key: literal "sk-" followed by 20 or more alphanumeric characters.
_API_KEY = re.compile(r"sk-[A-Za-z0-9]{20,}")

# A bearer token: the word "Bearer", whitespace, then an 8+ char token. The
# whole "Bearer <token>" span is redacted.
_BEARER = re.compile(r"Bearer\s+\S{8,}")

# A pragmatic email address matcher.
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")


def mask(text):
    """Return ``text`` with secrets replaced by the literal ``"[REDACTED]"``.

    Redacts API keys (``"sk-"`` + 20+ alphanumerics), bearer tokens
    (``"Bearer <token>"`` with an 8+ char token), and email addresses, using the
    ``re`` module only. Ordinary text is returned unchanged.
    """
    text = _API_KEY.sub(REDACTED, text)
    text = _BEARER.sub(REDACTED, text)
    text = _EMAIL.sub(REDACTED, text)
    return text
