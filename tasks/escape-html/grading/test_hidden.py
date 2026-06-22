"""Hidden tests: the graded correctness signal. Never mounted in the agent
workspace. The ampersand and quote cases fail with the snapshot (which forgets
``&`` and the quotes) and pass only with a complete, ampersand-first escape."""

from htmlesc import escape


def test_escapes_angle_brackets():
    assert escape("<script>") == "&lt;script&gt;"


def test_escapes_bare_ampersand():
    assert escape("&") == "&amp;"


def test_ampersand_first_no_double_escape():
    # "&" must be escaped before "<"/">" so the entities are not re-escaped.
    assert escape("<&>") == "&lt;&amp;&gt;"


def test_escapes_double_quote():
    assert escape('"') == "&quot;"


def test_escapes_single_quote():
    assert escape("'") == "&#x27;"


def test_empty_string():
    assert escape("") == ""


def test_combined_attribute_value():
    assert escape('a&b<c>"d\'') == "a&amp;b&lt;c&gt;&quot;d&#x27;"


def test_escapes_repeated_occurrences():
    # Every occurrence of a special character must be escaped, not just the first
    # (a str.replace(..., 1) variant would pass the single-occurrence tests).
    assert escape("a<b>c<d>") == "a&lt;b&gt;c&lt;d&gt;"


def test_escapes_repeated_ampersands_and_brackets():
    assert escape("<<") == "&lt;&lt;"
    assert escape("&&") == "&amp;&amp;"
    assert escape("''") == "&#x27;&#x27;"
    assert escape('""') == "&quot;&quot;"
