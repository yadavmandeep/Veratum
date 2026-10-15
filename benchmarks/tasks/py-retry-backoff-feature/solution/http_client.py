"""Tiny retry wrapper around an injectable fetch function."""
import time


class TransientError(Exception):
    """A failure that is worth retrying (timeouts, 503s, ...)."""


class RetryExhausted(TransientError):
    """Every attempt failed with a TransientError."""

    def __init__(self, attempts, last_error):
        super().__init__("gave up after %d attempts: %s" % (attempts, last_error))
        self.attempts = attempts
        self.last_error = last_error


def fetch_with_retry(fetch, url, attempts=3, *, base_delay=0.1, sleep=time.sleep):
    """Call ``fetch(url)`` up to ``attempts`` times on TransientError."""
    if attempts < 1:
        raise ValueError("attempts must be >= 1")
    last = None
    for n in range(attempts):
        if n:
            sleep(base_delay * 2 ** (n - 1))
        try:
            return fetch(url)
        except TransientError as exc:
            last = exc
    raise RetryExhausted(attempts, last) from last
