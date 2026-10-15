# Hosts: what each IDE actually enforces

Veratum is the same protocol everywhere, but IDEs expose different extension points. This table says plainly what is **instruction** (the agent is told) and what is **enforced** (the IDE blocks it).

| | Antigravity | Claude Code | Cursor | Windsurf | Cline | Copilot (VS Code) | OpenCode |
|---|---|---|---|---|---|---|---|
| Skill (skills.sh) | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| Always-on rules | skill | `CLAUDE.md` | `.cursor/rules` | `.windsurfrules` | `.clinerules` | `copilot-instructions.md` | `AGENTS.md` |
| Memory injected at session start | via skill | **hook** | via rule | via rule | via rule | via instructions | via `AGENTS.md` |
| Block out-of-scope edits | **hook** | **hook** | MCP `check_scope` | MCP `check_scope` | MCP `check_scope` | MCP `check_scope` | **plugin** |
| Read-before-write / stale-read | **hook** | **hook** | **hook** (`beforeReadFile`) | — | — | — | — |
| Shell guard (pre-execution scope, destructive, plan lock) | **hook** | **hook** | **hook** (`beforeShellExecution`) | MCP `explain_shell` | MCP `explain_shell` | MCP `explain_shell` | **plugin** |
| Plan/review action lock | **hook** | **hook** | MCP | MCP | MCP | MCP | **plugin** |
| Duplicate-failure guard, failure signature, evidence chain | ✓ engine | ✓ engine | ✓ engine | ✓ engine | ✓ engine | ✓ engine | ✓ engine |
| Evidence marked stale after an edit | **hook** | **hook** | **hook** (`afterFileEdit`) | at gate | at gate | at gate | **plugin** |
| Completion gate on stop | **hook** | **hook** | **hook** (follow-up message) | MCP `check_gate` | MCP `check_gate` | MCP `check_gate` | MCP `check_gate` |
| Tamper / destructive-git guard | **hook** | **hook** | **hook** (shell) | — | — | — | **plugin** |

**Bold** = mechanical. Everything else depends on the agent following the rules and calling the tools. The cryptographic check inside `gate` is always mechanical: when the gate runs, a stale or missing proof **cannot** pass, on any host.

## Limits

- Hooks are workflow guardrails, not an OS sandbox. `.veratum/ledger.json` lives in your workspace, so a process with unrestricted shell access could rewrite it. The tamper guard blocks the obvious routes (agent edits, shell redirects into `.veratum/*.json`).
- On hosts without hooks, nothing prevents an agent from editing a file without calling `veratum_check_scope` first. Scope drift is still caught by `gate`, which diffs against the contract baseline.
- Blast-radius analysis is static. It does not see dynamic imports, reflection or string-based registration (e.g. Django settings). The stack skills tell the agent to grep for those.
