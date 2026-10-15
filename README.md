<div align="center">

# 🧠 Veratum

**The AI coding harness that remembers your repo and proves its work.**

[yadavmandeep/Veratum](https://github.com/yadavmandeep/Veratum) · Antigravity · Claude Code · Cursor · Windsurf · Cline · GitHub Copilot · OpenCode

[![skills.sh](https://skills.sh/b/yadavmandeep/veratum)](https://skills.sh/yadavmandeep/veratum)
[![npm](https://img.shields.io/npm/v/veratum.svg?style=flat-square)](https://www.npmjs.com/package/veratum)
[![License: MIT](https://img.shields.io/badge/license-MIT-2563EB.svg?style=flat-square)](LICENSE)

</div>

Veratum is an open-source Agent Skill with a zero-dependency runtime. Your coding agent **remembers the project between sessions**, **locks the scope** of every change, **checks the blast radius** before it edits, **runs real validation** with compact logs, and **cannot say "done"** until a cryptographic gate confirms that the verified code is exactly the code on disk.

For Antigravity, install it in your project with one command:

```bash
npx skills add yadavmandeep/veratum --skill veratum --agent antigravity --yes
```

Then say:

```text
Use Veratum to fix this bug and verify the result.
```

## Install

Pick **your** IDE. You only need one line.

| IDE | Install the skill |
|---|---|
| Antigravity | `npx skills add yadavmandeep/veratum --skill veratum --agent antigravity --yes` |
| Claude Code | `npx skills add yadavmandeep/veratum --skill veratum --agent claude-code --yes` |
| Cursor | `npx skills add yadavmandeep/veratum --skill veratum --agent cursor --yes` |
| Windsurf | `npx skills add yadavmandeep/veratum --skill veratum --agent windsurf --yes` |
| Cline | `npx skills add yadavmandeep/veratum --skill veratum --agent cline --yes` |
| GitHub Copilot | `npx skills add yadavmandeep/veratum --skill veratum --agent github-copilot --yes` |
| OpenCode | `npx skills add yadavmandeep/veratum --skill veratum --agent opencode --yes` |

The skill ships with the Veratum engine. The first time you use it, your agent runs the engine's `init`, which creates `.veratum/` (project memory) and detects your stack. Python 3.8+ is the only requirement.

### Veratum Enforced (optional): hooks and MCP that the agent cannot skip

The skill tells the agent what to do. **Enforced** mode makes your IDE block shortcuts mechanically: edits outside the contract, finishing with stale or missing verification, and tampering with evidence.

```bash
npx veratum init --ide antigravity   # or claude-code | cursor | windsurf | cline | copilot | opencode
```

Run it with no `--ide` to get an interactive picker. Step-by-step, per-IDE instructions are in the **[installation guide](docs/install.md)**.

### Or just ask your agent

Paste this into any agent chat:

```text
Install Veratum from https://github.com/yadavmandeep/veratum for this IDE only, following docs/install.md.
Install the skill with `npx skills add`, run its engine `init`, then run `doctor` and tell me the health score.
Do not change unrelated configuration.
```

### Check it

```bash
python3 .veratum/engine/veratum_cli.py doctor     # → Health: 100%
```

## Use it

You don't need a special prompt. Veratum activates for implementation, debugging, refactoring and review work. Naming it makes sure:

```text
Use Veratum to find and fix why pagination sometimes skips records.
```
```text
Use Veratum to add rate limiting to the API without breaking existing clients.
```
```text
Use veratum-review to review this branch. Do not modify files.
```
```text
Use veratum-highstakes to add the column migration for user emails.
```

Every task ends with an evidence block you can check:

```text
━━━━━━━━━━━━━━━━ VERATUM EVIDENCE BLOCK ━━━━━━━━━━━━━━━━
Goal:            Fix pagination skipping records
Changed (2):     src/api/list.ts, src/api/list.test.ts
Scope:           ✓ all changes inside contract
Impact checked:  src/routes/users.ts, src/routes/orders.ts
Verified by:     `pnpm test -- list` → EXIT 0 (4.2s)
Tree hash:       sha256:9c41e0a7… (matches verified state)
```

## What Veratum changes

```text
Without:  task → edits → "done"

With:     brain sync → contract + blast radius → checkpoint → scoped edits
          → compacted validation → cryptographic gate + memory commit → done
```

| Gate | What happens | Why it matters |
|---|---|---|
| 0 · Brain | Loads `.veratum/brain.json`: stack, proven commands, decisions, pitfalls | No re-learning the repo every session |
| 1 · Contract | Goal + allowed files + verify command, plus a list of every file that imports what you'll touch | No blind edits, no surprise breakage |
| 2 · Checkpoint | Hidden git snapshot (including untracked files) | One-command rollback of a bad experiment |
| 3 · Scope | Only contracted files may change | No drive-by refactors |
| 4 · Verify | Runs the real command. Failures are compacted to errors only (80–95% fewer tokens) | The agent reasons on signal, not noise |
| 5 · Gate | Passes only if the **exact verified bytes** are still on disk | "I tested it, then edited one more thing" gets caught |

## The skill pack

| Skill | Use it for |
|---|---|
| `veratum` | Core 6-gate protocol + engine (install this first) |
| `veratum-debug` | Bugs: reproduce first, root cause, regression test |
| `veratum-review` | Read-only review with blast radius and evidence |
| `veratum-refactor` | Behaviour-preserving refactors in small, checkpointed steps |
| `veratum-highstakes` | Auth, payments, migrations, deletions, infra |
| `veratum-typescript` | TS/JS stack pack (package managers, aliases, pitfalls) |
| `veratum-python` | Python stack pack (envs, runners, pitfalls) |

```bash
npx skills add yadavmandeep/veratum --skill veratum-debug --agent cursor --yes
npx skills add yadavmandeep/veratum --agent claude-code --yes          # whole pack
```

## Skill vs Enforced

| Capability | Skill | Enforced |
|---|:---:|:---:|
| 6-gate protocol, project memory, blast radius, checkpoints, compacted verify | ✓ | ✓ |
| Completion gate with tree-hash check | Agent runs it | Runs automatically when the agent stops |
| Block edits outside the contract | — | ✓ (Antigravity, Claude Code, OpenCode). Cursor/Windsurf/Cline/Copilot get scope checks via MCP tools |
| Read-before-write + stale-read detection | Instruction | ✓ hook hosts |
| Shell guard: tokenized capability levels, out-of-scope writes blocked *before* they run | `explain-shell` on demand | ✓ hook hosts |
| Plan/review mode action lock | Instruction + gate | ✓ hook hosts |
| Mark evidence stale on every edit | Detected at gate | Immediately, after each tool call |
| Duplicate-failure guard, same-failure signature, hash-chained evidence, risk-adaptive profiles | ✓ | ✓ |
| Block evidence tampering, and destructive commands without a checkpoint | — | ✓ (hook hosts) |

Hooks are workflow guardrails, not an OS sandbox. See [hosts](docs/hosts.md) for the exact capability of each IDE.

## Documentation

- [Quickstart](docs/quickstart.md): first task in 3 minutes
- [Installation guide](docs/install.md): every IDE, verify, update, uninstall
- [Using Veratum](docs/usage.md): prompts, commands, the evidence block
- [Skill pack](docs/skills.md): when to use which skill
- [Hosts](docs/hosts.md): what each IDE enforces, honestly
- [Concepts](docs/concepts.md): brain, contract, ledger, tree hash, scope drift
- [Configuration](docs/configuration.md): `.veratum/config.json`
- [Troubleshooting](docs/troubleshooting.md)
- [Publishing & launch](docs/publishing.md): for maintainers

## Contributing

```bash
node bin/veratum.js build     # regenerate skills/veratum + IDE adapters from core/SKILL.md
npm test                     # sync check + full test suite
```

MIT © [yadavmandeep/Veratum](https://github.com/yadavmandeep/Veratum)
