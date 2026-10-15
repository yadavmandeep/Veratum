# Writing a good contract

A contract states what "done" means and what you may touch. Get it right and the rest of the gates are mechanical.

## Goal: one sentence, observable
- ✗ "Improve the pagination code"
- ✓ "Paginated `/users` returns every record exactly once when page size divides the total"

## Files: exact, not hopeful
- List every file you expect to change, **plus its test file**.
- Every dependent in the blast radius whose usage changes (renamed export, new parameter, different return shape) belongs in the contract.
- Prefer exact paths. Use `dir/` or `glob/*` only for generated or mechanical changes, such as a rename across a folder.
- Too narrow is cheap to fix (`--extend`). Too broad hides scope creep.

## Verify: the narrowest command that proves the goal, plus the guard rails
`"<targeted test> && <typecheck>"`, for example `"pnpm vitest run src/users && pnpm tsc --noEmit"`.
- It must fail before your change if you are fixing a bug (see `veratum-debug`).
- It must be one-shot: no watch mode, no interactive prompts.
- Include the tests the impact report suggests for HIGH-risk dependents.

## Mode and profile
- Unclear requirements, or the user asked for a plan → `--mode plan`. Present the plan, then `contract --mode implement` once the user approves.
- `--mode review` for read-only reviews.
- Leave `--profile auto` unless you have a reason. Veratum raises the profile to `deep`/`highstakes` for wide blast radius or sensitive paths (auth, payments, migrations, infra).

## When to re-contract
- The goal changed → lock a new contract.
- You need one more file → `--extend` it, and say why in your reasoning.
- You found a separate bug → don't fix it inside this contract. Report it, or `remember` it as a pitfall.
