import re

REDACTED = "[REDACTED]"

_API_KEY = re.compile(r"sk-[A-Za-z0-9]{20,}")
_BEARER = re.compile(r"Bearer\s+\S{8,}")
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

_PATTERNS = (_API_KEY, _BEARER, _EMAIL)


def mask(text):
    """Return ``text`` with secrets replaced by the literal ``"[REDACTED]"``.

    Structurally different from the sequential-substitution reference: collect
    every match span from every pattern first, merge overlapping/adjacent
    spans, then rebuild the string in a single pass around the merged spans.
    """
    spans = []
    for pattern in _PATTERNS:
        for match in pattern.finditer(text):
            spans.append((match.start(), match.end()))

    if not spans:
        return text

    spans.sort()
    merged = [spans[0]]
    for start, end in spans[1:]:
        last_start, last_end = merged[-1]
        if start <= last_end:
            merged[-1] = (last_start, max(last_end, end))
        else:
            merged.append((start, end))

    pieces = []
    cursor = 0
    for start, end in merged:
        pieces.append(text[cursor:start])
        pieces.append(REDACTED)
        cursor = end
    pieces.append(text[cursor:])
    return "".join(pieces)
