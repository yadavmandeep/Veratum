# Concepts

## `.veratum/` layout

| File | Commit it? | Purpose |
|---|---|---|
| `brain.json` | **yes** | Project memory: stack, commands, module map, insights, pitfalls, task history |
| `config.json` | yes | Enforcement settings, installed adapters |
| `engine/` | yes | The runtime, so every IDE config points to one place: `veratum_cli.py` (gates, contract, hooks, CLI), `veratum_graph.py` (codebase graph), `veratum_export.py` (graph exports), `mcp_server.py`. All four are installed together |
| `contract.json` | no | The active task |
| `ledger.json` | no | Verification evidence bound to a tree hash |
| `baseline.json`, `snapshots/`, `state.json` | no | Diff baselines, checkpoint index, hook counters |
| `logs/last_run.log`, `logs/history.jsonl` | no | Full raw output of the last verify, append-only event log |

## Brain

Cross-session memory. `init` fills in the stack and the default commands (from `package.json`, `pyproject.toml`, `Cargo.toml`, `go.mod`, Maven/Gradle, `Makefile`). Verified commands are learned automatically (`known_good_commands`). Agents add insights with `remember`, and each completed task is appended to `task_history`.

## Contract

`goal`, `files` (paths, `dir/` prefixes, `glob/*` patterns), `verify` command, blast-radius `impact`, and a **baseline snapshot** of the workspace taken when it's locked. Locking a contract resets the ledger to `IN_PROGRESS`.

## Modes and risk profiles

- **Mode** `implement` (default), `plan` or `review`. Plan and review are an **action lock**: edits and file-writing shell commands are blocked. The gate passes only if nothing changed, and the contract stays open across turns, so you can go plan → user approval → `contract --mode implement`.
- **Profile** is picked automatically (`--profile auto`) from what the change touches:

| Profile | Chosen when | Rules |
|---|---|---|
| `eco` | single isolated file | depth-1 impact, 2 retries, short logs |
| `balanced` | normal change | + read-before-write |
| `deep` | > 8 dependents or > 6 paths | depth-2 impact (+ dynamic mentions), checkpoint required before the first edit |
| `highstakes` | auth, payments, PII, migrations, infra, CI, prod config | depth-2, checkpoint required, **1** retry |

## Read-before-write and stale reads

Hooks record what the agent reads (Read / `view_file` / `cat` / Cursor `beforeReadFile`), together with the file's SHA-256. An edit to an existing file is blocked if the file was never read in this task, or if it changed since that read (a formatter, a shell command or another process wrote to it). The agent's own edits refresh its view, so it can keep editing a file it just wrote.

## Shell guard

Every shell command is tokenized (quotes, pipes, `&&`/`;`, redirects, `cd`, env prefixes, `sudo`/`npx` wrappers, nested `bash -c`) and given a capability level: `read < exec < network < write < install < destructive`. Before the command runs:
- writes to files outside the contract are blocked (gitignored targets are fine)
- package installs that change a manifest need the manifest in scope
- destructive commands need a recent checkpoint
- plan/review mode blocks anything above `network`
- writes to Veratum evidence are blocked
Programs Veratum can't see inside (`npm test`, `make`) are `exec`. Anything they change is still caught afterwards by scope-drift detection and the tree hash.

## Failure intelligence

- **Duplicate-failure guard**: re-running a command that already failed on the *identical* tree is refused (exit 3). It can't produce new information. `--force` exists for flaky tests.
- **Failure signature**: a fingerprint of the error lines and locations (timings and addresses are ignored). If an attempt fails with the same signature after a code change, Veratum says *SAME FAILURE*: the edit missed the cause.

## Evidence chain

`logs/history.jsonl` is append-only and hash-chained: each record stores `prev` and `hash = sha256(prev + canonical JSON)`. A `PASSED` ledger must point (`evidence_hash`) to an intact `verify` record whose tree hash, command, exit code and contract match. Editing the log, deleting a record, or hand-writing `ledger.json` makes `gate` and `audit` fail.

## Tree hash

A content fingerprint of every non-ignored file: SHA-256 over sorted `(path, blob id)` pairs.
- In git repos, clean files use the index blob id. Modified and untracked files are hashed with `git hash-object`. So **staging and committing don't change it**, but any byte edit, new file or deletion does.
- Outside git, every file is SHA-256-hashed (common build/dependency folders are skipped).
- `.veratum/` is excluded, so writing memory never invalidates evidence.

## Ledger

`verify` writes `status` (`PASSED`/`FAILED`), `command`, `exit_code`, `duration`, `tree_hash`, `contract_id`, and a 20-run history. Hooks flip `PASSED` → `STALE` as soon as the tree changes.

## Completion gate

Passes only when **all** of these are true:
1. a contract is active
2. the ledger is `PASSED` for **this** contract
3. the passing command **is** the contracted verify command
4. the current tree hash **equals** the verified tree hash
5. nothing outside the contract changed since the baseline (**scope drift**)

When it passes, the contract is closed, the task goes into the brain's history, and the Evidence Block is printed.

## Checkpoints

`checkpoint create` copies the git index into a temporary one, runs `git add -A` (excluding `.veratum/`), writes a tree, and stores a commit under `refs/veratum/checkpoints/<id>`. Your worktree, index, branches and `git stash` are untouched. `rollback` first takes a safety checkpoint of the current state, then restores tracked and untracked files and removes files created after the checkpoint.

## Compaction

Failed verify output is reduced to error lines, stack traces, `file:line` locations, assertion diffs and the summary tail (≤ 40 lines by default). Passing-test noise, progress bars and ANSI codes are dropped. The full log is always in `.veratum/logs/last_run.log`.
