"""Hidden tests: the graded correctness signal. Never mounted in the agent
workspace. Every case raises NotImplementedError on the stub snapshot and passes
only once mask is implemented to redact the three secret kinds."""

from maskkit import mask


def test_masks_api_key():
    key = "sk-" + "a1b2c3d4e5f6g7h8i9j0"  # 20 alphanumerics after the prefix
    out = mask("token is " + key + " end")
    assert key not in out
    assert "[REDACTED]" in out


def test_masks_bearer_token():
    out = mask("Authorization: Bearer abcdefgh123")
    assert "abcdefgh123" not in out
    assert "Bearer abcdefgh123" not in out
    assert "[REDACTED]" in out


def test_masks_email():
    out = mask("write to a@b.com soon")
    assert "a@b.com" not in out
    assert "[REDACTED]" in out


def test_leaves_ordinary_text_untouched():
    text = "the quick brown fox jumps over the lazy dog"
    assert mask(text) == text


def test_handles_two_secrets_on_one_line():
    line = "mail a@b.com and key sk-" + "0123456789abcdefghij"
    out = mask(line)
    assert "a@b.com" not in out
    assert "sk-0123456789abcdefghij" not in out
    assert out.count("[REDACTED]") >= 2


def test_short_sk_prefix_not_masked():
    # "sk-" followed by fewer than 20 alphanumerics is not an API key.
    text = "sk-tooshort here"
    assert mask(text) == text


def test_masks_whole_bearer_credential_not_just_token():
    # The "Bearer" keyword must be redacted together with the token, not left
    # visible (an impl that masks only the token portion would fail this).
    assert mask("Authorization: Bearer abcdefgh1234") == "Authorization: [REDACTED]"


def test_masks_api_key_glued_to_preceding_word():
    # Semantic property: the spec defines an API key purely as a substring
    # shape -- "'sk-' followed by 20 or more alphanumeric characters" -- with
    # no requirement that a delimiter (space/punctuation/start-of-string)
    # precede the "sk-". A secret is a secret regardless of what character
    # happens to sit immediately before it; pasting one directly against
    # other text (no separator) is exactly the kind of leak masking exists to
    # catch. An implementation that requires a word boundary before "sk-"
    # (e.g. wrapping the pattern in \b) will fail to match here and leave the
    # key exposed.
    key = "sk-" + "a1b2c3d4e5f6g7h8i9j0"  # exactly 20 alphanumerics
    out = mask("leaked" + key + " in the log")
    assert key not in out
    assert out == "leaked[REDACTED] in the log"


def test_masks_bearer_token_glued_to_preceding_word():
    # Same semantic property as above, applied to the bearer-token pattern:
    # the contract never requires whitespace or punctuation before the
    # literal word "Bearer", only that "Bearer <token>" appears as a
    # substring. A \b-anchored implementation fails to redact a credential
    # that is glued directly onto a preceding word with no separator.
    out = mask("xBearer abcdefgh1234")
    assert "abcdefgh1234" not in out
    assert out == "x[REDACTED]"
