# Planning & effort — spend effort where the risk is

## Scale the process to the task
| Task | Process |
|---|---|
| Question / explanation | No contract. Answer from the brain + targeted reads |
| Typo, copy, single obvious line | 1-file contract (profile `eco`), verify, gate |
| Normal feature or bug | Full 6 gates (profile `balanced`) |
| Wide blast radius, multi-module | `deep`: depth-2 impact, checkpoint before the first edit |
| Auth, payments, data, migrations, infra | `highstakes`: plus the `veratum-highstakes` skill, 1 retry, user sign-off before irreversible steps |

`--profile auto` picks this for you from paths and blast radius. Trust it unless you know better, and if you override it, say why.

## Plan mode
Use `contract --mode plan` when requirements are ambiguous, the change is large, or the user asked for a plan. File changes are blocked (action lock), so you can only investigate. Deliver:
1. Goal and non-goals.
2. Approach, plus the alternative you rejected and why.
3. Steps. Each step is one checkpointed, verifiable change.
4. Files per step, taken from the blast radius.
5. Verification per step, and for the whole change.
6. Risks and the rollback plan.

Then stop and wait. Once the user approves: `contract --mode implement`.

## Splitting large work
If the plan has more than ~5 steps or touches more than ~10 files, propose separate contracts, each with its own verify and gate. Small, proven increments beat one large unverified change.

## Parallel work (sub-agents)
Only split work that touches disjoint files. Give each sub-agent its own contract scope. Gate the whole result once, at the end, in the parent session.
