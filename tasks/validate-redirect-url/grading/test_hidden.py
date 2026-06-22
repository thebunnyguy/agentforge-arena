"""Hidden tests: the graded correctness signal. Never mounted in the agent
workspace. The rejection cases fail with the pass-through snapshot and pass only
with an implementation that validates the redirect target."""

import pytest

from saferedirect import safe_redirect

ALLOWED = "app.example.com"


def test_relative_path_ok():
    assert safe_redirect("/dashboard", ALLOWED) == "/dashboard"


def test_relative_path_with_query_ok():
    assert safe_redirect("/p?q=1", ALLOWED) == "/p?q=1"


def test_same_host_absolute_ok():
    url = "https://app.example.com/x"
    assert safe_redirect(url, ALLOWED) == url


def test_external_absolute_raises():
    with pytest.raises(ValueError):
        safe_redirect("https://evil.com/x", ALLOWED)


def test_protocol_relative_raises():
    with pytest.raises(ValueError):
        safe_redirect("//evil.com", ALLOWED)


def test_javascript_scheme_raises():
    with pytest.raises(ValueError):
        safe_redirect("javascript:alert(1)", ALLOWED)


def test_data_scheme_raises():
    with pytest.raises(ValueError):
        safe_redirect("data:text/html,<script>alert(1)</script>", ALLOWED)


def test_hosted_javascript_scheme_raises():
    # "javascript://host/..." parses with a non-empty netloc; the "//host" is a
    # JS line-comment and the payload after %0a (newline) executes. Must reject
    # even though the host equals the allowed host.
    with pytest.raises(ValueError):
        safe_redirect("javascript://app.example.com/%0aalert(1)", ALLOWED)


def test_hosted_data_scheme_raises():
    with pytest.raises(ValueError):
        safe_redirect("data://app.example.com/x", ALLOWED)


def test_non_http_scheme_to_allowed_host_raises():
    # An ftp:// (or any non-http(s)) URL to the allowed host is still not a
    # valid web redirect target.
    with pytest.raises(ValueError):
        safe_redirect("ftp://app.example.com/file", ALLOWED)


def test_http_same_host_absolute_ok():
    url = "http://app.example.com/x"
    assert safe_redirect(url, ALLOWED) == url
