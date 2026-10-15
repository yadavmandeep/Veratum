# Verification — evidence, not opinion

A passing check is evidence only if it **could have failed** for the bug you fixed or the feature you added.

## Choosing what to run
| Change | Minimum evidence |
|---|---|
| Bug fix | A test that failed before the fix and passes after it (run it before editing) |
| Feature | New tests for the behaviour + existing tests of touched modules + typecheck |
| Refactor | The full suite of every module in the blast radius, unchanged and green before and after |
| Config/infra | The command that consumes the config (build, migrate --dry-run, plan) |
| Docs only | Link/format check if the repo has one. Otherwise say "no executable check applies" |

## Claims and the evidence they need
| You want to say | You need to have seen |
|---|---|
| "Fixed" | The reproducing test fail before the change and pass after it, both in this task |
| "Tests pass" | `✅ [VERATUM VERIFIED]` for the contracted command, with a test count greater than 0 |
| "No regressions" | The tests for every dependent in the blast radius, green after your final edit |
| "Done" | `✅ [VERATUM COMPLETION GATE PASSED]` and its evidence block |
| "Reviewed, no issues" (review mode) | The files you actually read, listed. Not "looks fine" |
| Anything you could not run | Say so explicitly: "not verified: <what> because <why>" |

## Reading results
- Exit code 0 with "0 tests ran" or "no tests found" is **not** a pass. Fix the selector.
- Skipped tests near your change: find out why they were skipped.
- Read the compacted trace from the **first** failing frame inside your code, not the last line.
- Flaky? Prove it: `verify --force` once, and say so in your evidence. Don't loop.

## Things that are never verification
- "The code looks right" / self-review.
- Running a different, easier command than the contracted one (the gate rejects it).
- Weakening assertions, deleting tests, adding `skip`/`xfail`/`only`, catching errors to silence them.
- A pass recorded before your last edit (the tree hash catches it).

## After green
Run `V gate` right away. Any further edit, even a comment, invalidates the proof by design.
