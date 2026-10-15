"""Tiny retry wrapper around an injectable fetch function."""


class TransientError(Exception):
    """A failure that is worth retrying (timeouts, 503s, ...)."""


def fetch_with_retry(fetch, url, attempts=3):
    """Call ``fetch(url)`` up to ``attempts`` times on TransientError."""
    if attempts < 1:
        raise ValueError("attempts must be >= 1")
    last = None
    for _ in range(attempts):
        try:
            return fetch(url)
        except TransientError as exc:
            last = exc
    raise last
