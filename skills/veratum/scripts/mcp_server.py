#!/usr/bin/env python3
"""
Veratum MCP Server
====================================

Zero-dependency Model Context Protocol server (JSON-RPC 2.0 over stdio,
newline-delimited) that gives Cursor, Windsurf, Cline, VS Code/Copilot,
OpenCode and Claude the same mechanical Veratum guarantees as native hooks:

    veratum_get_brain      project memory, known commands, active contract
    veratum_remember       persist an insight / decision / pitfall
    veratum_lock_contract  lock goal + scope + verify command, run blast radius
    veratum_impact         blast-radius analysis for one or more files
    veratum_check_scope    may this file be edited under the contract?
    veratum_checkpoint     create / list / rollback shadow git checkpoints
    veratum_verify         run validation, compact log, bind tree hash
    veratum_check_gate     hard completion gate + Evidence Block
    veratum_status         contract / ledger / freshness overview
    veratum_explain_shell  capability level + write targets of a shell command
    veratum_audit          verify the hash-chained evidence log

Usage:  python3 .veratum/engine/mcp_server.py [--root <workspace>]
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import veratum_cli  # noqa: E402

SERVER_NAME = "veratum"
SUPPORTED_PROTOCOLS = ("2025-06-18", "2025-03-26", "2024-11-05")
LOCK = threading.Lock()

INSTRUCTIONS = (
    "Veratum enforces the 6-Gate Engineering Protocol. "
    "1) Call veratum_get_brain first to reuse project memory instead of re-reading the repo. "
    "2) Before editing, call veratum_lock_contract with goal, files and verify command; read its blast radius. "
    "3) Call veratum_checkpoint(create) before multi-file or risky edits. "
    "4) Edit only contracted files (veratum_check_scope when unsure). "
    "5) Validate ONLY via veratum_verify (max 2 failed retries, then rollback or escalate). "
    "6) You may not claim completion until veratum_check_gate passes; paste its Evidence Block and save learnings with veratum_remember."
)

_ROOT_PROP = {"root": {"type": "string", "description": "Workspace root (optional; defaults to the server root)."}}


def _schema(props: dict, required=None) -> dict:
    merged = dict(props)
    merged.update(_ROOT_PROP)
    return {"type": "object", "properties": merged, "required": list(required or []), "additionalProperties": False}


TOOLS = [
    {
        "name": "veratum_get_brain",
        "description": "Gate 0 — Load Veratum project memory: stack, verified build/test commands, module map, insights, pitfalls and the active contract. Call this BEFORE exploring the codebase.",
        "inputSchema": _schema({}),
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "veratum_remember",
        "description": "Gate 5 — Persist a durable learning (architecture fact, decision, pitfall, command) into .veratum/brain.json for future sessions.",
        "inputSchema": _schema({
            "insight": {"type": "string", "description": "One concise, reusable fact."},
            "kind": {"type": "string", "enum": list(veratum_cli.INSIGHT_KINDS), "default": "insight"},
            "files": {"type": "string", "description": "Optional comma separated related files."},
        }, ["insight"]),
    },
    {
        "name": "veratum_lock_contract",
        "description": "Gate 1 — Lock the task contract (goal, allowed files, verification command), reset the ledger to IN_PROGRESS and return the blast radius of each target file. Required before any edit.",
        "inputSchema": _schema({
            "goal": {"type": "string", "description": "One-sentence objective."},
            "files": {"description": "Files/globs allowed to change (array or comma separated string).",
                      "anyOf": [{"type": "array", "items": {"type": "string"}}, {"type": "string"}]},
            "verify": {"type": "string", "description": "Command that must pass (defaults to the brain's test command)."},
            "trivial": {"type": "boolean", "default": False},
            "mode": {"type": "string", "enum": ["implement", "plan", "review"], "default": "implement",
                     "description": "plan/review = read-only action lock; switch an active contract by sending only `mode`."},
            "profile": {"type": "string", "enum": ["auto", "eco", "balanced", "deep", "highstakes"], "default": "auto",
                        "description": "auto picks the profile from risk (sensitive paths, blast radius)."},
            "extend": {"type": "boolean", "default": False, "description": "Add `files` to the active contract instead of locking a new one."},
        }),
    },
    {
        "name": "veratum_impact",
        "description": "Blast-radius analysis: lists files importing the target (JS/TS, Python, Go, Rust, Java/Kotlin, C/C++) and related tests.",
        "inputSchema": _schema({
            "file": {"description": "File path or array of paths.",
                     "anyOf": [{"type": "array", "items": {"type": "string"}}, {"type": "string"}]},
            "depth": {"type": "integer", "minimum": 1, "maximum": 5, "default": 1},
            "symbol": {"type": "string", "description": "Only dependents that use this exported symbol."},
        }, ["file"]),
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "veratum_check_scope",
        "description": "Gate 3 — Returns whether a file may be edited under the active contract. Call before editing a file you are unsure about.",
        "inputSchema": _schema({"file": {"type": "string"}}, ["file"]),
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "veratum_checkpoint",
        "description": "Gate 2 — Shadow git checkpoint. action=create snapshots tracked+untracked files without touching the worktree; action=rollback restores the latest (or given) checkpoint; action=list shows them.",
        "inputSchema": _schema({
            "action": {"type": "string", "enum": ["create", "rollback", "list"], "default": "create"},
            "label": {"type": "string"},
            "id": {"type": "string"},
        }),
    },
    {
        "name": "veratum_verify",
        "description": "Gate 4 — Run the verification command, save the raw log to .veratum/logs/last_run.log, return a compacted error trace on failure and lock a SHA-256 tree hash into the ledger on success.",
        "inputSchema": _schema({
            "command": {"type": "string", "description": "Shell command (defaults to the contract's verify command)."},
            "timeout_sec": {"type": "integer", "minimum": 1},
            "force": {"type": "boolean", "default": False, "description": "Re-run although the same command already failed on identical code (flaky tests only)."},
        }),
    },
    {
        "name": "veratum_explain_shell",
        "description": "Classify a shell command (read/exec/network/write/install/destructive), list the files it would write, and say whether Veratum would allow it now. Use before risky shell commands.",
        "inputSchema": _schema({"command": {"type": "string"}}, ["command"]),
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "veratum_audit",
        "description": "Verify the hash-chained evidence log and that the PASSED ledger is bound to an intact chained record.",
        "inputSchema": _schema({}),
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "veratum_check_gate",
        "description": "Gate 5 — Hard completion gate. Passes only if the contract is active, the ledger is PASSED for the contracted command, no file changed after verification and no out-of-scope file changed. On pass it closes the contract and returns the Evidence Block you must include in your final answer.",
        "inputSchema": _schema({"dry_run": {"type": "boolean", "default": False}}),
    },
    {
        "name": "veratum_status",
        "description": "Show active contract, ledger status, evidence freshness and changed files.",
        "inputSchema": _schema({}),
        "annotations": {"readOnlyHint": True},
    },
]


def _as_list(value) -> list:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v) for v in value]
    return veratum_cli.split_csv(str(value))


def _argv_for(name: str, args: dict) -> list:
    if name == "veratum_get_brain":
        return ["brain", "show"]
    if name == "veratum_remember":
        argv = ["remember", str(args.get("insight", "")), "--kind", str(args.get("kind") or "insight")]
        if args.get("files"):
            argv += ["--files", str(args["files"])]
        return argv
    if name == "veratum_lock_contract":
        files = ",".join(_as_list(args.get("files")))
        if args.get("extend"):
            return ["contract", "--extend", files]
        if args.get("mode") and not args.get("goal"):
            return ["contract", "--mode", str(args["mode"])]
        argv = ["contract", "--goal", str(args.get("goal") or ""), "--files", files,
                "--mode", str(args.get("mode") or "implement"), "--profile", str(args.get("profile") or "auto")]
        if args.get("verify"):
            argv += ["--verify", str(args["verify"])]
        if args.get("trivial"):
            argv.append("--trivial")
        return argv
    if name == "veratum_impact":
        argv = ["impact"] + _as_list(args.get("file")) + ["--depth", str(int(args.get("depth") or 1))]
        return argv + (["--symbol", str(args["symbol"])] if args.get("symbol") else [])
    if name == "veratum_check_scope":
        return ["check-scope", str(args.get("file", ""))]
    if name == "veratum_checkpoint":
        action = str(args.get("action") or "create")
        argv = ["checkpoint", action]
        if args.get("id"):
            argv.append(str(args["id"]))
        if args.get("label"):
            argv += ["--label", str(args["label"])]
        return argv
    if name == "veratum_verify":
        argv = ["verify"]
        if args.get("timeout_sec"):
            argv += ["--timeout", str(int(args["timeout_sec"]))]
        if args.get("force"):
            argv.append("--force")
        if args.get("command"):
            argv.append(str(args["command"]))
        return argv
    if name == "veratum_check_gate":
        return ["gate"] + (["--dry-run"] if args.get("dry_run") else [])
    if name == "veratum_status":
        return ["status"]
    if name == "veratum_explain_shell":
        return ["explain-shell", str(args.get("command", ""))]
    if name == "veratum_audit":
        return ["audit"]
    raise KeyError(name)


def call_tool(name: str, args: dict, default_root: str) -> dict:
    args = args or {}
    root = str(args.pop("root", "") or default_root)
    argv = ["--root", root] + _argv_for(name, args)
    out, err = io.StringIO(), io.StringIO()
    with LOCK, contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = veratum_cli.main(argv)
        except SystemExit as exc:  # argparse errors
            code = exc.code if isinstance(exc.code, int) else 2
        except Exception as exc:  # never crash the server
            code = 1
            err.write("❌ [VERATUM] internal error: {}: {}".format(type(exc).__name__, exc))
    text = (out.getvalue() + ("\n" if out.getvalue() and err.getvalue() else "") + err.getvalue()).strip()
    if name == "veratum_get_brain" and code == 0:
        try:
            ws = veratum_cli.Workspace(veratum_cli.find_root(root))
            brain = ws.brain()
            text += "\n\n```json\n" + json.dumps({"commands": brain.get("commands"), "known_good_commands": brain.get("known_good_commands")}, indent=2) + "\n```"
        except Exception:
            pass
    return {"content": [{"type": "text", "text": text or "(no output)"}], "isError": code != 0,
            "structuredContent": {"exit_code": code, "tool": name}}


class Server:
    def __init__(self, root: str):
        self.root = root

    def handle(self, msg: dict):
        if not isinstance(msg, dict) or msg.get("jsonrpc") != "2.0":
            return self._error(msg.get("id") if isinstance(msg, dict) else None, -32600, "Invalid Request")
        method = msg.get("method")
        mid = msg.get("id")
        params = msg.get("params") or {}
        is_notification = "id" not in msg
        if method is None:
            return None  # a response from the client; nothing to do
        try:
            if method == "initialize":
                requested = params.get("protocolVersion")
                version = requested if requested in SUPPORTED_PROTOCOLS else SUPPORTED_PROTOCOLS[0]
                result = {
                    "protocolVersion": version,
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": {"name": SERVER_NAME, "title": "Veratum Engineering Harness", "version": veratum_cli.VERSION},
                    "instructions": INSTRUCTIONS,
                }
            elif method == "ping":
                result = {}
            elif method == "tools/list":
                result = {"tools": TOOLS}
            elif method == "tools/call":
                raw_name = params.get("name")
                name = str(raw_name) if isinstance(raw_name, str) else ""
                if not name or name not in {t["name"] for t in TOOLS}:
                    return self._error(mid, -32602, "Unknown tool: {}".format(raw_name))
                result = call_tool(name, dict(params.get("arguments") or {}), self.root)
            elif method in ("resources/list",):
                result = {"resources": []}
            elif method in ("resources/templates/list",):
                result = {"resourceTemplates": []}
            elif method in ("prompts/list",):
                result = {"prompts": []}
            elif method.startswith("notifications/"):
                return None
            else:
                return None if is_notification else self._error(mid, -32601, "Method not found: {}".format(method))
        except Exception as exc:  # pragma: no cover - defensive
            return None if is_notification else self._error(mid, -32603, "Internal error: {}".format(exc))
        return None if is_notification else {"jsonrpc": "2.0", "id": mid, "result": result}

    @staticmethod
    def _error(mid, code: int, message: str) -> dict:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": code, "message": message}}


def _write(obj) -> None:
    data = (json.dumps(obj, ensure_ascii=False) + "\n").encode("utf-8")
    sys.stdout.buffer.write(data)
    sys.stdout.buffer.flush()


def serve(root: str) -> int:
    server = Server(root)
    stdin = sys.stdin.buffer
    while True:
        line = stdin.readline()
        if not line:
            return 0
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line.decode("utf-8"))
        except ValueError:
            _write(Server._error(None, -32700, "Parse error"))
            continue
        if isinstance(msg, list):
            replies = [r for r in (server.handle(m) for m in msg) if r is not None]
            if replies:
                _write(replies)
        else:
            reply = server.handle(msg)
            if reply is not None:
                _write(reply)


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    root = None
    if "--root" in argv:
        i = argv.index("--root")
        if i + 1 < len(argv):
            root = argv[i + 1]
    if root and "${" in root:  # unexpanded IDE variable: fall back to auto-detection
        root = None
    resolved = str(veratum_cli.find_root(root or os.environ.get("VERATUM_ROOT")))
    return serve(resolved)


if __name__ == "__main__":
    sys.exit(main())
