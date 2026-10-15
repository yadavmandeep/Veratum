import datetime
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dates import parse_date  # noqa: E402


class DateTests(unittest.TestCase):
    def test_iso(self):
        self.assertEqual(parse_date("2024-04-03"), datetime.date(2024, 4, 3))

    def test_garbage(self):
        with self.assertRaises(ValueError):
            parse_date("yesterday")


if __name__ == "__main__":
    unittest.main()
