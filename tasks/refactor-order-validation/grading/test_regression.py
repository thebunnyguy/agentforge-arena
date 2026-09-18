"""Regression tests: pre-existing behavior that must keep working. These pass on
the unmodified snapshot AND after a correct refactor; a change that alters
process_order's observable behavior fails the regression gate (G=0).

These pin process_order's input/output contract (the stable behavior under
refactor) plus the already-correct money helpers. They deliberately do NOT
import the to-be-extracted helpers."""

from orderkit import process_order, to_cents, format_cents

import pytest


def test_process_order_no_coupon_totals():
    items = [
        {"name": "widget", "price": 2.00, "qty": 3},
        {"name": "gadget", "price": 0.50, "qty": 4},
    ]
    out = process_order(items)
    assert out == {"item_count": 2, "subtotal": 800, "total": 800}


def test_process_order_percent_coupon_totals():
    items = [{"name": "widget", "price": 20.0, "qty": 1}]
    out = process_order(items, coupon={"type": "percent", "value": 50})
    assert out == {"item_count": 1, "subtotal": 2000, "total": 1000}


def test_process_order_flat_coupon_totals():
    items = [{"name": "widget", "price": 8.0, "qty": 1}]
    out = process_order(items, coupon={"type": "flat", "value": 199})
    assert out == {"item_count": 1, "subtotal": 800, "total": 601}


def test_process_order_rejects_empty_list():
    try:
        process_order([])
    except ValueError:
        pass
    else:
        raise AssertionError("expected ValueError on empty items")


def test_money_helpers_unchanged():
    assert to_cents(1.0) == 100
    assert to_cents(2.5) == 250
    assert format_cents(1099) == "$10.99"
    assert format_cents(5) == "$0.05"
    # SEMANTIC PROPERTY: format_cents must split cents into a whole-dollar
    # part (cents // 100) and a remainder part (cents % 100), each divided/
    # modded by the same base (100 cents per dollar, per the "$D.CC" contract
    # in reference/orderkit/money.py's docstring). Values at and above a full
    # dollar are needed to pin this down: an implementation that silently
    # divides the dollar part by a different constant still matches on many
    # sub-dollar inputs (it only affects the quotient), but corrupts amounts
    # of a dollar or more.
    assert format_cents(0) == "$0.00"
    assert format_cents(100) == "$1.00"
    assert format_cents(10000) == "$100.00"


@pytest.mark.parametrize(
    "items",
    [
        "not-a-list",
        ["not-a-dict"],
        [{"name": "x", "price": True, "qty": 1}],
        [{"name": "x", "price": 1.0, "qty": True}],
    ],
)
def test_process_order_invalid_item_contract_unchanged(items):
    with pytest.raises(ValueError):
        process_order(items)


def test_process_order_unknown_coupon_contract_unchanged():
    items = [{"name": "widget", "price": 5.0, "qty": 1}]
    with pytest.raises(ValueError, match="unknown coupon type"):
        process_order(items, {"type": "mystery", "value": 1})
