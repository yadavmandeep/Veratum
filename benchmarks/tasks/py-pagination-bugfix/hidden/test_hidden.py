import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pager import page_count, paginate  # noqa: E402


class HiddenPagerTests(unittest.TestCase):
    def walk(self, items, per_page):
        out = []
        for page in range(1, page_count(len(items), per_page) + 1):
            out.extend(paginate(items, page, per_page))
        return out

    def test_walk_returns_every_item(self):
        items = list(range(23))
        for per_page in (1, 2, 5, 10, 23, 50):
            self.assertEqual(self.walk(items, per_page), items, per_page)

    def test_page_sizes(self):
        items = list(range(7))
        self.assertEqual(paginate(items, 1, 3), [0, 1, 2])
        self.assertEqual(paginate(items, 3, 3), [6])
        self.assertEqual(paginate(items, 4, 3), [])

    def test_validation_kept(self):
        with self.assertRaises(ValueError):
            paginate([1], 0, 1)
        with self.assertRaises(ValueError):
            paginate([1], 1, 0)
        self.assertEqual(page_count(0, 5), 0)


if __name__ == "__main__":
    unittest.main()
