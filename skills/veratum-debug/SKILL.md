---
name: veratum-debug
description: Reproduce-first debugging with Veratum. Use when fixing a bug, crash, flaky test, regression or wrong output - proves the bug with a failing check before changing code, finds the root cause, and only finishes when the same check passes under the Veratum completion gate.
version: 1.0.0
author: Mandeep Yadav
license: MIT
---

# Veratum Debug — prove it broken, then prove it fixed

Runs inside the Veratum 6-Gate protocol (`veratum` skill). `V` = `python3 .veratum/engine/veratum_cli.py`.
No `.veratum/`? Install the core skill first: `npx skills add yadavmandeep/veratum --skill veratum`.

## 1. Recall before you search
`V brain show` — check pitfalls and past tasks for this area. A bug fixed before often comes back the same way.

## 2. Reproduce (no code changes yet)
- Turn the report into an **observable failing check**: an existing test, a new minimal test, or a one-line command whose output shows the bug.
- Run it through Veratum so the failure is recorded: `V verify "<repro command>"` → must FAIL for the reason described.
- Cannot reproduce? Stop and report what you tried and what you observed. Do not "fix" a bug you have not seen.

## 3. Lock the contract around the repro
`V contract --goal "Fix: <symptom>" --files "<suspect files>,<test file>" --verify "<repro command> && <related suite>"`
Read the blast radius: every dependent of the file you will change is a place the fix can break something else.

## 4. Find the root cause, not the symptom
- Trace from the failing assertion back to the first wrong value. Read the code on that path; use `V impact <file>` to see callers.
- State the cause in one sentence before editing: *"X happens because Y, introduced by Z."*
- Forbidden "fixes": catching and ignoring the error, special-casing the test input, retry loops around a deterministic failure, loosening the assertion, deleting the test.

## 5. Fix minimally, verify, gate
- `V checkpoint create` if the fix spans files. Make the smallest change that removes the cause.
- `V verify` (contracted command: repro + related suite). Two failed attempts → `V rollback` and re-think the cause, or escalate with the compacted trace.
- `V gate` → paste the Evidence Block.

## 6. Make it stick
- Keep the repro test in the suite (it is now the regression test).
- `V remember "<cause> → <fix>; watch <file/pattern>" --kind pitfall`

Final answer format: **Symptom · Root cause · Fix · Regression test · Evidence Block.**
