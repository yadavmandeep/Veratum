# Recovery — failed verify, blocked gate, interrupted task

## Attempt 1: read, then fix the cause
1. Read the compacted trace. Find the first frame inside the repo's own code.
2. State the cause in one sentence: *"`x` is undefined because `loadUser` returns before the await."*
3. Make the smallest change that removes that cause. Verify.

## Signals Veratum gives you
| Message | Meaning | Do |
|---|---|---|
| `DUPLICATE-FAILURE GUARD` | You re-ran a failing command without changing code | Change something first. Flaky test? `verify --force` once |
| `SAME FAILURE as an earlier attempt` | Your edit didn't touch the cause | Stop. Go back to the trace and rethink the cause |
| `Retry budget exhausted` | Profile retry limit reached | Roll back or escalate. Don't try "one more thing" |
| `STALE` / `POST-VERIFICATION EDIT` | Code changed after the pass | Re-verify after your final edit |
| `SCOPE DRIFT` | Something outside the contract changed (often a formatter or codegen) | Revert it, or `contract --extend` with a reason |

### What a blocked gate looks like
```
🛑 [VERATUM COMPLETION GATE BLOCKED]
   ✗ SCOPE DRIFT: files changed outside the contract: notes.txt
   Required action:
   → python3 .veratum/engine/veratum_cli.py contract --extend "notes.txt"   (if intentional) or revert them
   You may NOT declare this task done until `gate` passes.
```
Each `✗` line is one reason. Fix them in order, and run the exact `Required action`. If the edit was not part of the
task, reverting it is almost always the right call. Extend the contract only for files the goal really needs.

## Resuming an interrupted task
Context compaction, a model switch or a new session do not reset Veratum. The state is on disk.
1. `V status`: the active contract, whether the evidence is fresh, and what changed since the contract.
   ```
   Contract: c-20261015-215333-386c — <goal>
   Ledger:   PASSED  (`<verify cmd>` exit 0)
   Evidence: FRESH ✓ (tree matches verified hash)
   Changed since contract (1): pager.py
   ```
2. `V brain show`: pitfalls and the last completed task. Do not repeat an approach that is listed there as a pitfall.
3. Continue from the state you see, not from what you remember:
   - `Evidence: FRESH` → go straight to `V gate`.
   - `not fresh` → re-read the changed files, then `V verify`.
   - `No active contract` → the last task finished, or none started. Start at Gate 1.
4. Don't redo work the changed-file list shows is already done, and don't re-read files you are not going to change.

## Rollback
`V rollback` restores the last checkpoint: tracked and untracked files, and new files are removed. It saves the current state first, so `V rollback <safety-id>` undoes the rollback. Use it when:
- the retry budget is spent,
- the change spread into files you didn't plan,
- you no longer understand the state of the code.

## Escalating well
Tell the user: the goal · what you tried (per attempt: hypothesis → change → result) · the compacted trace · your best current hypothesis · what you need from them (a decision, access, a reproduction). Never present a partial fix as done.

## Afterwards
`V remember "<cause> → <fix>" --kind pitfall` so the next session doesn't repeat the investigation.
