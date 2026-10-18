# 📖 Using Veratum

Veratum equips AI agents with deterministic engineering discipline, AST-level architectural context, and cryptographic verification guarantees.

---

## 🎯 Intent Prompts

Veratum engages automatically on coding tasks when installed. Use the following explicit prompt patterns to activate specific operational profiles:

| Task Objective | Recommended Prompt Syntax | Target Operational Profile |
|---|---|---|
| **Bug Fix** | `Use Veratum to fix <symptom> and verify with <command>.` | `balanced` / `auto` |
| **New Feature** | `Use Veratum to implement <feature>. Verify with <command>.` | `balanced` |
| **Architectural Review** | `Use veratum-review to inspect this branch. Do not modify files.` | `review` (no write access) |
| **Safe Refactor** | `Use veratum-refactor to extract <module> without behavioral regressions.` | `deep` (checkpoint mandatory) |
| **High-Stakes Change** | `Use veratum-highstakes to perform <migration/auth change>. Prompt before destructive actions.` | `highstakes` (depth-2 impact, 1 retry) |
| **Blast Radius & Plan** | `Use Veratum in plan mode: do not edit files, produce blast radius and step-by-step plan.` | `plan` (file changes locked) |

---

## 🔄 The 6-Gate Lifecycle in Action

Every task executed under Veratum advances strictly through 6 non-bypassable gates:

1. **Gate 0 — Brain Sync (`brain show`):** Reuses pinned commands, architectural rules, and past failure postmortems rather than wasting tokens on re-exploration.
2. **Gate 1 — Contract & Blast Radius (`contract`):** Locks the exact scope tuple `{ goal, files, verify_cmd }`. Computes direct and transitive dependencies with labeled citations (`EXTRACTED` vs `INFERRED`).
3. **Gate 2 — Shadow Checkpoint (`checkpoint create`):** Captures atomic repo snapshots. Destructive shell operations are guarded until a restore point exists.
4. **Gate 3 — Scoped Execution Guard:** Intercepts write operations. File modifications outside the contracted boundary or edits to unread files are instantly rejected.
5. **Gate 4 — Compacted Validation (`verify`):** Executes the test suite. Raw compiler output or 2,000-line stacktraces are reduced by ~95% to compact root-cause traces.
6. **Gate 5 — Cryptographic Ledger & Evidence (`gate`):** Compares the exact working tree SHA-256 against the verification record and outputs the tamper-evident **Veratum Evidence Block**.

```
🛑 POST-VERIFICATION EDIT PROTECTION:
If an agent modifies any contracted or uncontracted file after a passing verification,
the gate detects the SHA-256 tree hash mismatch and unconditionally blocks completion.
```

---

## 💻 CLI Command Reference

`V` = `python .veratum/engine/veratum_cli.py` (or `python3 .veratum/engine/veratum_cli.py` on Linux/macOS).

### 1. Contract & Scope Management

| Command | Description |
|---|---|
| `V contract --goal "..." --files "a.py,b.ts" --verify "<cmd>"` | Lock a task contract and compute blast radius |
| `V contract --mode plan\|implement\|review` | Switch contract operational modes |
| `V contract --profile auto\|eco\|balanced\|deep\|highstakes` | Set validation depth, checkpoint policy, and retry budgets |
| `V contract --extend "c.py,tests/test_c.py"` | Safely add new files to the active contract scope |
| `V contract --show` | Display current active contract details |
| `V contract --abandon` | Drop the current contract and reset scope locks |
| `V check-scope <path>` | Interrogate whether a file path is writable under active contract |

### 2. Impact & Architectural Knowledge Graph

| Command | Description |
|---|---|
| `V impact <file> [--depth 2] [--symbol <name>] [--json]` | Compute static AST blast radius, co-changes, and test couplings |
| `V graph build [--full] [--max-files N] [--max-file-kb K]` | Incrementally build/refresh AST knowledge graph across code, docs, and assets |
| `V graph query "<natural language query>" [--mode bfs\|dfs]` | Retrieve token-budgeted contextual subgraphs with exact `file:line` proof |
| `V graph path <source> <target>` | Identify shortest dependency or invocation path between two symbols/files |
| `V graph explain <node>` | Inspect direct neighbors, caller/callee trees, and cross-references |
| `V graph report` | Output god nodes, modularity communities, and surprising couplings |
| `V graph export [--format html\|svg\|obsidian\|cypher\|all]` | Generate zero-CDN HTML visualizer, SVG diagrams, and Obsidian vaults |
| `V graph watch` | Run background daemon that updates the AST graph as files change |
| `V graph status` | Check graph freshness, node/edge counts, and index health |

### 3. Checkpoints & Rollbacks

| Command | Description |
|---|---|
| `V checkpoint create [--label "<reason>"]` | Snapshot working directory state into an isolated shadow commit |
| `V checkpoint list` | List all historical snapshots and their creation timestamps |
| `V rollback [checkpoint-id]` | Safely revert the working tree to a previous checkpoint |

### 4. Verification, Gating & Memory

| Command | Description |
|---|---|
| `V verify ["<cmd>"] [--force]` | Execute test suite, compact error logs, and record passing SHA-256 hash |
| `V gate [--dry-run]` | Verify cryptographic ledger integrity and print Veratum Evidence Block |
| `V remember "<fact>" --kind decision\|pitfall\|architecture\|command` | Persist durable learnings into version-controlled `.veratum/brain.json` |
| `V brain show` | Print recorded project memory and persistent conventions |
| `V brain set-cmd <test\|build\|lint> "<cmd>"` | Pin canonical verification commands for the repository |
| `V status [--json]` | Full real-time summary: active contract, ledger state, and tree hashes |
| `V doctor` | Comprehensive health check of hooks, graph cache, and environment |

---

## 🔌 Model Context Protocol (MCP) Tools

When running with MCP-enabled IDEs (Cursor, Windsurf, Cline, Copilot, Antigravity), all capabilities are natively exposed as standardized tools:

- `veratum_get_brain`: Retrieve persistent architectural context and commands.
- `veratum_remember`: Record postmortem insights or architectural decisions.
- `veratum_lock_contract`: Atomically lock goal, scope, and verification command.
- `veratum_impact`: Retrieve static blast radius and export dependencies.
- `veratum_graph`: Query the AST knowledge graph, trace paths, and inspect nodes.
- `veratum_check_scope`: Pre-flight check prior to modifying files.
- `veratum_explain_shell`: Classify shell commands before running them.
- `veratum_checkpoint`: Create and restore shadow restore points.
- `veratum_verify`: Trigger compacted test execution and ledger binding.
- `veratum_check_gate`: Inspect gate status and obtain completion evidence.
- `veratum_audit`: Audit the cryptographic integrity of the verification chain.
- `veratum_status`: Query active contract status and working tree SHA.

---

## 🧠 Multi-Modal Knowledge Graph Specification

Veratum's built-in knowledge engine operates completely locally with **zero external telemetry**:

- **Polyglot Code Parsing:** Generates AST nodes and relationships across 24+ languages including Python, TypeScript, JavaScript, Rust, Go, C/C++, Java, Ruby, PHP, and SQL.
- **Documents & Specifications:** Indexes Markdown (`.md`), reStructuredText (`.rst`), HTML, LaTeX (`.tex`), OpenAPI/YAML, and JSON schemas. Automatically extracts section hierarchies and code backtick mentions.
- **Office Papers & Media Assets:** Indexes PDF, Word (`.docx`), Excel (`.xlsx`), images (`.png`, `.svg`, `.webp`), and media (`.mp4`, `.mp3`). Automatically links documents referencing or embedding media via `references` and `embeds` edges.
- **Community Detection:** Analyzes modularity using standard Louvain clustering, identifying architectural subsystems and god nodes.
- **Air-Gapped Visualizer Export:** Self-contained single-file HTML interactive visualizer with no remote script dependencies, alongside ready-to-use Obsidian vaults and Neo4j Cypher scripts.

