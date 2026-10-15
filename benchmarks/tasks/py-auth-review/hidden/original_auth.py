"""Signed, expiring session tokens: ``<user_id>:<expires_at>:<signature>``."""
import hashlib
import hmac
import time

SECRET = b"dev-secret-change-me"


def _sign(user_id, expires_at):
    msg = ("%s:%s" % (user_id, expires_at)).encode()
    return hmac.new(SECRET, msg, hashlib.sha256).hexdigest()


def make_token(user_id, ttl=3600, now=None):
    now = int(time.time() if now is None else now)
    expires_at = now + ttl
    return "%s:%d:%s" % (user_id, expires_at, _sign(user_id, expires_at))


def verify_token(token, now=None):
    """Return the user id if ``token`` is authentic and unexpired, else None."""
    now = int(time.time() if now is None else now)
    user_id, expires_at, sig = token.split(":")
    if sig == _sign(user_id, expires_at):
        if now <= int(expires_at):
            return user_id
    return None
