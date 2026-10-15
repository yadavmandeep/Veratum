#!/usr/bin/env python3
"""Veratum Stop hook (completion gate) for Antigravity.

Returns {"decision": "continue"} — keeping the agent working — while the
ledger is not PASSED, the verified tree hash no longer matches the workspace,
the passing command is not the contracted one, or files changed outside the
contract. A circuit breaker (config.stop_gate_max_blocks) prevents infinite
loops and records the task as UNVERIFIED when it trips.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _veratum_bridge import run  # noqa: E402

if __name__ == "__main__":
    sys.exit(run("stop"))
