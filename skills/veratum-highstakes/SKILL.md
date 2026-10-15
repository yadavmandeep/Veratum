---
name: veratum-highstakes
description: Maximum-assurance mode of Veratum for risky changes - authentication, authorization, payments, data migrations, deletions, cryptography, infrastructure and production config. Adds a written risk plan, depth-2 blast radius, mandatory checkpoint and rollback plan, negative tests, and explicit user sign-off before anything irreversible.
version: 1.0.0
author: Mandeep Yadav
license: MIT
---

# Veratum High-Stakes — for changes you cannot take back

Use when the change touches **auth, permissions, money, PII, schemas/migrations, data deletion, crypto, secrets, infra or prod config**. Everything in the `veratum` skill applies, plus the rules below.
`V` = `python3 .veratum/engine/veratum_cli.py`.

## 1. Risk plan first (write it in chat before any edit)
- **What could go wrong:** data loss, privilege escalation, double charge, lockout, downtime. Be concrete.
- **Blast radius:** `V impact <file> --depth 2` for every target. List the dependents you read.
- **Verification:** the positive tests *and* the negative ones (denied access stays denied, invalid input is rejected, a failed payment does not charge).
- **Rollback:** how to undo it in code (`V checkpoint`) **and** in data/infra (down-migration, backup, feature flag).

## 2. Contract with the strictest verify
`V contract --goal "<goal>" --files "<exact files, no broad globs>" --verify "<tests incl. negative cases> && <typecheck> && <lint>"`
Then `V checkpoint create --label "pre-highstakes"`.

## 3. Execution rules
- Never weaken a security check, widen a permission, disable validation or log secrets/PII to make something work.
- Migrations: reversible and idempotent, tested on a copy, never mixed with application logic in one step.
- **Stop and ask the user before anything irreversible or outside the repo:** running migrations on shared databases, deleting data, rotating keys, deploying, force-pushing. Show the exact command and wait for a clear yes.

## 4. Verification
- `V verify` must pass with the full contracted command. One retry, not two: a second failure → `V rollback` and escalate with the compacted trace.
- Read every dependent at depth 1 once more after the change.

## 5. Completion
`V gate`, then report: risk plan · what changed · negative tests that passed · rollback procedure · Evidence Block · anything still unverified (say it explicitly).
`V remember "<invariant that must never break>" --kind decision`.
