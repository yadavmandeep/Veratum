# Using Veratum

## Prompts

Veratum activates on its own for coding work. These prompts make the intent explicit:

| Goal | Prompt |
|---|---|
| Fix a bug | `Use Veratum to fix <symptom> and verify it.` (or `Use veratum-debug …`) |
| Build a feature | `Use Veratum to add <feature>. Verify with <command>.` |
| Review | `Use veratum-review to review this branch. Do not modify files.` |
| Refactor | `Use veratum-refactor to extract <x> into its own module without behaviour changes.` |
| Risky change | `Use veratum-highstakes to <migration / auth change>. Ask me before anything irreversible.` |
| Plan only | `Use Veratum in plan mode: lock no contract, just show the blast radius and a plan.` |

## What you'll see

1. **Brain sync**: the agent reads memory instead of re-exploring the repo.
2. **Contract**: goal, files, verify command, and the blast radius (who imports the files being changed).
3. **Checkpoint** before multi-file edits.
4. **Verify**: one line on success. On failure, a compacted trace like this:
   ```text
   ❌ [VERATUM FAILED] `pytest -q` → EXIT 1 (attempt 1 of 2)
   ──── COMPACTED ERROR TRACE (306 → 9 lines, ~95% tokens saved) ────
     File "src/calc.py", line 42, in divide
   ZeroDivisionError: division by zero
   FAILED tests/test_calc.py::test_divide
   ```
5. **Gate** + **Evidence Block** in the final answer.

If the agent edits anything after verifying, the gate prints:
```text
🛑 [VERATUM COMPLETION GATE BLOCKED]
   ✗ POST-VERIFICATION EDIT DETECTED … changed after verify: src/math.ts
```

## Command reference

`V` = `python3 .veratum/engine/veratum_cli.py` (on Windows, `python`)

| Command | What it does |
|---|---|
| `V init [--rescan]` | Create `.veratum/`, detect stack and commands |
| `V brain show` | Project memory |
| `V remember "<fact>" --kind insight\|decision\|pitfall\|architecture\|command` | Save a learning |
| `V brain set-cmd <test\|build\|lint\|typecheck> "<cmd>"` | Pin a command |
| `V brain forget <id>` | Delete a memory |
| `V contract --goal "…" --files "a,b,dir/,glob/*" --verify "<cmd>" [--mode plan\|review] [--profile auto\|eco\|balanced\|deep\|highstakes]` | Lock a task |
| `V contract --mode implement` | Leave plan/review mode on the active contract (after approval) |
| `V contract --extend "<files>"` / `--show` / `--abandon` | Change / view / drop the contract |
| `V impact <file> [--depth 2] [--symbol X] [--evidence] [--json]` | Blast radius: dependents + the exports they use, git co-change history, dynamic mentions, related tests. `--evidence` (always on with `--json`) adds `file:line` proof per relationship, labelled `EXTRACTED` (import statement resolved) or `INFERRED` (name match, git history, test naming) |
| `V graph build [--full] [--max-files N] [--max-file-kb K]` | Build/refresh the knowledge graph in `.veratum/graph/` (`graph.json`, `GRAPH_REPORT.md`, `cache.json`). **Takes every file by default** (no cap); `--max-files N` limits it, `--max-file-kb K` (default 1024) skips huge generated/minified sources. Incremental: files with the same size and modification time are not even re-hashed, changed ones are re-parsed. Prints progress on big repos |
| `V graph query "<question>" [--mode bfs\|dfs] [--depth 2] [--budget 2000]` | Token-budgeted subgraph for a question; every node/edge shows `file:line` and EXTRACTED / INFERRED / AMBIGUOUS |
| `V graph path <A> <B>` · `graph explain <node>` · `graph report` · `graph benchmark "<q>"` · `graph status` | Shortest relationship path, one node's neighbours, god nodes/communities/surprising links, corpus-vs-subgraph token ratio, stale-file check. MCP: `veratum_graph` |
| `V graph export [--format html\|svg\|obsidian\|cypher\|all] [--out dir] [--max-nodes 200]` | Picture, Obsidian vault, Neo4j script (default `.veratum/graph/export/`) |
| `V graph watch` | Rebuild automatically while files change |
| `V graph semantic list` / `add --data '{…}'` | PDFs/images/docs waiting for notes / store concepts your agent extracted from them |
| `V check-scope <file>` | May this file be edited now? |
| `V explain-shell "<cmd>"` | How the shell guard classifies a command, and what it would write |
| `V checkpoint create [--label …]` / `list` | Shadow snapshot |
| `V rollback [id]` | Restore a checkpoint (the current state is saved first, so you can undo it) |
| `V verify ["<cmd>"] [--force]` | Run validation, compact the log, bind the tree hash (`--force` re-runs a failure on unchanged code, for flaky tests only) |
| `V gate [--dry-run]` | Completion gate + Evidence Block |
| `V audit` | Verify the hash-chained evidence log |
| `V status [--json]` | Contract, ledger, freshness, changed files |
| `V config` / `config <name>` / `config <name> <value>` | List, read or change a setting: `graph_auto` (auto\|refresh\|off), `compact_max_lines`, `verify_timeout_sec`. Enforcement settings (`enforcement`, `protected_paths`, …) are deliberately not settable here, so an agent cannot switch the guards off; edit `.veratum/config.json` by hand for those |
| `V doctor` | Health check |

## MCP tools (Cursor, Windsurf, Cline, Copilot, OpenCode)

`veratum_get_brain`, `veratum_remember`, `veratum_lock_contract`, `veratum_impact`, `veratum_graph`, `veratum_check_scope`, `veratum_explain_shell`, `veratum_checkpoint`, `veratum_verify`, `veratum_check_gate`, `veratum_audit`, `veratum_status`. They behave exactly like the CLI commands above.

## Codebase graph

On by default. At session start Veratum builds `.veratum/graph/` automatically for repos up to 1500 source files (bigger repos: run `graph build` once, it then takes every file and the session-start hook keeps it fresh) and refreshes it whenever files changed; `graph query`, `path`, `explain` and `report` also refresh a stale graph first. The session-start text tells the agent to query the graph before grepping, and the generated rule files for Cursor, Windsurf, Cline, Copilot and OpenCode say the same.

* **Settings:** `python .veratum/engine/veratum_cli.py config graph_auto <value>`: `auto` (default: build if missing, then keep fresh), `refresh` (never build, only refresh an existing graph), `off`. It is stored as `"graph_auto"` in `.veratum/config.json`.
* **What is in it:** files, functions, classes, Markdown docs (headings, links, `` `code` `` mentions), PDFs/images as nodes. Imports are `EXTRACTED`; name-resolved calls are `INFERRED`; several candidates are `AMBIGUOUS`. Every edge has `file:line`.
* **Communities:** Louvain modularity clustering (stdlib), oversized communities are split again; see `GRAPH_REPORT.md`.
* **PDFs, images, prose:** Veratum has no model of its own. `graph semantic list` shows what is waiting; the agent reads each file and stores concepts with `graph semantic add`. Those notes are untrusted: they can only be `INFERRED`/`AMBIGUOUS`, are capped, and are dropped when the source file changes.
* **Exports:** `graph export` is self-contained (no CDN, no network). The Neo4j output is a `.cypher` script for `cypher-shell`.
* **Git:** `.veratum/graph/` is generated and is ignored automatically (`init` writes `graph/` into `.veratum/.gitignore`, and older installs get the line on the next `init`). To keep the whole `.veratum/` folder out of git, put `.veratum/` in your project's `.gitignore`.
