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


def test_host_containing_allowed_host_as_substring_raises():
    # Semantic property: "host equals allowed_host" means EXACT string
    # equality, not "allowed_host appears somewhere in host". A hostname
    # that merely *contains* the allowed host -- as a dot-separated
    # superstring domain fully owned by an attacker -- must still be
    # rejected. "app.example.com.evil.com" is a real, DNS-registrable
    # domain distinct from "app.example.com"; an implementation that
    # checks containment (`allowed_host in hostname`) instead of equality
    # wrongly treats it as the allowed host.
    with pytest.raises(ValueError):
        safe_redirect("https://app.example.com.evil.com/x", ALLOWED)


def test_host_with_allowed_host_as_bare_prefix_raises():
    # Same exact-equality property as above, exercised via a second,
    # structurally different substring shape: the allowed host appears as
    # a plain prefix with no separator at all ("app.example.comX"), not
    # just as a dot-separated superstring domain. Any hostname differing
    # from allowed_host in any way -- prefix, suffix, or containment --
    # is a different host and must be rejected.
    with pytest.raises(ValueError):
        safe_redirect("https://app.example.comx.attacker.net/x", ALLOWED)


def test_non_string_target_raises():
    # Semantic property: safe_redirect's contract is defined purely in
    # terms of URL-shaped strings ("a relative path...", "an absolute
    # URL..."); a non-string target matches neither safe form, so per the
    # docstring's "Anything else ... raises ValueError" clause it must be
    # rejected the same controlled way as any other unsafe target -- not
    # crash with an unrelated exception type (e.g. AttributeError from
    # calling a str method on a non-str object). Covers both a falsy
    # non-string (None) and a truthy one (an int) since an implementation
    # could special-case only one.
    with pytest.raises(ValueError):
        safe_redirect(None, ALLOWED)
    with pytest.raises(ValueError):
        safe_redirect(12345, ALLOWED)


def test_multi_slash_protocol_relative_raises():
    # Semantic property: the docstring's safe relative-path form is "a
    # relative path that begins with a single '/'" -- explicitly NOT
    # protocol-relative. Protocol-relative is the general class of "two
    # or more leading slashes", of which "//evil.com" is just the
    # canonical example; urlparse alone does not reliably signal this for
    # 3+ leading slashes (e.g. urlparse("///evil.com") yields an EMPTY
    # netloc, putting "evil.com" into .path instead), so an
    # implementation must not rely on "netloc happens to be non-empty" to
    # detect this class. Any target starting with 2+ slashes must raise,
    # regardless of the exact count.
    with pytest.raises(ValueError):
        safe_redirect("///evil.com", ALLOWED)
    with pytest.raises(ValueError):
        safe_redirect("////evil.com", ALLOWED)


def test_relative_path_without_leading_slash_raises():
    # Semantic property: the contract returns target "only when" it is
    # one of exactly two safe forms -- a relative path beginning with a
    # single '/', or an absolute URL with a matching host. A schemeless,
    # hostless string that does NOT start with '/' (an ordinary
    # document-relative reference) is neither form and must raise, not be
    # returned unchanged.
    with pytest.raises(ValueError):
        safe_redirect("relative/path", ALLOWED)
