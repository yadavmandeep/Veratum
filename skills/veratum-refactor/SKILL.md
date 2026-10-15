---
name: veratum-refactor
description: Behaviour-preserving refactoring with Veratum. Use for renames, extractions, module moves, dependency upgrades and cleanup - pins current behaviour with characterization checks, checkpoints before each step, follows the blast radius to every caller, and proves nothing changed with the Veratum completion gate.
version: 1.0.0
author: Mandeep Yadav
license: MIT
---

# Veratum Refactor — change the shape, never the behaviour

`V` = `python3 .veratum/engine/veratum_cli.py` (install with `npx skills add yadavmandeep/veratum --skill veratum` if missing).

## 1. Map before you move
- `V brain show`, then `V impact <each file you will touch> --depth 2`.
- Every dependent goes into the contract. A rename with 14 callers is a 15-file change, so scope it that way:
  `V contract --goal "Refactor: <what>, no behaviour change" --files "<targets>,<all dependents>,<tests>" --verify "<full suite + typecheck>"`

## 2. Pin current behaviour
- Run the contracted verify **before** any edit: `V verify`. It must pass. If it doesn't, stop: you can't refactor on a red baseline.
- Weak coverage around the target? Add characterization tests first (assert what the code does today, even if odd), verify, then refactor.

## 3. Small steps, each one green
For each step (rename, extract, move, inline):
1. `V checkpoint create --label "step N: <what>"`
2. Apply only that step. Update every caller from the blast radius in the same step.
3. `V verify`. Red? Fix it right away, or `V rollback` and take a smaller step. Never stack a second step on a red one.

## 4. Rules
- No functional changes, bug fixes or "while I'm here" improvements. Note them for the user instead.
- Public APIs keep working (re-export or deprecate) unless the user approved a break.
- Don't edit test assertions, except to change the names the refactor itself renamed.

## 5. Finish
`V gate` → Evidence Block. Then
`V remember "<new structure / where things moved>" --kind architecture` so future sessions find the new layout without re-reading it.
