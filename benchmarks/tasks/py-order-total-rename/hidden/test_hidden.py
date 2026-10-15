import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import shop  # noqa: E402
from shop import cli, pricing  # noqa: E402
from shop.cart import Cart  # noqa: E402


class HiddenOrderTests(unittest.TestCase):
    def test_quantity_counted(self):
        lines = [{"price_cents": 250, "qty": 2}, {"price_cents": 100, "qty": 1}]
        self.assertEqual(pricing.compute_total(lines), 600)
        self.assertEqual(pricing.compute_total(lines, 50), 300)

    def test_discount_validation_kept(self):
        with self.assertRaises(ValueError):
            pricing.compute_total([], 101)

    def test_old_name_removed(self):
        self.assertFalse(hasattr(pricing, "calc"))
        self.assertFalse(hasattr(shop, "calc"))
        self.assertIs(shop.compute_total, pricing.compute_total)

    def test_cart(self):
        cart = Cart()
        cart.add("a", 250, qty=3)
        cart.add("b", 100)
        cart.discount_pct = 10
        self.assertEqual(cart.total(), 765)

    def test_cli(self):
        self.assertEqual(cli.main(["250x2", "100"]), "6.00")
        self.assertEqual(cli.main(["1000x3", "--discount", "10"]), "27.00")


if __name__ == "__main__":
    unittest.main()
