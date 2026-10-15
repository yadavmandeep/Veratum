"""Shared bridge between Antigravity hook payloads and the project's Veratum engine.

Antigravity plugins are installed per user, so the hook resolves the *project*
engine at runtime from the payload's workspace paths (or the current
directory) and delegates to `veratum_cli.run_hook`, which speaks Antigravity's
hook protocol: stdin = {"toolCall": {"name", "args"}, "workspacePaths": [...]},
stdout = {"decision": "allow" | "deny" | "continue", "reason": "..."}.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path


def _candidate_roots(payload: dict) -> list:
    roots = []
    for key in ("workspacePaths", "workspace_paths", "workspace_roots"):
        for value in payload.get(key) or []:
            if isinstance(value, str) and value:
                roots.append(Path(value))
    if isinstance(payload.get("cwd"), str):
        roots.append(Path(payload["cwd"]))
    roots.append(Path.cwd())
    expanded = []
    for root in roots:
        root = root.resolve()
        expanded.extend([root] + list(root.parents))
    return expanded


def _load_engine(root: Path):
    engine = root / ".veratum" / "engine" / "veratum_cli.py"
    if not engine.is_file():
        return None
    spec = importlib.util.spec_from_file_location("veratum_cli", str(engine))
    module = importlib.util.module_from_spec(spec)
    sys.modules["veratum_cli"] = module
    spec.loader.exec_module(module)
    return module


def run(event: str) -> int:
    raw = sys.stdin.buffer.read().decode("utf-8", errors="replace") if not sys.stdin.isatty() else ""
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except ValueError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    for root in _candidate_roots(payload):
        if (root / ".veratum" / "engine" / "veratum_cli.py").is_file():
            engine = _load_engine(root)
            if engine is None:
                break
            engine._utf8_stdio()
            os.environ.setdefault("VERATUM_ROOT", str(root))
            return engine.run_hook(event, "antigravity", root, raw)
    # Veratum is not installed in this workspace: never block the agent.
    print(json.dumps({"decision": "allow"}))
    return 0
