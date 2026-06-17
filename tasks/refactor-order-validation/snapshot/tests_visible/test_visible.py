"""Visible tests: the agent's feedback signal (NOT scored).

These are deliberately weak -- they exercise process_order's happy path but do
NOT check that the three helper functions (validate_items / subtotal /
apply_coupon) exist or are wired in. The hidden tests are what actually grade
the refactor.
"""

from orderkit import process_order


def test_process_order_basic_total():
    out = process_order([{"name": "a", "price": 1.0, "qty": 2}])
    assert out["total"] == 200


def test_process_order_returns_dict():
    out = process_order([{"name": "a", "price": 2.5, "qty": 1}])
    assert isinstance(out, dict)
