"""Hidden tests: thoroughly covers the LOWER boundary (age 17 vs 18) but
NEVER tests the upper boundary (120/121) at all — the gap this fixture's
mutation testing should surface as a surviving mutant on the reference's
`if age > 120` check."""

from pkg import is_adult


def test_below_18_is_false():
    assert is_adult(17) is False


def test_exactly_18_is_true():
    assert is_adult(18) is True


def test_adult_is_true():
    assert is_adult(30) is True
