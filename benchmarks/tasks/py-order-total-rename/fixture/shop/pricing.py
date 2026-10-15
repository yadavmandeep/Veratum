"""Price calculations. All amounts are integer cents."""


def calc(lines, discount_pct=0):
    """Total of ``lines`` after an order-level percentage discount.

    Each line is a dict with ``price_cents`` and ``qty``.
    """
    if not 0 <= discount_pct <= 100:
        raise ValueError("discount_pct must be between 0 and 100")
    subtotal = sum(line["price_cents"] for line in lines)
    discount = subtotal * discount_pct // 100
    return subtotal - discount
