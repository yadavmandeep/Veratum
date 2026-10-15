import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import http_client  # noqa: E402
from http_client import TransientError, fetch_with_retry  # noqa: E402


def flaky(failures, value="ok", exc=TransientError):
    state = {"calls": 0}

    def fetch(url):
        state["calls"] += 1
        if state["calls"] <= failures:
            raise exc("boom %d" % state["calls"])
        return value

    return fetch, state


class HiddenRetryTests(unittest.TestCase):
    def test_backoff_schedule(self):
        sleeps = []
        fetch, state = flaky(3)
        result = fetch_with_retry(fetch, "u", 4, base_delay=0.5, sleep=sleeps.append)
        self.assertEqual(result, "ok")
        self.assertEqual(state["calls"], 4)
        self.assertEqual(sleeps, [0.5, 1.0, 2.0])

    def test_default_base_delay(self):
        sleeps = []
        fetch, _ = flaky(1)
        fetch_with_retry(fetch, "u", sleep=sleeps.append)
        self.assertEqual(sleeps, [0.1])

    def test_exhausted(self):
        sleeps = []
        fetch, state = flaky(10)
        with self.assertRaises(http_client.RetryExhausted) as ctx:
            fetch_with_retry(fetch, "u", 3, base_delay=1, sleep=sleeps.append)
        err = ctx.exception
        self.assertIsInstance(err, TransientError)
        self.assertEqual(err.attempts, 3)
        self.assertIsInstance(err.last_error, TransientError)
        self.assertEqual(str(err.last_error), "boom 3")
        self.assertIs(err.__cause__, err.last_error)
        self.assertEqual(state["calls"], 3)
        self.assertEqual(sleeps, [1, 2])

    def test_non_transient_propagates(self):
        sleeps = []
        fetch, state = flaky(5, exc=KeyError)
        with self.assertRaises(KeyError):
            fetch_with_retry(fetch, "u", 3, sleep=sleeps.append)
        self.assertEqual(state["calls"], 1)
        self.assertEqual(sleeps, [])

    def test_keyword_only(self):
        fetch, _ = flaky(0)
        with self.assertRaises(TypeError):
            fetch_with_retry(fetch, "u", 3, 0.1)

    def test_positional_attempts_compat(self):
        fetch, state = flaky(4)
        self.assertEqual(fetch_with_retry(fetch, "u", 5, sleep=lambda s: None), "ok")
        self.assertEqual(state["calls"], 5)


if __name__ == "__main__":
    unittest.main()
