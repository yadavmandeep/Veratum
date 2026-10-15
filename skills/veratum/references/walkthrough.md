# Walkthrough — one task, all six gates

A real session with real engine output. Output is trimmed where marked `…`, and the temp-folder project name is
replaced with `shop-api`. The task:

> Users report that list endpoints skip records: walking every page of `paginate()` in `pager.py` never returns all items.

`M` = `python .veratum/engine/veratum_cli.py`.

## Gate 0 — Brain sync
```
$ V brain show
[VERATUM BRAIN] project=shop-api | stack=unknown
Modules: .(1 py), tests(1 py)
No active contract. Before editing: `veratum_cli.py contract --goal "..." --files "a,b" --verify "<cmd>"`.
```
The brain is empty for this repo, so reconnaissance is just reading `pager.py` and its test.
On a repo Veratum has seen before, this is where pitfalls and known commands show up. Read them before anything else.

## Gate 1 — Contract & blast radius
The goal is observable and the files include the test. The verify command is one-shot.
```
$ V contract --goal "Walking every page of paginate() returns each item exactly once" \
    --files "pager.py,tests/test_pager.py" --verify "python -m unittest discover -s tests"
📜 [VERATUM CONTRACT] c-20261015-215300-59e8 — ACTIVE
   Mode:    implement   Profile: balanced (1 dependent(s), 2 file(s))
   Scope:   pager.py, tests/test_pager.py
   Impact:  pager.py → 1 dependent(s) [LOW]: tests/test_pager.py
   Rules:   max 2 retries, read-before-write
```
`Profile: balanced` was picked automatically: one dependent, low risk. Check the dependents it lists. Here the only one is the test.

## Gate 2 — Checkpoint
Optional for a 2-file `balanced` change; cheap insurance anyway:
```
$ V checkpoint create --label "before off-by-one fix"
📸 [VERATUM CHECKPOINT] cp-20261015-215301-1e9f → 47bfd4ef3c86 (incl. untracked files, worktree untouched)
```

## Gate 3 — Scoped execution: reproduce first
The existing tests pass, so they cannot prove anything about this bug. Write a test that walks every page **before**
fixing, and watch it fail:
```
$ V verify
❌ [VERATUM FAILED] `python -m unittest discover -s tests` → EXIT 1 in 0.26s (attempt 1 of 2)
AssertionError: Lists differ: [0, 1, 3, 4, 6] != [0, 1, 2, 3, 4, 5, 6]
…
Fix the ROOT CAUSE shown above, then re-run verify.
```
The missing items are the last item of each page, so the cause is the page's end index:
`end = start + per_page - 1`, but a slice end is already exclusive. Change that one line.

## Gate 4 — Validation
```
$ V verify
✅ [VERATUM VERIFIED] `python -m unittest discover -s tests` → EXIT 0 in 0.22s
   Proof locked: tree sha256:0edc1e2280188a37 → .veratum/ledger.json
   Any edit from now on invalidates this proof. Next: run `gate`.
```

### The trap: one more "harmless" edit
Adding a comment to `pager.py` after the pass breaks the proof:
```
$ V gate
🛑 [VERATUM COMPLETION GATE BLOCKED]
   ✗ POST-VERIFICATION EDIT DETECTED: working tree sha256:18ad0115df8df8ae ≠ verified sha256:0edc1e2280188a37 — changed after verify: pager.py
   Required action:
   → python3 .veratum/engine/veratum_cli.py verify "python -m unittest discover -s tests"
```
Do what it says: verify again after your **final** edit. Do not argue with the gate.

## Gate 5 — Gate & memory
```
$ V gate
✅ [VERATUM COMPLETION GATE PASSED]
━━━━━━━━━━━━━━━━ VERATUM EVIDENCE BLOCK ━━━━━━━━━━━━━━━━
Goal:            Walking every page of paginate() returns each item exactly once
Changed (2):     pager.py, tests/test_pager.py
Scope:           ✓ all changes inside contract
Impact checked:  tests/test_pager.py
Verified by:     `python -m unittest discover -s tests` → EXIT 0 (0.22s) @ 2026-10-15T16:23:12Z
Tree hash:       sha256:0edc1e2280188a374880ce3d (matches verified state)
Evidence chain:  ✓ intact · record 6de0cdb3280d · profile balanced
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

$ V remember "paginate() end index is exclusive: start + per_page, no -1" --kind pitfall
```
The next session's `brain show` starts with that pitfall, the test command and the last completed task.

## The final message
```
Fixed: paginate() dropped the last item of every page (end index was start + per_page - 1;
slice ends are exclusive). Added a test that walks every page; it failed before the fix
and passes now.

<Veratum Evidence Block from the gate, pasted unchanged>
```
Short, states the cause, says how it was proven, and includes the evidence block. No "should work".
