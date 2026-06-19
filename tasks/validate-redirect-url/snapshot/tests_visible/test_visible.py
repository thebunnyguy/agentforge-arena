"""Visible tests: the agent's feedback signal (NOT scored).

These are deliberately weak — they pass even with the buggy pass-through
implementation — to demonstrate why hidden tests are what actually grade.
"""

from saferedirect import safe_redirect


def test_relative_path_returned():
    assert safe_redirect("/dashboard", "app.example.com") == "/dashboard"


def test_same_host_absolute_returned():
    url = "https://app.example.com/profile"
    assert safe_redirect(url, "app.example.com") == url
