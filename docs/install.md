# Installation guide

Install Veratum **only for the IDE you use**. Every section has the same steps: **install → (optional) enforce → verify → update → uninstall**.

Requirements: Node.js 16+ (for `npx`), Python 3.8+, git (recommended). On Windows, `python` is fine. The installer detects `python3`, `python` or `py -3` and writes the right command into your configs.

There are two levels:

- **Veratum Skill** (`npx skills add …`): the protocol plus the bundled engine. The agent follows the gates and runs the engine commands itself.
- **Veratum Enforced** (`npx veratum init --ide …`): adds IDE hooks and/or an MCP server, so scope violations, stale evidence and premature "done" are **blocked by the IDE**, not just discouraged.

You can start with the skill and add enforcement later. They work together.

---

## Google Antigravity

**Install**
```bash
npx skills add yadavmandeep/veratum --skill veratum --agent antigravity --yes
```
For the terminal product, use `--agent antigravity-cli`. The skill lands in `.agents/skills/veratum/`.

**Enforce (native hooks)**
```bash
npx veratum init --ide antigravity
agy plugin install "$PWD/.agents/plugins/veratum"
agy plugin list            # shows "veratum"
```
In the `agy` TUI, `/hooks` lists the active registrations: `PreToolUse` (scope + tamper guard), `PostToolUse` (evidence invalidation) and `Stop` (completion gate).

**Verify**
```bash
python3 .veratum/engine/veratum_cli.py doctor
```
If `.veratum/` doesn't exist yet, run `python3 .agents/skills/veratum/scripts/veratum_cli.py init` first, or let the agent do it on first use.

---

## Claude Code

**Install**
```bash
npx skills add yadavmandeep/veratum --skill veratum --agent claude-code --yes
```
The skill lands in `.claude/skills/veratum/`.

**Enforce (native hooks)**
```bash
npx veratum init --ide claude-code
```
This adds a managed Veratum block to `CLAUDE.md` (your own content is kept) and merges four hooks into `.claude/settings.json`:

| Hook | Effect |
|---|---|
| `SessionStart` | Injects project memory into every new session |
| `PreToolUse` (Edit/Write/MultiEdit/NotebookEdit/Bash) | Blocks out-of-scope edits, evidence tampering, destructive git without a checkpoint |
| `PostToolUse` | Marks verification `STALE` as soon as code changes. Reports shell-made scope drift |
| `Stop` | Claude can't end the turn until the completion gate passes (circuit breaker after 3 tries) |

Restart Claude Code or open `/hooks` once to load them.

**Verify**: `python3 .veratum/engine/veratum_cli.py doctor` → "Claude Code hooks wired".

---

## Cursor

**Install**
```bash
npx skills add yadavmandeep/veratum --skill veratum --agent cursor --yes
```

**Enforce (rule + MCP + hooks)**
```bash
npx veratum init --ide cursor
```
This writes `.cursor/rules/veratum.mdc` (always applied), `.cursor/mcp.json` (Veratum MCP server) and `.cursor/hooks.json` (`afterFileEdit`, `beforeShellExecution`, `stop`).
Then open **Cursor → Settings → MCP** and switch on **veratum**. You should see 9 tools (`veratum_lock_contract`, `veratum_verify`, `veratum_check_gate`, …).

**Verify**: ask the agent *"call veratum_get_brain"*, or run `doctor`.

---

## Windsurf

**Install**
```bash
npx skills add yadavmandeep/veratum --skill veratum --agent windsurf --yes
```
The skill lands in `.windsurf/skills/veratum/`.

**Enforce (rules + MCP)**
```bash
npx veratum init --ide windsurf
```
This writes the managed block in `.windsurfrules`. Windsurf keeps MCP servers in a **global** file, so Veratum prints a ready-to-paste snippet instead of editing it. Open **Settings → Cascade → MCP Servers → View raw config** and add:
```json
{ "mcpServers": { "veratum": { "command": "python3", "args": ["/abs/path/project/.veratum/engine/mcp_server.py", "--root", "/abs/path/project"] } } }
```

---

## Cline

**Install**
```bash
npx skills add yadavmandeep/veratum --skill veratum --agent cline --yes
```

**Enforce (rules + MCP)**
```bash
npx veratum init --ide cline
```
This writes `.clinerules`, or `.clinerules/veratum.md` if you use a rules folder. Add the printed MCP snippet under **Cline → MCP Servers → Configure MCP Servers**.

---

## GitHub Copilot (VS Code)

**Install**
```bash
npx skills add yadavmandeep/veratum --skill veratum --agent github-copilot --yes
```

**Enforce (instructions + MCP)**
```bash
npx veratum init --ide copilot
```
This writes the managed block in `.github/copilot-instructions.md` and the `veratum` server in `.vscode/mcp.json`. In Copilot Chat, switch to **Agent** mode, open the tools picker and make sure the Veratum tools are ticked.

---

## OpenCode

**Install**
```bash
npx skills add yadavmandeep/veratum --skill veratum --agent opencode --yes
```

**Enforce (plugin + MCP)**
```bash
npx veratum init --ide opencode
```
This writes the managed block in `AGENTS.md`, the `veratum` MCP entry in `opencode.json`, and `.opencode/plugin/veratum.js`, which blocks out-of-scope `edit`/`write`/`patch` calls before they run. Restart OpenCode.

---

## VS Code: Which option to use?

VS Code supports multiple AI extensions. Pick the command matching the assistant you use:

| Extension / Tool in VS Code | Command to Run | What it Configures |
|---|---|---|
| **GitHub Copilot** | `npx veratum init --ide copilot` | `.github/copilot-instructions.md` + `.vscode/mcp.json` |
| **Cline / Roo Code** | `npx veratum init --ide cline` | `.clinerules` |
| **Claude Code CLI** (Terminal) | `npx veratum init --ide claude-code` | `CLAUDE.md` + `.claude/settings.json` hooks |
| **Google Antigravity** | `npx veratum init --ide antigravity` | `.agents/skills/veratum` + `.agents/plugins/veratum` |

If you use multiple extensions in the same repository, pass multiple `--ide` flags or run `npx veratum init` for the interactive picker. All extensions automatically share the same `.veratum/` project memory and verification ledger.

---

## Privacy & Git: Keeping `.veratum/` 100% Local

If you are working on a company or client repository and want to ensure Veratum's memory and state files are **never pushed to remote git**, add `.veratum/` to your project's `.gitignore`:

```gitignore
# Keep Veratum runtime & memory 100% local
.veratum/
```

Veratum functions completely offline and locally without needing to track or push anything to remote git. For machine-wide automatic exclusion across all your repos, add `.veratum/` to your global gitignore:
```bash
git config --global core.excludesfile ~/.gitignore_global
echo ".veratum/" >> ~/.gitignore_global
```

---

## More than one IDE?

```bash
npx veratum init --ide cursor --ide claude-code
npx veratum init            # interactive picker (detects the IDEs you already use)
npx veratum list            # what's installed / detected
```

All IDEs share the same `.veratum/` memory and evidence, so you can switch between them mid-task.

## Update

```bash
npx skills update veratum --project --yes      # skill + bundled engine
npx veratum update                         # re-sync engine + adapters for the IDEs you installed
```
Updates never touch `.veratum/brain.json`.

## Uninstall

```bash
npx veratum uninstall --ide cursor         # remove one IDE adapter (memory kept)
npx veratum uninstall --all --purge        # remove everything, including .veratum/
npx skills remove veratum                       # remove the skill
```
Uninstall removes only Veratum's managed blocks and entries. Your own `CLAUDE.md`, rules, hooks and MCP servers are kept.
