import datetime
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import legacy_report  # noqa: E402
from dates import parse_date  # noqa: E402


class HiddenDateTests(unittest.TestCase):
    def test_day_first(self):
        self.assertEqual(parse_date("03/04/2024"), datetime.date(2024, 4, 3))
        self.assertEqual(parse_date("31/12/1999"), datetime.date(1999, 12, 31))
        self.assertEqual(parse_date(" 1/2/2020 "), datetime.date(2020, 2, 1))

    def test_iso_unchanged(self):
        self.assertEqual(parse_date("2024-04-03"), datetime.date(2024, 4, 3))

    def test_invalid(self):
        for bad in ("31/02/2024", "12/13/2024", "nonsense"):
            with self.assertRaises(ValueError, msg=bad):
                parse_date(bad)


class HiddenLegacyReportTests(unittest.TestCase):
    """Pinned byte-for-byte: a fixed-width downstream parser depends on it."""

    def test_report_bytes(self):
        out = legacy_report.format_report([("alice", 1200, "X1"), ("a-very-long-name-here", 5, "REF123")])
        self.assertEqual(
            out,
            "alice       |     1200|X1     \n"
            "a-very-long-|        5|REF123 \n"
            "==============================\n",
        )

    def test_row(self):
        self.assertEqual(legacy_report.format_row("bob", 7, "R"), "bob         |        7|R      ")


if __name__ == "__main__":
    unittest.main()
