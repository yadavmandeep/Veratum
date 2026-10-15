import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from http_client import TransientError, fetch_with_retry  # noqa: E402


def flaky(failures, value="ok"):
    state = {"calls": 0}

    def fetch(url):
        state["calls"] += 1
        if state["calls"] <= failures:
            raise TransientError("boom %d" % state["calls"])
        return value

    return fetch, state


class RetryTests(unittest.TestCase):
    def test_first_try(self):
        fetch, state = flaky(0)
        self.assertEqual(fetch_with_retry(fetch, "u"), "ok")
        self.assertEqual(state["calls"], 1)

    def test_eventually_succeeds(self):
        fetch, state = flaky(2)
        self.assertEqual(fetch_with_retry(fetch, "u", sleep=lambda s: None), "ok")
        self.assertEqual(state["calls"], 3)


if __name__ == "__main__":
    unittest.main()
