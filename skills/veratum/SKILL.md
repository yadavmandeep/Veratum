---
name: veratum
description: Memory-driven, evidence-backed engineering protocol. Use for ANY code change - loads project memory, locks a scoped contract with blast-radius analysis, checkpoints risky edits, validates with compacted logs, and blocks "done" until a cryptographic tree-hash gate passes.
version: 1.1.0
author: Mandeep Yadav
license: MIT
---

# Veratum — 6-Gate Engineering Protocol

**One rule above all: report what happened, not what you intended.** Every claim rests on output you saw in this session. If you did not check something, say so explicitly.

You run under **Veratum**. Never go `task → edit → "done"`. Every code change passes the 6 gates below, in order. The engine enforces them; do not route around it.

- **Engine CLI**: `V` = `python3 .veratum/engine/veratum_cli.py` (on Windows, `python .veratum/engine/veratum_cli.py`).
- **MCP Server**: When Veratum MCP tools are registered in your IDE, invoke the tool names listed in brackets `[veratum_*]`.
- **First Use** (when `.veratum/` does not exist yet): run `python3 <this-skill-folder>/scripts/veratum_cli.py init` once (or run `npx veratum init --ide <your-ide>`).
- **Reference Guides**: In-depth documentation lives in `references/` (also mirrored at `.veratum/references/`):
  - `walkthrough.md`: Step-by-step example of a full task with real outputs.
  - `reconnaissance.md`: How to inspect unfamiliar repositories before locking a contract.
  - `contracts.md`: Best practices for defining goals, scope, and verification commands.
  - `planning.md`: Detailed planning workflows for complex or high-risk tasks.
  - `verification.md`: Choosing high-signal test runners and validating results.
  - `recovery.md`: Debugging failures, resolving blocked gates, and handling rollbacks.

---

## The 6 Invariants

These invariants are enforced by Veratum across all supported models and IDE hosts:

1. **Ground before mutating**: Always read the target file, its tests, and its callers before editing. Never act on assumed state.
2. **Stay in declared scope**: Only modify files declared in the active contract. Uncontracted edits and shell write redirections are blocked before they run.
3. **Completion requires fresh evidence**: Work is only complete when an executed test passes *after* the final edit. Stale green results, self-reviews, and assumptions do not count.
4. **Never exact-retry a failure**: When a test fails, you must diagnose the root cause and alter your approach. The engine blocks duplicate and byte-identical retries.
5. **Satisfy the contract**: Verification must run the exact test command bound to the task contract. Running unrelated tests does not satisfy completion.
6. **Say what you cannot verify**: Label any uncertain or unverified claims honestly. Never fabricate certainty.

---

## Gate 0 — Brain Sync `[veratum_get_brain]`

Before exploring files or proposing changes, load project memory:

```bash
V brain show
```

- **Purpose**: Retrieves `.veratum/brain.json` containing stack detection, proven test/build commands, architectural invariants, and past pitfalls discovered in previous sessions.
- **Action**: Do not re-explore stack details or re-guess test commands that the brain already documents. Read only what the brain does not explain.

---

## Gate 1 — Contract & Blast Radius `[veratum_lock_contract]`

Lock the task boundaries and inspect the blast radius before touching any file:

```bash
V contract --goal "<observable outcome>" --files "<file1,file2,test1>" --verify "<one-shot verify command>"
```

- **Goal**: A clear, observable outcome (e.g., `"Fix off-by-one error in pagination when offset exceeds total"`).
- **Files**: Comma-separated list of files you are authorized to modify, including their corresponding test files.
- **Verify**: One-shot deterministic command that validates the change (e.g., `"npm test"`, `"pytest tests/test_auth.py"`, `"cargo test"`).
- **Blast Radius Analysis**: Veratum automatically analyzes imports, exports, and call hierarchies across TypeScript, JavaScript, Python, Rust, Go, and Java:
  - Inspects all downstream dependent files that import symbols from contracted files.
  - Flags co-changed files historically modified together in git history.
  - Lists related test suites that cover the contracted code.
- **Risk Profiles** (`--profile auto|eco|balanced|deep|highstakes`):
  - `eco`: Low ceremony for trivial, localized edits (single file, no dependents).
  - `balanced`: Default standard profile for multi-file features and bug fixes.
  - `deep`: High-uncertainty architectural refactoring, migrations, or wide blast radius.
  - `highstakes`: Critical systems (auth, billing, schema migrations). Requires shadow checkpoint, strict single-retry budget.
- **Execution Modes** (`--mode implement|plan|review`):
  - `--mode plan`: File modifications are locked. Use when the user requests a plan or requirements are ambiguous. Once approved, switch via `V contract --mode implement`.
  - `--mode review`: Read-only code review mode. Analyzes blast radius without allowing file edits.
- **Extending Scope**: If you discover that an additional file must be touched, run `V contract --extend "<path>"` *before* modifying it.

---

## Gate 2 — Shadow Checkpoint `[veratum_checkpoint]`

Protect the working tree before making multi-file or risky modifications:

```bash
V checkpoint create --label "<descriptive reason>"
```

- **Purpose**: Creates an isolated, hidden git snapshot ref capturing staged, unstaged, and untracked files without altering your working directory.
- **Enforcement**: Required automatically for `deep` and `highstakes` profiles. Destructive shell commands (`git reset --hard`, `rm -rf`, force-push) are strictly blocked unless a checkpoint exists.
- **Rollback**: If an experimental approach fails, restore the clean state instantly:
  ```bash
  V rollback [checkpoint-id]
  ```

---

## Gate 3 — Scoped Execution `[veratum_check_scope, veratum_explain_shell]`

Perform surgical, minimal code edits strictly within contracted boundaries:

- **Read Before Write**: Edits to any file you have not read during the current task are blocked. If an external process or formatter changes a file, re-read it before writing.
- **Strict Scope Whitelist**: Modifying files outside the contracted scope is denied mechanically by IDE hooks and tool wrappers.
- **Shell Guard**: Before executing complex shell commands, verify safety with `V explain-shell "<command>"`. Shell commands redirecting output (`>`, `>>`, `tee`) to uncontracted files are intercepted and blocked.
- **Minimal Diff Principle**: Retain existing styling, conventions, types, and public interfaces. Never perform drive-by refactorings. Never edit `.veratum/*.json` manually.

---

## Gate 4 — Compacted Validation `[veratum_verify]`

Execute the contracted verification command to produce tamper-evident proof:

```bash
V verify
```

- **Compacted Log Processing**: Full output is saved to `.veratum/logs/last_run.log`, while terminal/tool output is filtered to errors and stack traces only (80–95% token savings).
- **Duplicate Failure Guard**: Re-running `V verify` without editing code is flagged as `DUPLICATE` and blocked.
- **Same Failure Signature**: If an edit does not fix the underlying compiler error or test failure, Veratum alerts you that the failure signature is unchanged. Stop and rethink the root cause.
- **Retry Budget**: Governed by the risk profile (typically 2 retries; 1 retry for `highstakes`). When exhausted, roll back via `V rollback` or escalate to the user with the compacted trace.
- **Stale Evidence Protection**: Never weaken, skip, or delete tests. Any file edit performed after a passing verification immediately invalidates the ledger. Verification must run after your **final** edit.

---

## Gate 5 — Cryptographic Gate & Memory Commit `[veratum_check_gate, veratum_remember]`

Validate cryptographic integrity and persist learnings before completing the turn:

1. **Completion Check**:
   ```bash
   V gate
   ```
   Must output `PASSED`. Veratum computes a SHA-256 tree hash of the working tree and validates:
   - Contract is active and all changed files are within declared scope.
   - Contracted verify command passed with exit code 0.
   - Current working tree hash matches the verified ledger state byte-for-byte.
   - Evidence chain in `.veratum/ledger.json` is untampered and cryptographically valid.
   - If blocked (`🛑 BLOCKED`), perform the specific remedial action indicated.

2. **Memory Commit**:
   Capture durable architectural facts, proven test commands, or discovered pitfalls:
   ```bash
   V remember "<fact or learning>" --kind decision|pitfall|architecture|command
   ```

3. **Veratum Evidence Block**:
   Your final completion message to the user **MUST** display the Evidence Block generated by `V gate`:

```text
━━━━━━━━━━━━━━━━ VERATUM EVIDENCE BLOCK ━━━━━━━━━━━━━━━━
Goal:            <Observable outcome>
Changed:         <List of modified files>
Scope:           ✓ all changes inside contract
Impact checked:  <List of downstream dependents inspected>
Verified by:     `<verify-command>` → EXIT 0 (<duration>)
Tree hash:       sha256:<hash> (matches verified state)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

**Never declare "done", "fixed", or "completed" without a passed gate and a valid Evidence Block.** If a gate cannot be passed, explain precisely what remains unverified.

---

## Quick Reference

| CLI Command | MCP Tool Equivalent | Purpose |
|---|---|---|
| `V status` | `veratum_status` | View active contract, ledger state, and tree hash freshness |
| `V brain show` | `veratum_get_brain` | Display project memory, stack, proven commands, and pitfalls |
| `V contract --goal ...` | `veratum_lock_contract` | Lock task scope, run blast-radius analysis, set verify command |
| `V contract --extend <f>` | `veratum_lock_contract` | Extend contract to include additional file |
| `V checkpoint create` | `veratum_checkpoint` | Create an atomic hidden git snapshot ref |
| `V rollback [id]` | `veratum_rollback` | Roll back to a previous checkpoint |
| `V verify` | `veratum_verify` | Execute verification command with compacted trace logging |
| `V gate` | `veratum_check_gate` | Cryptographically verify that tree hash matches verified ledger |
| `V remember "<fact>"` | `veratum_remember` | Save durable knowledge to `.veratum/brain.json` |
| `V impact <file>` | `veratum_impact` | Inspect downstream dependents and AST call hierarchy |
| `V explain-shell "<cmd>"` | `veratum_explain_shell` | Audit shell command safety and target file paths |
| `V doctor` | `veratum_doctor` | Run comprehensive health check and adapter diagnostic |
