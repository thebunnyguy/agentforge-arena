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
