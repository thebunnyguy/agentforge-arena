"""Order processing pipeline (refactored).

``process_order`` now delegates to three standalone, independently-testable
helpers -- ``validate_items``, ``subtotal`` and ``apply_coupon`` -- while
preserving its exact observable behavior.
"""

from .money import to_cents


def validate_items(items):
    """Validate the ``items`` payload, raising ``ValueError`` on bad input.

    ``items`` must be a non-empty list of dicts, each carrying a positive
    numeric ``price`` (dollars) and a positive integer ``qty``.
    """
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


def subtotal(items):
    """Return the subtotal of ``items`` in integer cents (price * qty summed)."""
    sub = 0
    for item in items:
        sub += to_cents(item["price"]) * item["qty"]
    return sub


def apply_coupon(amount, coupon):
    """Apply ``coupon`` to ``amount`` (in cents) and return the new amount.

    ``coupon`` is ``None`` (no change) or ``{"type": "percent"|"flat",
    "value": number}``. The result never goes below zero.
    """
    if coupon is None:
        return amount
    ctype = coupon["type"]
    value = coupon["value"]
    if ctype == "percent":
        total = amount - int(round(amount * value / 100))
    elif ctype == "flat":
        total = amount - int(round(value))
    else:
        raise ValueError("unknown coupon type: {0}".format(ctype))
    if total < 0:
        total = 0
    return total


def process_order(items, coupon=None):
    """Validate ``items``, compute the subtotal (in cents), optionally apply a
    ``coupon``, and return a summary dict.

    Behavior is identical to the original tangled implementation; this version
    simply delegates to ``validate_items``, ``subtotal`` and ``apply_coupon``.

    Returns ``{"item_count": int, "subtotal": int, "total": int}`` with the
    monetary fields expressed in integer cents.
    """
    validate_items(items)
    sub = subtotal(items)
    total = apply_coupon(sub, coupon)
    return {
        "item_count": len(items),
        "subtotal": sub,
        "total": total,
    }
