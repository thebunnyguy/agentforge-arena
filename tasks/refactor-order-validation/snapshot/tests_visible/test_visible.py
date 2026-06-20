"""Visible tests: the agent's feedback signal (NOT scored).

These exercise stable public behavior but do NOT reveal the hidden helper-
delegation probes that actually grade the refactor.
"""

from orderkit import process_order

import pytest


def test_process_order_basic_total():
    out = process_order([{"name": "a", "price": 1.0, "qty": 2}])
    assert out == {"item_count": 1, "subtotal": 200, "total": 200}


def test_process_order_returns_dict():
    out = process_order([{"name": "a", "price": 2.5, "qty": 1}])
    assert isinstance(out, dict)


def test_process_order_rejects_empty_items():
    with pytest.raises(ValueError):
        process_order([])
