import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from pager import page_count, paginate  # noqa: E402


class PagerTests(unittest.TestCase):
    def test_page_count(self):
        self.assertEqual(page_count(0, 10), 0)
        self.assertEqual(page_count(10, 10), 1)
        self.assertEqual(page_count(11, 10), 2)

    def test_rejects_bad_page(self):
        with self.assertRaises(ValueError):
            paginate([1, 2, 3], 0, 2)


if __name__ == "__main__":
    unittest.main()
