from .pricing import calc


class Cart:
    def __init__(self):
        self.lines = []
        self.discount_pct = 0

    def add(self, sku, price_cents, qty=1):
        self.lines.append({"sku": sku, "price_cents": price_cents, "qty": qty})

    def total(self):
        return calc(self.lines, self.discount_pct)
