"""Regression tests: pre-existing behavior that must keep working. These pass on
the unmodified snapshot AND after a correct fix; a change that breaks them fails
the regression gate (G=0). They exercise only the stable sibling
romankit.render.to_roman and a trivial parse contract true in both versions."""

from romankit import from_roman, to_roman


def test_to_roman_four():
    assert to_roman(4) == "IV"


def test_to_roman_1994():
    assert to_roman(1994) == "MCMXCIV"


def test_to_roman_58():
    assert to_roman(58) == "LVIII"


def test_from_roman_single_numeral_contract():
    assert from_roman("X") == 10
