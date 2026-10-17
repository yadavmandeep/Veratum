# Quickstart

Your first verified task with Veratum in about 3 minutes.

**You need:** a project folder, Node.js 16+ (for `npx`), Python 3.8+, and git (recommended, needed for checkpoints).

## 1. Install the skill for your IDE

```bash
cd your-project
npx skills add yadavmandeep/veratum --skill veratum --agent <your-ide> --yes
```

`<your-ide>` is one of `antigravity`, `claude-code`, `cursor`, `windsurf`, `cline`, `github-copilot`, `opencode`.

## 2. (Optional) Turn on enforcement

```bash
npx veratum init --ide <your-ide>
```

For Copilot use `--ide copilot`. Follow the one "Last step" line it prints (for example, enabling the MCP server in Cursor).

## 3. Give your agent a task

```text
Use Veratum to fix the off-by-one error in the invoice total and verify it.
```

You will see the agent:

1. read project memory (`brain show`)
2. lock a contract and print the **blast radius**:
   ```text
   🎯 Impact: src/billing/invoice.ts → 3 dependent(s) [MEDIUM]: src/api/checkout.ts, …
   ```
3. edit only the contracted files
4. run `verify`. If something fails, it gets a compacted trace instead of 2,000 log lines
5. run `gate` and finish with the **Veratum Evidence Block**

## 4. Check the result yourself

```bash
npx veratum status    # contract, ledger, is the evidence fresh?   (in chat: /veratum status)
npx veratum brain show
```

## 5. Commit the memory

`.veratum/brain.json` is meant to be committed, so everyone on the team (and every agent session) starts with what the last one learned. Machine-local state (`ledger.json`, `logs/`, …) is already gitignored.

Next: [Using Veratum](usage.md) · [Installation details per IDE](install.md)
