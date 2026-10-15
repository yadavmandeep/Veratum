# Review of auth.py

- `verify_token`: the signature is compared with `==`, which is not constant-time and leaks timing information. Use `hmac.compare_digest`.
- `verify_token`: a malformed token (wrong number of `:` parts, or a user id containing `:`) makes `token.split(":")` raise ValueError instead of returning None. Use `rsplit(":", 2)` and catch the error.
- `SECRET` is hardcoded in source; load it from configuration / environment.
