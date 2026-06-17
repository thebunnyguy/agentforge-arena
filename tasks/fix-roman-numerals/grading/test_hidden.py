"""Hidden tests: the graded correctness signal. Never mounted in the agent
workspace. The subtractive-notation cases fail with a naive summing parser and
pass only with an implementation that handles subtractive pairs."""

from romankit import from_roman


def test_iv():
    assert from_roman("IV") == 4


def test_ix():
    assert from_roman("IX") == 9


def test_xl():
    assert from_roman("XL") == 40


def test_xc():
    assert from_roman("XC") == 90


def test_cd():
    assert from_roman("CD") == 400


def test_cm():
    assert from_roman("CM") == 900


def test_mcmxciv():
    assert from_roman("MCMXCIV") == 1994


def test_iii():
    assert from_roman("III") == 3


def test_lviii():
    assert from_roman("LVIII") == 58
