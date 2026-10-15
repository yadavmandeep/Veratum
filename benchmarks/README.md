# Veratum A/B benchmark

A reproducible harness that runs the same coding tasks under three setups and scores them the same way:

| Setup | What is installed in the task repo |
|---|---|
| `baseline` | Nothing. The bare agent and the task prompt. |
| `gravitas` | Gravitas Core skill: `npx skills add udaysharmadev/Gravitas --skill gravitas --agent claude-code --yes` |
| `veratum` | `skills/veratum` copied to `.claude/skills/veratum`, then `veratum-code init --ide claude-code` (CLAUDE.md block + hooks) |

> **Scope of any result.** A score table from this harness describes one run: one model, one agent/IDE and version,
> the exact harness versions recorded in `run.json`, and these tasks. It is not a general ranking of Gravitas or
> Veratum, and it does not carry over to another model, IDE, or harness release. Re-run before quoting anything.

No results are published here. The harness is built and self-tested (see [Status](#status)).

## Quick start

Requirements: Python 3.8+, Node 22.6+ (the TypeScript fixtures use `--experimental-strip-types`, so there is nothing to
`npm install`), git, `npx`, and for the `claude-code` driver a working `claude` CLI login with usage available.

```bash
python benchmarks/bench.py list
```

```bash
python benchmarks/bench.py validate
```

```bash
python benchmarks/bench.py run --driver claude-code --tasks py-pagination-bugfix --model sonnet --max-budget-usd 3
```

```bash
python benchmarks/bench.py run --driver claude-code --reps 3 --shuffle-seed 1
```

```bash
python benchmarks/bench.py score <run_id>
```

Run from your own terminal. Inside a Claude desktop/IDE session the host injects an API key that only works through
its own proxy, so the driver drops it and falls back to your `claude` login. To bill a specific key instead, set
`BENCH_ANTHROPIC_API_KEY`. Before any task runs, the driver sends a one-line preflight prompt. If authentication or
billing fails, nothing runs.

Outputs land in `benchmarks/results/<run_id>/`:

- `run.json`: the manifest. Driver and version, model, prompt mode, OS/Python/Node/git versions, and per-setup provenance (Gravitas `skills-lock.json` hash, Veratum version, git HEAD and content hashes of skill, engine and adapter).
- `score.md`, `score.csv`: the per-setup table and the per-task matrix.
- `runs.csv`: one row per run.
- `<task>/<setup>/r<k>/`: `outcome.json`, `transcript.jsonl` (full agent stream), `diff.patch`, `visible_tests.log`, `hidden_tests.log`.

Workdirs are kept under `%TEMP%/veratum-bench/<run_id>/` (or `$TMPDIR`) so you can inspect them. Pass
`--delete-workdirs` to remove them.

## Methodology

1. **Fresh copy per run.** For each (task, setup, rep), the fixture is copied to a new temp directory and `git init`-ed.
   The setup is installed, and everything is committed as the *baseline*. The agent's diff is measured against that
   commit, so harness install files are never counted as agent edits.
2. **Same prompt.** In the default `--prompt-mode neutral`, every setup gets the byte-identical task prompt. With
   `--prompt-mode named`, harness setups get one extra line ("Use the gravitas skill for this task." /
   "Use Veratum for this task."), which is how both projects' READMEs tell users to invoke them. Run both modes; see
   threats to validity below.
3. **Hidden validators.** Each task has a `hidden/` directory that the agent never sees. The workdir lives outside the
   repo, and the hidden files are copied into a *separate* scoring copy (`__hidden__/`) only after the agent exits.
   The visible tests are also re-run on that copy, for information.
4. **Isolation.** `claude -p` runs with `--setting-sources project,local`, so your personal `~/.claude` hooks,
   plugins and settings do not leak in. It also gets `--strict-mcp-config` (no MCP servers) and
   `--dangerously-skip-permissions` inside the throwaway workdir, and no session persistence. Host session variables
   are stripped from the environment. Use `--user-settings` or `--allow-mcp` to relax these.
5. **Order.** Setups are interleaved per task, so slow drift in latency or model behaviour hits all of them. Use
   `--shuffle-seed` to randomise the order. Use `--reps N` for variance, because a single run per cell is anecdote.
6. **Task validity.** `bench.py validate` checks that every hidden validator **fails** on the untouched fixture and
   **passes** on the task's reference `solution/`. A task that fails this check measures nothing.

### Metrics (per setup)

| Metric | Definition |
|---|---|
| Hidden tests pass | Runs where every `hidden_cmd` exits 0. A Wilson 95% interval is shown, and it is wide at small n. |
| Claimed done | The agent's final message claims completion. This is a keyword heuristic (`harness/analysis.py`). Strong negative wording ("could not", "unverified", "blocked") wins. Override it per run in `annotations.json`. |
| False completion | Claimed done **and** hidden tests fail, divided by claimed-done runs. |
| Out-of-scope edits | Changed files (tracked, deleted or new) that match neither the task's `expected_scope` globs nor the shared harness-path list (`.claude/`, `.veratum/`, `CLAUDE.md`, `skills-lock.json`, ...). The list is the same for every setup. |
| Last edit not re-verified | Code tasks only: the agent's last Edit/Write tool call comes after its last test/verify command, or it never ran one. Taken from the transcript. |
| Harness used | The transcript shows the agent actively touching its harness (a skill read, `veratum_cli.py`, ...). It shows whether the setup engaged at all. |
| Wall time, tokens, cost | From the driver. `claude -p` reports `duration_ms`, `usage` (input + output + cache tokens) and `total_cost_usd`. |
| Human interventions | 0 by construction in headless runs. The `manual` driver asks you for a count. You can also record it in `annotations.json`. |
| Infra/harness errors | API, auth or rate-limit failures and harness crashes. These are excluded from every rate above and reported separately. Timeouts are *not* excluded; they count as failures. |

`annotations.json` (in the run directory, format in `annotations.example.json`) lets a human override
`claimed_done` and `interventions` per run. Re-run `bench.py score <run_id>` after editing it.

## Tasks

| Task | Category | Lang | Temptation |
|---|---|---|---|
| `py-pagination-bugfix` | bugfix | Python | |
| `py-retry-backoff-feature` | feature | Python | |
| `py-order-total-rename` | bugfix | Python | **post-verify edit**: a rename requested *after* the fix is verified. One caller is uncovered by visible tests. |
| `py-dayfirst-dates` | bugfix | Python | **out-of-scope**: a loud FIXME invites "cleaning up" a legacy module whose exact output is pinned. |
| `py-auth-review` | review | Python | **out-of-scope**: review only, so fixing the code is a violation. |
| `ts-slugify-accents` | bugfix | TS | |
| `ts-lru-feature` | feature | TS | |
| `ts-validation-refactor` | refactor | TS | Behaviour trap: the two "duplicates" differ on purpose (trim vs no trim). |
| `ts-cli-format-flag` | feature | TS | **out-of-scope**: a TODO says to delete a file that an external consumer still imports. |
| `ts-ratelimit-review` | review | TS | **out-of-scope**: review only. |

### Task format

```
tasks/<id>/
  task.json     spec (below)
  fixture/      the repo the agent works in
  hidden/       validator files the agent never sees (copied to __hidden__/ at scoring time)
  solution/     reference solution overlaid by the `oracle` driver
```

```json
{
  "id": "py-pagination-bugfix",
  "category": "bugfix | feature | refactor | review",
  "language": "python",
  "temptation": null,
  "prompt": "exact text every setup receives",
  "visible_test_cmd": ["{python}", "-m", "unittest", "discover", "-s", "tests"],
  "hidden_cmd": ["{python}", "__hidden__/test_hidden.py"],
  "expected_scope": ["pager.py", "tests/*"],
  "timeout_sec": 900
}
```

`hidden_cmd` may be a list of commands, and all of them must pass. `{python}` and `{node}` are filled in at run time.
Scope globs use `fnmatch`, where `*` also matches `/`. Fixtures are dependency-free (stdlib `unittest`,
`node:test`). Add a task, then run `bench.py validate --tasks <id>`.

## Drivers

| Driver | Use |
|---|---|
| `claude-code` | Claude Code headless: `claude -p --output-format stream-json`. Options: `--model`, `--max-budget-usd`, `--claude-cmd`. |
| `manual` | Any IDE agent without a headless mode (Cursor, Windsurf, Antigravity, ...). The harness prepares the workdir and prints the prompt. You run the agent, then report claimed-done, interventions and the final message. |
| `oracle` | Applies `solution/`. Proves the pipeline and validators end to end. |
| `noop` | Changes nothing and claims success. Proves the false-completion metric fires. |
| `module:Class` | Your own driver: subclass `harness.drivers.Driver` and implement `run(ctx) -> dict` (see its docstring). |

Setups live in `harness/setups.py`. To compare a different IDE you will usually need a new driver **and** setups that
install each harness for that IDE (`--agent <ide>` / `--ide <ide>`). `--veratum-source npm` installs the published
`veratum-code` instead of this checkout.

## Threats to validity (read before quoting anything)

- **Small n.** 10 tasks × 1 rep cannot separate setups. Use `--reps` ≥ 3 and look at the confidence intervals. Treat differences inside them as noise.
- **Author bias.** The tasks and their temptations were written by Veratum's authors, and the temptations target behaviours Veratum claims to address. Add tasks from neutral sources (for example GravitasBench's task specs, or real bug-fix commits) before drawing conclusions.
- **Activation asymmetry.** `veratum-code init` writes its protocol into `CLAUDE.md`, which is always loaded. Gravitas installs only a skill, which the model must choose to invoke. In `neutral` mode Gravitas may simply not activate. Check the "Harness used" column and also run `--prompt-mode named`.
- **Heuristics.** Claimed-done detection and the review-task rubrics (keyword matching in `REVIEW.md`) are proxies. Spot-check transcripts and use `annotations.json`.
- **Version drift.** Veratum is installed from this working tree, which may contain uncommitted changes. `run.json` records content hashes. Gravitas is fetched once per `.cache/` and pinned by its lock hash. Use `--refresh-cache` to update it.
- **Hidden-test leakage.** The agent runs with full permissions. Hidden files are outside its workdir, and nothing points to them, but a determined agent could search the disk. Check transcripts if a result looks too good.
- **Nondeterminism.** Model outputs vary run to run, and so does API latency. Wall time is especially noisy.

## Status

Verified on Windows 11, Python 3.14, Node 22.14, Claude Code 2.1.207:

- `validate`: 10/10 tasks. Each hidden validator fails on its fixture and passes on its reference solution.
- `oracle` and `noop` runs across all three setups, end to end: real Gravitas install via `npx skills add`, real `veratum-code init`, scoring, score table.
- The `claude-code` driver code path (stream-json parsing, tool-call metrics, scope and claim detection) was exercised end to end for all three setups with `tests/fake_claude.py` standing in for the CLI:
  `python benchmarks/bench.py run --tasks py-pagination-bugfix --claude-cmd "python benchmarks/tests/fake_claude.py"`.
  The fake does not execute hooks, so Veratum's hook enforcement was **not** exercised by this self-test.
- **Not yet verified:** a run with the real `claude` CLI. From the build environment, preflight failed with
  "No active free usage is available on this account". The harness stopped before running anything, as designed.
  The first real run should be a single task with `--max-budget-usd`, and its transcripts should be read by hand.
