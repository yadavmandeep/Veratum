import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from shop.cart import Cart  # noqa: E402


class CartTests(unittest.TestCase):
    def test_single_items(self):
        cart = Cart()
        cart.add("a", 250)
        cart.add("b", 100)
        self.assertEqual(cart.total(), 350)

    def test_discount(self):
        cart = Cart()
        cart.add("a", 1000)
        cart.discount_pct = 15
        self.assertEqual(cart.total(), 850)


if __name__ == "__main__":
    unittest.main()
