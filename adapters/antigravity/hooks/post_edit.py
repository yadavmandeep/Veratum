#!/usr/bin/env python3
"""Veratum PostToolUse hook for Antigravity.

After any write or shell command: records touched files on the contract,
invalidates a PASSED ledger (status -> STALE) when the working-tree hash no
longer matches the verified hash, and reports out-of-scope changes made by
shell commands.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _veratum_bridge import run  # noqa: E402

if __name__ == "__main__":
    sys.exit(run("post-tool"))
