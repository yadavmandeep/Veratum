# Troubleshooting

Start with:
```bash
npx veratum doctor
```
(No Node? `python3 .veratum/engine/veratum_cli.py doctor` does the same.)

| Symptom | Fix |
|---|---|
| `python3: command not found` (Windows) | Use `python`. `npx veratum init` detects the right command and writes it into every config |
| `.veratum/` missing after `npx skills add` | Run the bundled engine once: `python3 .agents/skills/veratum/scripts/veratum_cli.py init` (Claude Code: `.claude/skills/…`, Windsurf: `.windsurf/skills/…`) |
| Every edit is blocked: "No active Veratum contract" | Working as intended. Lock one: `V contract --goal … --files … --verify …`. For a quick throwaway session: `VERATUM_TRIVIAL=1`, or `"enforcement": "advisory"` |
| "OUTSIDE the active contract scope" | `V contract --extend "<file>"`, then retry the edit |
| Gate: `POST-VERIFICATION EDIT DETECTED` | Something changed after verify (the message lists the files). Re-run `V verify` |
| Gate: `SCOPE DRIFT` | A file outside the contract changed (often via a shell command or a formatter). Revert it or `contract --extend` it |
| Gate: "not the contracted verification" | Run the exact contracted command: `V verify` with no argument uses it |
| `READ-BEFORE-WRITE` | Read the file with the Read/view tool (or `cat`) first. This is intended |
| `STALE READ` | The file changed since you read it (formatter, codegen, another process). Re-read it, then edit |
| `ACTION LOCK` | The contract is in plan/review mode. After approval: `V contract --mode implement` |
| `DUPLICATE-FAILURE GUARD` (exit 3) | You re-ran a failing command on unchanged code. Change the code, or `verify --force` once if the test is flaky |
| `EVIDENCE INTEGRITY` | `ledger.json` or `logs/history.jsonl` was edited by hand, or the logs were deleted. Run `V audit` to see which, then `V verify` to create fresh evidence |
| Shell command blocked unexpectedly | `V explain-shell "<cmd>"` shows the level, the write targets and the reason |
| Generated files keep invalidating evidence | Gitignore them, or add patterns to `fingerprint_exclude` |
| Verify hangs | The test runner is in watch mode. Use `vitest run`, `jest --ci`, `CI=1 …`. The timeout is `verify_timeout_sec` |
| `checkpoint` says git is required | `git init` (no commit needed) |
| Cursor shows no Veratum tools | Settings → MCP → enable **veratum**. Check `.cursor/mcp.json` points at `.veratum/engine/mcp_server.py` |
| Claude Code hooks don't fire | Restart Claude Code / open `/hooks`. `doctor` should say "Claude Code hooks wired" |
| Antigravity hooks don't fire | `agy plugin install "$PWD/.agents/plugins/veratum"`, then `agy plugin list` |
| Agent loops on the stop gate | The circuit breaker lets it stop after `stop_gate_max_blocks` tries and records `gate_overridden` in the ledger. Read the gate's blocked reasons and fix them |
| Undo a rollback | `V checkpoint list` → `V rollback <the "pre-rollback safety" id>` |
