# Using Veratum

## Prompts

Veratum activates on its own for coding work. These prompts make the intent explicit:

| Goal | Prompt |
|---|---|
| Fix a bug | `Use Veratum to fix <symptom> and verify it.` (or `Use veratum-debug …`) |
| Build a feature | `Use Veratum to add <feature>. Verify with <command>.` |
| Review | `Use veratum-review to review this branch. Do not modify files.` |
| Refactor | `Use veratum-refactor to extract <x> into its own module without behaviour changes.` |
| Risky change | `Use veratum-highstakes to <migration / auth change>. Ask me before anything irreversible.` |
| Plan only | `Use Veratum in plan mode: lock no contract, just show the blast radius and a plan.` |

## What you'll see

1. **Brain sync**: the agent reads memory instead of re-exploring the repo.
2. **Contract**: goal, files, verify command, and the blast radius (who imports the files being changed).
3. **Checkpoint** before multi-file edits.
4. **Verify**: one line on success. On failure, a compacted trace like this:
   ```text
   ❌ [VERATUM FAILED] `pytest -q` → EXIT 1 (attempt 1 of 2)
   ──── COMPACTED ERROR TRACE (306 → 9 lines, ~95% tokens saved) ────
     File "src/calc.py", line 42, in divide
   ZeroDivisionError: division by zero
   FAILED tests/test_calc.py::test_divide
   ```
5. **Gate** + **Evidence Block** in the final answer.

If the agent edits anything after verifying, the gate prints:
```text
🛑 [VERATUM COMPLETION GATE BLOCKED]
   ✗ POST-VERIFICATION EDIT DETECTED … changed after verify: src/math.ts
```

## Command reference

`V` = `python3 .veratum/engine/veratum_cli.py` (or `npx veratum …`)

| Command | What it does |
|---|---|
| `V init [--rescan]` | Create `.veratum/`, detect stack and commands |
| `V brain show` | Project memory |
| `V remember "<fact>" --kind insight\|decision\|pitfall\|architecture\|command` | Save a learning |
| `V brain set-cmd <test\|build\|lint\|typecheck> "<cmd>"` | Pin a command |
| `V brain forget <id>` | Delete a memory |
| `V contract --goal "…" --files "a,b,dir/,glob/*" --verify "<cmd>" [--mode plan\|review] [--profile auto\|eco\|balanced\|deep\|highstakes]` | Lock a task |
| `V contract --mode implement` | Leave plan/review mode on the active contract (after approval) |
| `V contract --extend "<files>"` / `--show` / `--abandon` | Change / view / drop the contract |
| `V impact <file> [--depth 2] [--symbol X] [--json]` | Blast radius: dependents + the exports they use, git co-change history, dynamic mentions, related tests |
| `V check-scope <file>` | May this file be edited now? |
| `V explain-shell "<cmd>"` | How the shell guard classifies a command, and what it would write |
| `V checkpoint create [--label …]` / `list` | Shadow snapshot |
| `V rollback [id]` | Restore a checkpoint (the current state is saved first, so you can undo it) |
| `V verify ["<cmd>"] [--force]` | Run validation, compact the log, bind the tree hash (`--force` re-runs a failure on unchanged code, for flaky tests only) |
| `V gate [--dry-run]` | Completion gate + Evidence Block |
| `V audit` | Verify the hash-chained evidence log |
| `V status [--json]` | Contract, ledger, freshness, changed files |
| `V doctor` | Health check |

## MCP tools (Cursor, Windsurf, Cline, Copilot, OpenCode)

`veratum_get_brain`, `veratum_remember`, `veratum_lock_contract`, `veratum_impact`, `veratum_check_scope`, `veratum_explain_shell`, `veratum_checkpoint`, `veratum_verify`, `veratum_check_gate`, `veratum_audit`, `veratum_status`. They behave exactly like the CLI commands above.
