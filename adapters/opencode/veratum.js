/**
 * Veratum enforcement plugin for OpenCode.
 *
 * Maps OpenCode tool calls onto Veratum's hook protocol and lets the project's
 * engine (.veratum/engine/veratum_cli.py) decide. A denial throws, which blocks
 * the tool call before it runs. After edits/shell commands the ledger is
 * re-checked so stale verification evidence is invalidated immediately.
 */
import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { join } from "node:path";

const PYTHON = process.env.VERATUM_PYTHON || "python3";
const WRITE_TOOLS = new Set(["edit", "write", "patch", "multiedit"]);
const SHELL_TOOLS = new Set(["bash"]);
const SEARCH_TOOLS = new Set(["grep", "glob"]);

function runHook(directory, event, tool, args) {
  const engine = join(directory, ".veratum", "engine", "veratum_cli.py");
  if (!existsSync(engine)) return { allow: true };
  const toolName = WRITE_TOOLS.has(tool) ? "edit_file" : SHELL_TOOLS.has(tool) ? "run_command" : tool;
  const payload = {
    toolCall: {
      name: toolName,
      args: { TargetFile: args?.filePath || args?.path || "", CommandLine: args?.command || "" },
    },
    workspacePaths: [directory],
  };
  const res = spawnSync(PYTHON, [engine, "hook", event, "--host", "antigravity"], {
    cwd: directory,
    input: JSON.stringify(payload),
    encoding: "utf8",
    timeout: 60000,
  });
  if (res.error) return { allow: true, warning: `Veratum hook unavailable: ${res.error.message}` };
  try {
    const out = JSON.parse((res.stdout || "").trim().split("\n").pop() || "{}");
    return { allow: out.decision !== "deny", reason: out.reason };
  } catch {
    return { allow: true };
  }
}

export const VeratumPlugin = async ({ directory }) => ({
  "tool.execute.before": async (input, output) => {
    if (!WRITE_TOOLS.has(input.tool) && !SHELL_TOOLS.has(input.tool)) return;
    const decision = runHook(directory, "pre-tool", input.tool, output.args);
    if (!decision.allow) throw new Error(decision.reason || "Blocked by Veratum");
  },
  "tool.execute.after": async (input, output) => {
    if (SEARCH_TOOLS.has(input.tool)) {
      // Tell the model about the code graph (at most twice per task; the engine decides). Appended to the search result.
      const hint = runHook(directory, "pre-tool", input.tool, {});
      if (hint.allow && hint.reason && typeof output?.output === "string") output.output += `\n\n${hint.reason}`;
      return;
    }
    if (!WRITE_TOOLS.has(input.tool) && !SHELL_TOOLS.has(input.tool)) return;
    runHook(directory, "post-tool", input.tool, {});
  },
});

export default VeratumPlugin;
