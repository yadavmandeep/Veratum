#!/usr/bin/env python3
"""Veratum PreToolUse hook for Antigravity.

Denies file writes when there is no active Veratum contract or the target file
is outside the contracted scope, blocks direct tampering with Veratum evidence
files, and requires a shadow checkpoint before destructive git commands.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _veratum_bridge import run  # noqa: E402

if __name__ == "__main__":
    sys.exit(run("pre-tool"))
