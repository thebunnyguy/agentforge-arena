"""Hidden tests: the graded correctness signal. Never mounted in the agent
workspace.

These import the three functions the refactor must extract --
``validate_items``, ``subtotal`` and ``apply_coupon`` -- which do NOT exist in
the unmodified snapshot, so the import-dependent tests fail until the refactor
adds them. They also confirm that ``process_order`` still returns the same
totals (behavior unchanged) and is wired through the new helpers."""

import pytest

from orderkit.process import (
    validate_items,
    subtotal,
    apply_coupon,
    process_order,
)


# --- validate_items ---------------------------------------------------------

def test_validate_items_accepts_good_input():
    # Returns None (or any falsy/non-raising result) on valid input.
    validate_items([{"name": "a", "price": 1.0, "qty": 1}])


def test_validate_items_rejects_empty():
    with pytest.raises(ValueError):
        validate_items([])


def test_validate_items_rejects_non_list():
    with pytest.raises(ValueError):
        validate_items("not a list")


def test_validate_items_rejects_bad_price():
    with pytest.raises(ValueError):
        validate_items([{"name": "a", "price": 0, "qty": 1}])
    with pytest.raises(ValueError):
        validate_items([{"name": "a", "price": -3.0, "qty": 1}])


def test_validate_items_rejects_bad_qty():
    with pytest.raises(ValueError):
        validate_items([{"name": "a", "price": 1.0, "qty": 0}])
    with pytest.raises(ValueError):
        validate_items([{"name": "a", "price": 1.0, "qty": 1.5}])


def test_validate_items_rejects_missing_keys():
    with pytest.raises(ValueError):
        validate_items([{"name": "a", "price": 1.0}])


# --- subtotal ---------------------------------------------------------------

def test_subtotal_single_item():
    assert subtotal([{"name": "a", "price": 1.0, "qty": 2}]) == 200


def test_subtotal_multiple_items():
    items = [
        {"name": "a", "price": 1.50, "qty": 2},
        {"name": "b", "price": 0.99, "qty": 3},
    ]
    assert subtotal(items) == 300 + 297


def test_subtotal_returns_int_cents():
    out = subtotal([{"name": "a", "price": 2.5, "qty": 4}])
    assert isinstance(out, int)
    assert out == 1000


# --- apply_coupon -----------------------------------------------------------

def test_apply_coupon_none_is_noop():
    assert apply_coupon(1000, None) == 1000


def test_apply_coupon_percent():
    assert apply_coupon(1000, {"type": "percent", "value": 10}) == 900


def test_apply_coupon_flat():
    assert apply_coupon(1000, {"type": "flat", "value": 250}) == 750


def test_apply_coupon_clamps_at_zero():
    assert apply_coupon(500, {"type": "flat", "value": 800}) == 0


def test_apply_coupon_unknown_type_raises():
    with pytest.raises(ValueError):
        apply_coupon(1000, {"type": "mystery", "value": 5})


# --- process_order still behaves identically --------------------------------

def test_process_order_total_unchanged_no_coupon():
    items = [
        {"name": "a", "price": 1.50, "qty": 2},
        {"name": "b", "price": 0.99, "qty": 3},
    ]
    out = process_order(items)
    assert out == {"item_count": 2, "subtotal": 597, "total": 597}


def test_process_order_total_unchanged_percent_coupon():
    items = [{"name": "a", "price": 10.0, "qty": 1}]
    out = process_order(items, coupon={"type": "percent", "value": 25})
    assert out == {"item_count": 1, "subtotal": 1000, "total": 750}


def test_process_order_total_unchanged_flat_coupon():
    items = [{"name": "a", "price": 5.0, "qty": 2}]
    out = process_order(items, coupon={"type": "flat", "value": 300})
    assert out == {"item_count": 1, "subtotal": 1000, "total": 700}


def test_process_order_still_validates():
    with pytest.raises(ValueError):
        process_order([])
