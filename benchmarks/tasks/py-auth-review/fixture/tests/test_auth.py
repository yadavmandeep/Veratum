import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from auth import make_token, verify_token  # noqa: E402


class AuthTests(unittest.TestCase):
    def test_roundtrip(self):
        token = make_token("alice", ttl=60, now=1000)
        self.assertEqual(verify_token(token, now=1030), "alice")

    def test_expired(self):
        token = make_token("alice", ttl=60, now=1000)
        self.assertIsNone(verify_token(token, now=2000))


if __name__ == "__main__":
    unittest.main()
