"""Hidden tests: DELIBERATELY narrow for this fixture. Covers the empty-name
and length requirements but never the alphanumeric-only requirement — the gap
this fixture's known-bad control (integrity/controls/known_bad/hardcoded/)
exploits to demonstrate a broken oracle."""

from pkg import is_valid_username


def test_empty_is_invalid():
    assert is_valid_username("") is False


def test_too_long_rejected():
    assert is_valid_username("a" * 21) is False


def test_valid_name_accepted():
    assert is_valid_username("abc123") is True
