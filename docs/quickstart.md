# ⚡ Quickstart

Get up and running with **Veratum** in under 3 minutes.

Veratum acts as an autonomous reliability kernel and structural knowledge engine for AI coding agents across **Antigravity**, **Claude Code**, **Cursor**, **Windsurf**, **Cline**, and **GitHub Copilot**.

---

## 📋 Prerequisites

- **Python:** 3.8+ (`python --version`)
- **Node.js:** 16+ (for `npx` skill installation)
- **Git:** Initialized repository (`git status`)

---

## 1. Install Veratum in Your Project

Run the single-line installation command inside your project directory:

```bash
cd your-project
npx skills add yadavmandeep/veratum --skill veratum --agent <your-ide> --yes
```

> Replace `<your-ide>` with your environment:  
> `antigravity` · `claude-code` · `cursor` · `windsurf` · `cline` · `github-copilot` · `opencode`

---

## 2. Enable Real-Time Enforcement & MCP Hooks (Optional)

Inject strict pre-edit hooks, completion blockers, and the model context protocol (MCP) server:

```bash
npx github:yadavmandeep/Veratum init --ide <your-ide>
```

*For GitHub Copilot, use `--ide copilot`.*

---

## 3. Launch Your First Autonomous Verified Task

Instruct your agent in natural language. Because Veratum rules are automatically ingested into your IDE prompt context, simply describe what you want solved:

```text
Use Veratum to resolve the null pointer exception in auth/tokens.ts and verify it.
```

### What Happens Under the Hood:

```
[0. BRAIN SYNC]       Agent pulls repo architectural facts and pinned test commands from .veratum/brain.json
                      ↓
[1. CONTRACT]         Locks scope: { goal, files: ["auth/tokens.ts", "tests/tokens.test.ts"], verify_cmd }
                      Calculates Blast Radius & Transitive Graph Impact
                      ↓
[2. CHECKPOINT]       Creates a zero-overhead git shadow snapshot (cp-2026...) before edits occur
                      ↓
[3. SCOPE GUARD]      Guards write operations: blocks drift, halts edits to un-contracted files
                      ↓
[4. VERIFICATION]     Executes contracted verify command. Failures are token-compacted (~95% noise reduced)
                      ↓
[5. EVIDENCE GATE]    Validates tree SHA-256 against ledger; emits tamper-proof Veratum Evidence Block
```

---

## 4. Explore the Knowledge Graph

Build and query the local multi-modal AST and asset knowledge graph:

```bash
# Build/refresh the AST graph across code, docs, and assets
python .veratum/engine/veratum_cli.py graph build

# Query architectural relationships with exact file:line citations
python .veratum/engine/veratum_cli.py graph query "How is authentication handled?"

# Export interactive visualization (zero-CDN, air-gapped HTML + SVG + Obsidian vault)
python .veratum/engine/veratum_cli.py graph export --format all
```

Open `.veratum/graph/export/index.html` directly in your browser to interactively explore communities, call paths, and file dependencies.

---

## 5. Verify & Inspect Status

Inspect active contract state and repo health at any moment:

```bash
python .veratum/engine/veratum_cli.py status
python .veratum/engine/veratum_cli.py doctor
```

---

## 🔗 Next Steps

- **[Core Concepts](concepts.md)**: Deep dive into the 6 Gates, blast radius analysis, and SHA-256 tree hashing.
- **[Full Command Reference](usage.md)**: Explore the complete CLI, MCP server tools, and configuration flags.

