<!-- Generated from core/SKILL.md by `veratum build`. Do not edit by hand. -->
# Veratum — 6-Gate Engineering Protocol

**One rule above all: report what happened, not what you intended.** Every claim rests on output you saw in
this task. If you did not check something, say so.

You run under **Veratum**. Never go `task → edit → "done"`. Every code change passes the
6 gates below, in order. The engine enforces them; do not route around it.

`V` = `python3 .veratum/engine/veratum_cli.py`. With Veratum MCP tools, use those (names in brackets).
**First use** (no `.veratum/`): run `python3 <this-skill-folder>/scripts/veratum_cli.py init` once
(e.g. `.agents/skills/veratum/…`, `.claude/skills/veratum/…`). Tell the user `npx veratum init --ide <ide>` adds hook enforcement.
Guides live in `references/` (also `.veratum/references/`). Read one only when you need it:

| Read | When |
|---|---|
| `walkthrough.md` | First Veratum task in a session: one full task, gate by gate, with real output |
| `reconnaissance.md` | Unfamiliar code, before Gate 1 |
| `contracts.md` | Writing the goal / files / verify command |
| `planning.md` | Large, ambiguous or high-risk work; the user wants a plan |
| `verification.md` | Choosing what to run; deciding whether a result counts |
| `recovery.md` | Verify failed, the gate is blocked, or you are resuming an interrupted task |

## Gate 0 — Brain Sync  `[veratum_get_brain]`
`V brain show` **before** exploring. Reuse known commands, decisions and pitfalls. Read only what the brain doesn't explain.

## Gate 1 — Contract & Blast Radius  `[veratum_lock_contract]`
```
V contract --goal "<observable outcome>" --files "<files + their tests>" --verify "<one-shot command>"
```
- Read the blast radius: dependents and the exports they use, co-changed files, related tests. Inspect what you could break.
- `--profile auto` picks eco / balanced / deep / highstakes from risk. Sensitive paths and wide impact raise it: depth-2 impact, required checkpoint, fewer retries.
- Unclear task or the user wants a plan → `--mode plan` (file changes are locked). After approval: `V contract --mode implement`.
- Need another file → `V contract --extend "<file>"` *before* touching it.

## Gate 2 — Shadow Checkpoint  `[veratum_checkpoint]`
Before multi-file or risky edits: `V checkpoint create --label "<why>"`. `deep`/`highstakes` require it.
Destructive commands (`git reset --hard`, `rm -r`, force-push) are blocked until a checkpoint exists.

## Gate 3 — Scoped Execution  `[veratum_check_scope, veratum_explain_shell]`
- **Read before write.** Edits to files you haven't read in this task are blocked. If a file changed since you read it
  (formatter, shell, another process), re-read it.
- Touch only contracted files, including via the shell: writes outside scope are blocked before they run.
- Smallest diff. Keep style, types and public APIs. No drive-by refactors. Never edit `.veratum/*.json`.

## Gate 4 — Compacted Validation  `[veratum_verify]`
`V verify` runs the contracted command. A pass binds the exact working-tree SHA-256 into a hash-chained ledger.
- FAIL → compacted trace (full log: `.veratum/logs/last_run.log`). Fix the **root cause**.
- `DUPLICATE` = you re-ran without changing code. `SAME FAILURE` = your edit missed the cause. Rethink before editing.
- Retry budget per profile (2, or 1 for highstakes). Then `V rollback` or escalate with the trace.
- Never weaken, skip or delete tests. Any edit after a pass invalidates it, so verify after your **final** edit.

## Gate 5 — Cryptographic Gate & Memory Commit  `[veratum_check_gate, veratum_remember]`
1. `V gate` must print `PASSED`. It checks the contract, the PASSED ledger for the contracted command, current tree hash ==
   verified hash, no out-of-scope changes, and an intact evidence chain. `🛑 BLOCKED` → do exactly the listed action.
2. Save new durable learnings: `V remember "<fact>" --kind decision|pitfall|architecture|command`.
3. Your final message MUST include the **Veratum Evidence Block** from the gate.

Never say "done", "fixed" or "should work" without a passed gate. If you can't pass it, say exactly what is unverified.

## Quick reference
`V status` · `V impact <file> [--depth 2] [--symbol X]` · `V explain-shell "<cmd>"` · `V audit` · `V rollback [id]` · `V doctor`
