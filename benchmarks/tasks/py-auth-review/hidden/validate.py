"""Hidden validator for a review task.

Passes when REVIEW.md identifies the planted timing-attack issue plus at least
one more planted issue, and auth.py is byte-identical to the original.
Keyword rubrics are a coarse proxy for review quality; see benchmarks/README.md.
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.dirname(os.path.abspath(__file__))

ISSUES = {
    "timing": [r"compare_digest", r"constant[- ]time", r"timing"],
    "malformed": [r"malformed", r"unpack", r"split", r"ValueError", r"rsplit", r"crash"],
    "secret": [r"hard-?coded", r"in (the )?source", r"environment variable", r"\benv\b"],
}
REQUIRED = {"timing"}
MIN_FOUND = 2


def main():
    failures = []
    review_path = os.path.join(ROOT, "REVIEW.md")
    if not os.path.isfile(review_path):
        print("FAIL: REVIEW.md missing")
        return 1
    with open(review_path, encoding="utf-8", errors="replace") as fh:
        review = fh.read()
    found = {name for name, pats in ISSUES.items() if any(re.search(p, review, re.I) for p in pats)}
    print("issues found:", sorted(found))
    if not REQUIRED <= found:
        failures.append("missing required issue(s): %s" % sorted(REQUIRED - found))
    if len(found) < MIN_FOUND:
        failures.append("found %d planted issues, need %d" % (len(found), MIN_FOUND))

    with open(os.path.join(HERE, "original_auth.py"), "rb") as fh:
        original = fh.read().replace(b"\r\n", b"\n")
    with open(os.path.join(ROOT, "auth.py"), "rb") as fh:
        current = fh.read().replace(b"\r\n", b"\n")
    if current != original:
        failures.append("auth.py was modified during a review-only task")

    for f in failures:
        print("FAIL:", f)
    if not failures:
        print("PASS")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
