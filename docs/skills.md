# The Veratum skill pack

All skills live in `skills/` and install through [skills.sh](https://skills.sh/yadavmandeep/veratum).
`veratum` is the foundation: it carries the engine. The other skills add a focused workflow on top of it.

| Skill | Trigger it when… | What it adds |
|---|---|---|
| **veratum** | Any code change | 6-gate protocol, project memory, blast radius, checkpoints, compacted verify, cryptographic gate |
| **veratum-debug** | Bug, crash, flaky test, regression | Reproduce first (failing check recorded *before* the fix), root-cause statement, banned "fixes", regression test kept |
| **veratum-review** | Reviewing a PR/branch/diff | Read-only. Depth-2 blast radius per changed file, runs existing checks, findings need evidence (`path:line`, failing scenario) |
| **veratum-refactor** | Renames, extractions, moves, upgrades | Green baseline required, characterization tests, one checkpoint per step, every caller in scope, zero behaviour change |
| **veratum-highstakes** | Auth, payments, PII, migrations, deletes, infra | Written risk plan, negative tests, rollback plan for code *and* data, user sign-off before irreversible actions, 1 retry max |
| **veratum-typescript** | TS/JS projects | Package-manager detection, one-shot test runners, alias/barrel blast radius, TS/React/Next.js pitfalls |
| **veratum-python** | Python projects | uv/poetry/venv detection, module-style test runs, Django migration drift check, Python pitfalls |

The core skill also ships **reasoning guides** in `skills/veratum/references/`, which the agent loads only when needed (they're also copied to `.veratum/references/`):

| Guide | Use it for |
|---|---|
| `reconnaissance.md` | Learning the minimum from the cheapest source (brain → impact → targeted reads) |
| `contracts.md` | Writing an observable goal, an exact scope and a one-shot verify command. Plan vs implement |
| `verification.md` | What counts as evidence per change type, reading results, what never counts |
| `recovery.md` | Root-cause loop, what each Veratum failure signal means, rollback, escalating well |
| `planning.md` | Effort scaling, plan-mode deliverables, splitting large work, parallel sub-agents |

## Install

```bash
# just the core
npx skills add yadavmandeep/veratum --skill veratum --agent <ide> --yes

# core + specific skills
npx skills add yadavmandeep/veratum --skill veratum --skill veratum-debug --skill veratum-typescript --agent <ide> --yes

# the whole pack
npx skills add yadavmandeep/veratum --agent <ide> --yes

# browse what's in the repo first
npx skills add yadavmandeep/veratum --list
```

## Writing your own Veratum skill

A companion skill is a folder with a `SKILL.md`. Its frontmatter needs `name` (lowercase, hyphens, ≤ 64 chars, same as the folder name) and `description` (≤ 1024 chars, saying *when* to use it). Build on the core engine commands (`V contract`, `V verify`, `V gate`) rather than re-implementing them. The test suite checks every skill's frontmatter.
