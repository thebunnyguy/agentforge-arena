"""Order processing pipeline.

``process_order`` WORKS correctly, but it is one tangled function that inlines
validation, subtotal computation, and coupon application all at once.

REFACTOR TASK: extract three standalone functions in this module --
``validate_items(items)``, ``subtotal(items)`` and ``apply_coupon(amount, coupon)``
-- and have ``process_order`` call them, WITHOUT changing ``process_order``'s
observable behavior.
"""

from .money import to_cents


def process_order(items, coupon=None):
    """Validate ``items``, compute the subtotal (in cents), optionally apply a
    ``coupon``, and return a summary dict.

    ``items`` is a non-empty list of dicts, each with a positive numeric
    ``price`` (dollars), a positive integer ``qty`` and a ``name``.

    ``coupon`` is either ``None`` or a dict ``{"type": "percent"|"flat",
    "value": number}``. A percent coupon takes that percentage off the
    subtotal; a flat coupon takes that many cents off. The total never goes
    below zero.

    Returns ``{"item_count": int, "subtotal": int, "total": int}`` with the
    monetary fields expressed in integer cents.
    """
    # --- validation (tangled, inline) ---
    if not isinstance(items, list) or len(items) == 0:
        raise ValueError("items must be a non-empty list")
    for item in items:
        if not isinstance(item, dict):
            raise ValueError("each item must be a dict")
        if "price" not in item or "qty" not in item:
            raise ValueError("each item must have 'price' and 'qty'")
        price = item["price"]
        qty = item["qty"]
        if isinstance(price, bool) or not isinstance(price, (int, float)) or price <= 0:
            raise ValueError("price must be a positive number")
        if isinstance(qty, bool) or not isinstance(qty, int) or qty <= 0:
            raise ValueError("qty must be a positive integer")

    # --- subtotal (tangled, inline) ---
    sub = 0
    for item in items:
        sub += to_cents(item["price"]) * item["qty"]

    # --- coupon (tangled, inline) ---
    total = sub
    if coupon is not None:
        ctype = coupon["type"]
        value = coupon["value"]
        if ctype == "percent":
            total = sub - int(round(sub * value / 100))
        elif ctype == "flat":
            total = sub - int(round(value))
        else:
            raise ValueError("unknown coupon type: {0}".format(ctype))
        if total < 0:
            total = 0

    return {
        "item_count": len(items),
        "subtotal": sub,
        "total": total,
    }
