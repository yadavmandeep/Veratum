---
name: veratum-review
description: Evidence-based, read-only code review with Veratum. Use when asked to review a diff, PR, branch or file for bugs, regressions and risk - computes the blast radius of every changed file, runs the existing checks, and reports only findings it can back with code or command output. Never edits files.
version: 1.0.0
author: Mandeep Yadav
license: MIT
---

# Veratum Review — findings you can prove, nothing you can't

Read-only. **Do not edit, format, or "quickly fix" anything** unless the user explicitly asks afterwards.
`V` = `python3 .veratum/engine/veratum_cli.py` (install with `npx skills add yadavmandeep/veratum --skill veratum` if missing).

## 1. Load context cheaply
`V brain show` for stack, commands, architecture decisions and known pitfalls. They are the review checklist for this repo.

## 2. Establish the change set
- Use what the user pointed at (PR, branch, commit range, files). Otherwise: `git diff --stat HEAD` and `git status`.
- List the changed files. Read each change **with its surrounding code**, not just the hunk.

## 3. Blast radius for every changed source file
`V impact <file> --depth 2` — read the direct dependents' call sites of anything whose signature, return shape, error behaviour or side effects changed. Most real regressions live here, outside the diff.

## 4. Run the evidence you are allowed to run
Run the repo's existing read-only checks (tests, typecheck, lint from the brain) through `V verify "<cmd>"` so the result is logged and compacted. Never modify tests or config to make them pass.

## 5. Report
Only report what you can support. For each finding:

| Field | Content |
|---|---|
| **Severity** | blocker · major · minor · nit |
| **Where** | `path:line` |
| **What breaks** | concrete input/state → wrong result, crash, data loss, security impact |
| **Evidence** | the code path, a dependent from the blast radius, or failing output |
| **Suggested fix** | one or two lines, not a rewrite |

Then: changed files, dependents inspected, checks run with exit codes. If nothing survives verification, say so plainly — an empty review is a valid result.
Skip style opinions unless the repo's own conventions (brain or linter) say otherwise.
