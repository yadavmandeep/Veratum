#!/usr/bin/env node
/**
 * Veratum installer & adapter compiler
 *
 *   npx github:yadavmandeep/Veratum init --ide <ide>     install Veratum for ONE IDE (repeat --ide or comma-separate for more)
 *   npx github:yadavmandeep/Veratum init                 interactive picker (terminal) or auto-detect (agents/CI)
 *   npx github:yadavmandeep/Veratum init --all           every supported IDE
 *   npx github:yadavmandeep/Veratum update [--ide ...]   re-sync engine + adapters (keeps brain.json)
 *   npx github:yadavmandeep/Veratum uninstall --ide <ide> [--purge]
 *   npx github:yadavmandeep/Veratum doctor | status | list
 *   npx github:yadavmandeep/Veratum build [--check]      regenerate skills/veratum + IDE rule files from core/SKILL.template.md
 *   npx github:yadavmandeep/Veratum <engine command>     any veratum_cli.py command, e.g. `verify "npm test"`
 *
 * IDEs: antigravity, claude-code, cursor, windsurf, cline, copilot, opencode
 */
"use strict";

const fs = require("fs");
const path = require("path");
const readline = require("readline");
const { spawnSync } = require("child_process");

const PKG_ROOT = path.resolve(__dirname, "..");
const PKG = JSON.parse(fs.readFileSync(path.join(PKG_ROOT, "package.json"), "utf8"));
const ALL_IDES = ["antigravity", "claude-code", "cursor", "windsurf", "cline", "copilot", "opencode"];
const IDE_LABELS = {
  antigravity: "Google Antigravity",
  "claude-code": "Claude Code",
  cursor: "Cursor",
  windsurf: "Windsurf",
  cline: "Cline",
  copilot: "GitHub Copilot (VS Code)",
  opencode: "OpenCode",
};
const ALIASES = {
  claude: "claude-code", claudecode: "claude-code", "github-copilot": "copilot", vscode: "copilot",
  "vs-code": "copilot", agy: "antigravity", "antigravity-cli": "antigravity", "open-code": "opencode",
};
const BLOCK_START = "<!-- veratum:start (managed by veratum — edits inside this block are overwritten) -->";
const BLOCK_END = "<!-- veratum:end -->";
const GITIGNORE_START = "# >>> veratum (managed)";
const GITIGNORE_END = "# <<< veratum";
const GITIGNORE_LINES = [
  ".veratum/logs/",
  ".veratum/ledger.json",
  ".veratum/contract.json",
  ".veratum/baseline.json",
  ".veratum/state.json",
  ".veratum/snapshots/",
  ".veratum/cache/",
  ".veratum/graph/",
];

const tty = process.stdout.isTTY;
const c = {
  green: (s) => (tty ? `\x1b[32m${s}\x1b[0m` : s),
  cyan: (s) => (tty ? `\x1b[36m${s}\x1b[0m` : s),
  yellow: (s) => (tty ? `\x1b[33m${s}\x1b[0m` : s),
  red: (s) => (tty ? `\x1b[31m${s}\x1b[0m` : s),
  bold: (s) => (tty ? `\x1b[1m${s}\x1b[0m` : s),
  dim: (s) => (tty ? `\x1b[2m${s}\x1b[0m` : s),
};

// ---------------------------------------------------------------------------
// Adapter compiler (core/SKILL.template.md -> skills/veratum bundle + every IDE's rule format)
// ---------------------------------------------------------------------------

function readSkill() {
  const raw = fs.readFileSync(path.join(PKG_ROOT, "core", "SKILL.template.md"), "utf8").replace(/\r\n/g, "\n");
  const m = raw.match(/^---\n([\s\S]*?)\n---\n+([\s\S]*)$/);
  if (!m) throw new Error("core/SKILL.template.md is missing YAML frontmatter");
  return { raw, frontmatter: m[1], body: m[2].trim() + "\n" };
}

function compiledAdapters() {
  const { raw, body } = readSkill();
  const generated = "<!-- Generated from core/SKILL.template.md by `veratum build`. Do not edit by hand. -->\n";
  const engine = (name) => fs.readFileSync(path.join(PKG_ROOT, "engine", name), "utf8").replace(/\r\n/g, "\n");
  return {
    // skills.sh bundle: `npx skills add <owner>/veratum --skill veratum --agent <ide>`
    "skills/veratum/SKILL.md": raw,
    "skills/veratum/scripts/veratum_cli.py": engine("veratum_cli.py"),
    "skills/veratum/scripts/veratum_graph.py": engine("veratum_graph.py"),
    "skills/veratum/scripts/veratum_export.py": engine("veratum_export.py"),
    "skills/veratum/scripts/mcp_server.py": engine("mcp_server.py"),
    "adapters/cursor/veratum.mdc":
      "---\n" +
      "description: Veratum 6-Gate Engineering Protocol - contract, blast radius, checkpoint, compacted verify, cryptographic completion gate.\n" +
      "globs:\n" +
      "alwaysApply: true\n" +
      "---\n\n" +
      generated +
      body,
    "adapters/windsurf/.windsurfrules": generated + body,
    "adapters/cline/.clinerules": generated + body,
    "adapters/copilot/copilot-instructions.md": generated + body,
  };
}

function build(check) {
  const stale = [];
  for (const [rel, content] of Object.entries(compiledAdapters())) {
    const file = path.join(PKG_ROOT, rel);
    const current = fs.existsSync(file) ? fs.readFileSync(file, "utf8").replace(/\r\n/g, "\n") : null;
    if (current === content) continue;
    if (check) {
      stale.push(rel);
    } else {
      fs.mkdirSync(path.dirname(file), { recursive: true });
      fs.writeFileSync(file, content, "utf8");
      console.log(`${c.green("✓")} built ${rel}`);
    }
  }
  if (check) {
    if (stale.length) {
      console.error(`✗ Out of date with core/ and engine/: ${stale.join(", ")}\n  Run: node bin/veratum.js build`);
      return 1;
    }
    console.log(`${c.green("✓")} skills/veratum and all adapters are in sync with core/SKILL.template.md and engine/`);
  }
  return 0;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function detectPython() {
  const candidates = process.platform === "win32"
    ? [["python", []], ["py", ["-3"]], ["python3", []]]
    : [["python3", []], ["python", []]];
  for (const [cmd, pre] of candidates) {
    const res = spawnSync(cmd, [...pre, "-c", "import sys;print(sys.version_info>=(3,8))"], { encoding: "utf8" });
    if (!res.error && res.status === 0 && (res.stdout || "").trim() === "True") {
      return { exe: cmd, pre, shell: [cmd, ...pre].join(" ") };
    }
  }
  return null;
}

function rel(target, file) {
  return path.relative(target, file).split(path.sep).join("/");
}

function writeFile(target, file, content, log) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  const existed = fs.existsSync(file);
  if (existed && fs.readFileSync(file, "utf8") === content) {
    log.push(`ok       ${rel(target, file)}`);
    return;
  }
  fs.writeFileSync(file, content, "utf8");
  log.push(`${existed ? "updated" : "created"}  ${rel(target, file)}`);
}

function removePath(target, p, log) {
  if (!fs.existsSync(p)) return;
  fs.rmSync(p, { recursive: true, force: true });
  log.push(`removed  ${rel(target, p)}`);
  // prune now-empty parent folders we may have created (never the project root)
  let dir = path.dirname(p);
  while (dir.startsWith(target) && dir !== target && fs.existsSync(dir) && fs.readdirSync(dir).length === 0) {
    fs.rmdirSync(dir);
    dir = path.dirname(dir);
  }
}

function upsertBlock(target, file, inner, log, opts = {}) {
  const start = opts.start || BLOCK_START;
  const end = opts.end || BLOCK_END;
  const block = `${start}\n${inner.trim()}\n${end}\n`;
  let content = fs.existsSync(file) ? fs.readFileSync(file, "utf8") : "";
  const s = content.indexOf(start);
  const e = content.indexOf(end);
  if (s !== -1 && e !== -1 && e > s) {
    content = content.slice(0, s) + block + content.slice(e + end.length).replace(/^\r?\n/, "");
  } else {
    content = content ? content.replace(/\s*$/, "\n\n") + block : block;
  }
  writeFile(target, file, content, log);
}

function removeBlock(target, file, log, opts = {}) {
  if (!fs.existsSync(file) || fs.statSync(file).isDirectory()) return;
  const start = opts.start || BLOCK_START;
  const end = opts.end || BLOCK_END;
  const content = fs.readFileSync(file, "utf8");
  const s = content.indexOf(start);
  const e = content.indexOf(end);
  if (s === -1 || e < s) return;
  const rest = (content.slice(0, s) + content.slice(e + end.length).replace(/^\r?\n/, "")).replace(/\s*$/, "\n");
  if (!rest.trim()) {
    removePath(target, file, log);
  } else {
    fs.writeFileSync(file, rest, "utf8");
    log.push(`cleaned  ${rel(target, file)}`);
  }
}

function readJson(file) {
  try {
    return JSON.parse(fs.readFileSync(file, "utf8"));
  } catch {
    return null;
  }
}

function mergeJson(target, file, mutate, log) {
  let data = {};
  if (fs.existsSync(file)) {
    data = readJson(file);
    if (data === null) {
      const backup = `${file}.veratum-backup-${Date.now()}`;
      fs.copyFileSync(file, backup);
      log.push(`backup   ${rel(target, backup)} (existing file was not valid JSON)`);
      data = {};
    }
  }
  mutate(data);
  writeFile(target, file, JSON.stringify(data, null, 2) + "\n", log);
}

function editJsonIfExists(target, file, mutate, log) {
  if (!fs.existsSync(file)) return;
  const data = readJson(file);
  if (data === null) return;
  mutate(data);
  const empty = Object.keys(data).filter((k) => k !== "$schema" && k !== "version").length === 0;
  if (empty) {
    removePath(target, file, log);
  } else {
    fs.writeFileSync(file, JSON.stringify(data, null, 2) + "\n", "utf8");
    log.push(`cleaned  ${rel(target, file)}`);
  }
}

function stripVeratumHooks(hooks) {
  for (const event of Object.keys(hooks || {})) {
    hooks[event] = (hooks[event] || []).filter((e) => !isVeratumEntry(e));
    if (!hooks[event].length) delete hooks[event];
  }
}

function readTemplate(relPath) {
  return fs.readFileSync(path.join(PKG_ROOT, relPath), "utf8");
}

function withPython(text, py) {
  return text.replace(/\bpython3 /g, `${py.shell} `);
}

function isVeratumEntry(entry) {
  const s = JSON.stringify(entry);
  return s.includes("veratum_cli.py") || s.includes("mcp_server.py");
}

function runEngine(target, py, args, opts = {}) {
  const engine = path.join(target, ".veratum", "engine", "veratum_cli.py");
  return spawnSync(py.exe, [...py.pre, engine, "--root", target, ...args], {
    cwd: target,
    stdio: opts.capture ? "pipe" : "inherit",
    encoding: "utf8",
    env: { ...process.env, PYTHONIOENCODING: "utf-8" },
  });
}

function mcpSnippet(target, py) {
  const server = path.join(target, ".veratum", "engine", "mcp_server.py");
  return JSON.stringify({ mcpServers: { veratum: { command: py.exe, args: [...py.pre, server, "--root", target] } } }, null, 2);
}

// ---------------------------------------------------------------------------
// Per-IDE install / uninstall
// ---------------------------------------------------------------------------

// `/veratum <question | status | gate | impact <file> | export ...>` shortcut, so nobody has to type the engine path.
// Cline is skipped: its workflows live in .clinerules/workflows, which collides with Veratum's .clinerules file.
// One command with one grammar, `/veratum <area> <action> [arguments]`: graph build|query|report|export|path|explain|docs,
// status, gate, doctor, impact <file>, memory, remember, config. Anything else is treated as a graph question.
const COMMAND_INFO = {
  veratum: { desc: "Veratum: graph build | graph query <question> | graph export | status | gate | impact <file> | doctor",
    hint: "graph build | graph query <question> | graph export | status | gate | impact <file>" },
};
const COMMANDS = {
  "claude-code": { file: ".claude/commands/{name}.md", args: "$ARGUMENTS", front: (i) => `description: ${i.desc}\nargument-hint: ${i.hint}` },
  cursor: { file: ".cursor/commands/{name}.md", args: "(the text typed after the command)", front: () => "" },
  opencode: { file: ".opencode/command/{name}.md", args: "$ARGUMENTS", front: (i) => `description: ${i.desc}` },
  copilot: { file: ".github/prompts/{name}.prompt.md", args: "(the text typed after the command)", front: (i) => `mode: agent\ndescription: ${i.desc}` },
  windsurf: { file: ".windsurf/workflows/{name}.md", args: "(the text typed after the command)", front: (i) => `description: ${i.desc}` },
  antigravity: { file: ".agents/workflows/{name}.md", args: "(the text typed after the command)", front: (i) => `description: ${i.desc}` },
};

function installCommand(ide, target, py, log) {
  const cmd = COMMANDS[ide];
  if (!cmd) return;
  for (const [name, info] of Object.entries(COMMAND_INFO)) {
    const body = withPython(readTemplate(`adapters/commands/${name}.md`), py).replace("{{ARGS}}", cmd.args);
    const front = cmd.front(info);
    writeFile(target, path.join(target, ...cmd.file.replace("{name}", name).split("/")), front ? `---\n${front}\n---\n\n${body}` : body, log);
  }
}

function removeCommand(ide, target, log) {
  if (!COMMANDS[ide]) return;
  for (const name of Object.keys(COMMAND_INFO)) removePath(target, path.join(target, ...COMMANDS[ide].file.replace("{name}", name).split("/")), log);
}

const IDES = {
  antigravity: {
    install(target, py, skill, log) {
      writeFile(target, path.join(target, ".agents", "skills", "veratum", "SKILL.md"), withPython(skill.raw, py), log);
      const pluginDir = path.join(target, ".agents", "plugins", "veratum");
      writeFile(target, path.join(pluginDir, "plugin.json"), readTemplate("adapters/antigravity/plugin.json"), log);
      writeFile(target, path.join(pluginDir, "hooks.json"), withPython(readTemplate("adapters/antigravity/hooks.json"), py), log);
      for (const name of ["_veratum_bridge.py", "pre_edit.py", "post_edit.py", "completion_gate.py"]) {
        writeFile(target, path.join(pluginDir, "hooks", name), readTemplate(`adapters/antigravity/hooks/${name}`), log);
      }
      return [`Turn on the native hooks (one time):\n      agy plugin install "${pluginDir}"\n      agy plugin list          # should list "veratum"`];
    },
    uninstall(target, log) {
      removePath(target, path.join(target, ".agents", "skills", "veratum"), log);
      removePath(target, path.join(target, ".agents", "plugins", "veratum"), log);
      return ["If you activated the plugin: agy plugin uninstall veratum"];
    },
  },

  "claude-code": {
    install(target, py, skill, log) {
      upsertBlock(target, path.join(target, "CLAUDE.md"), withPython(skill.body, py), log);
      const template = JSON.parse(withPython(readTemplate("adapters/claude-code/settings.template.json"), py));
      mergeJson(target, path.join(target, ".claude", "settings.json"), (data) => {
        data.hooks = data.hooks || {};
        for (const [event, entries] of Object.entries(template.hooks)) {
          const kept = (data.hooks[event] || []).filter((e) => !isVeratumEntry(e));
          data.hooks[event] = [...kept, ...entries];
        }
      }, log);
      return ["Restart Claude Code (or open /hooks once) so it loads the new hooks."];
    },
    uninstall(target, log) {
      removeBlock(target, path.join(target, "CLAUDE.md"), log);
      editJsonIfExists(target, path.join(target, ".claude", "settings.json"), (d) => {
        stripVeratumHooks(d.hooks);
        if (d.hooks && !Object.keys(d.hooks).length) delete d.hooks;
      }, log);
      return [];
    },
  },

  cursor: {
    install(target, py, skill, log) {
      writeFile(target, path.join(target, ".cursor", "rules", "veratum.mdc"), withPython(readTemplate("adapters/cursor/veratum.mdc"), py), log);
      const mcp = JSON.parse(readTemplate("adapters/cursor/mcp.template.json")).mcpServers.veratum;
      mergeJson(target, path.join(target, ".cursor", "mcp.json"), (data) => {
        data.mcpServers = data.mcpServers || {};
        data.mcpServers.veratum = { ...mcp, command: py.exe, args: [...py.pre, ...mcp.args] };
      }, log);
      const hooks = JSON.parse(withPython(readTemplate("adapters/cursor/hooks.template.json"), py));
      mergeJson(target, path.join(target, ".cursor", "hooks.json"), (data) => {
        data.version = data.version || 1;
        data.hooks = data.hooks || {};
        for (const [event, entries] of Object.entries(hooks.hooks)) {
          const kept = (data.hooks[event] || []).filter((e) => !isVeratumEntry(e));
          data.hooks[event] = [...kept, ...entries];
        }
      }, log);
      return ["Cursor → Settings → MCP: switch the \"veratum\" server on (Cursor asks once per project)."];
    },
    uninstall(target, log) {
      removePath(target, path.join(target, ".cursor", "rules", "veratum.mdc"), log);
      editJsonIfExists(target, path.join(target, ".cursor", "mcp.json"), (d) => {
        if (d.mcpServers) delete d.mcpServers.veratum;
        if (d.mcpServers && !Object.keys(d.mcpServers).length) delete d.mcpServers;
      }, log);
      editJsonIfExists(target, path.join(target, ".cursor", "hooks.json"), (d) => {
        stripVeratumHooks(d.hooks);
        if (d.hooks && !Object.keys(d.hooks).length) delete d.hooks;
      }, log);
      return [];
    },
  },

  windsurf: {
    install(target, py, skill, log) {
      upsertBlock(target, path.join(target, ".windsurfrules"), withPython(readTemplate("adapters/windsurf/.windsurfrules"), py), log);
      return [`Windsurf → Settings → Cascade → MCP Servers → "View raw config" (~/.codeium/windsurf/mcp_config.json), add:\n${indent(mcpSnippet(target, py), 6)}`];
    },
    uninstall(target, log) {
      removeBlock(target, path.join(target, ".windsurfrules"), log);
      return ["Remove the \"veratum\" entry from ~/.codeium/windsurf/mcp_config.json if you added it."];
    },
  },

  cline: {
    install(target, py, skill, log) {
      const clineRules = path.join(target, ".clinerules");
      const content = withPython(readTemplate("adapters/cline/.clinerules"), py);
      if (fs.existsSync(clineRules) && fs.statSync(clineRules).isDirectory()) {
        writeFile(target, path.join(clineRules, "veratum.md"), content, log);
      } else {
        upsertBlock(target, clineRules, content, log);
      }
      return [`Cline → MCP Servers → Installed → "Configure MCP Servers" (cline_mcp_settings.json), add:\n${indent(mcpSnippet(target, py), 6)}`];
    },
    uninstall(target, log) {
      const clineRules = path.join(target, ".clinerules");
      if (fs.existsSync(clineRules) && fs.statSync(clineRules).isDirectory()) removePath(target, path.join(clineRules, "veratum.md"), log);
      else removeBlock(target, clineRules, log);
      return ["Remove the \"veratum\" entry from cline_mcp_settings.json if you added it."];
    },
  },

  copilot: {
    install(target, py, skill, log) {
      upsertBlock(target, path.join(target, ".github", "copilot-instructions.md"),
        withPython(readTemplate("adapters/copilot/copilot-instructions.md"), py), log);
      const server = JSON.parse(readTemplate("adapters/copilot/vscode-mcp.template.json")).servers.veratum;
      mergeJson(target, path.join(target, ".vscode", "mcp.json"), (data) => {
        data.servers = data.servers || {};
        data.servers.veratum = { ...server, command: py.exe, args: [...py.pre, ...server.args] };
      }, log);
      return ["VS Code: open Copilot Chat in Agent mode → Tools icon → make sure the \"veratum\" tools are ticked."];
    },
    uninstall(target, log) {
      removeBlock(target, path.join(target, ".github", "copilot-instructions.md"), log);
      editJsonIfExists(target, path.join(target, ".vscode", "mcp.json"), (d) => {
        if (d.servers) delete d.servers.veratum;
        if (d.servers && !Object.keys(d.servers).length) delete d.servers;
      }, log);
      return [];
    },
  },

  opencode: {
    install(target, py, skill, log) {
      upsertBlock(target, path.join(target, "AGENTS.md"), withPython(skill.body, py), log);
      const tpl = JSON.parse(readTemplate("adapters/opencode/opencode.template.json"));
      mergeJson(target, path.join(target, "opencode.json"), (data) => {
        data.$schema = data.$schema || tpl.$schema;
        data.mcp = data.mcp || {};
        data.mcp.veratum = { ...tpl.mcp.veratum, command: [py.exe, ...py.pre, ".veratum/engine/mcp_server.py"] };
      }, log);
      const plugin = readTemplate("adapters/opencode/veratum.js").replace('|| "python3"', `|| ${JSON.stringify(py.shell)}`);
      writeFile(target, path.join(target, ".opencode", "plugin", "veratum.js"), plugin, log);
      return ["Restart OpenCode so it loads the plugin and the MCP server."];
    },
    uninstall(target, log) {
      removeBlock(target, path.join(target, "AGENTS.md"), log);
      editJsonIfExists(target, path.join(target, "opencode.json"), (d) => {
        if (d.mcp) delete d.mcp.veratum;
        if (d.mcp && !Object.keys(d.mcp).length) delete d.mcp;
      }, log);
      removePath(target, path.join(target, ".opencode", "plugin", "veratum.js"), log);
      return [];
    },
  },
};

function indent(text, n) {
  return text.split("\n").map((l) => " ".repeat(n) + l).join("\n");
}

function installEngine(target, log) {
  for (const name of ["veratum_cli.py", "veratum_graph.py", "veratum_export.py", "mcp_server.py"]) {
    writeFile(target, path.join(target, ".veratum", "engine", name), readTemplate(`engine/${name}`), log);
  }
  const refs = path.join(PKG_ROOT, "skills", "veratum", "references");
  for (const name of fs.readdirSync(refs).filter((n) => n.endsWith(".md"))) {
    writeFile(target, path.join(target, ".veratum", "references", name), fs.readFileSync(path.join(refs, name), "utf8"), log);
  }
}

function installGitignore(target, log) {
  const file = path.join(target, ".gitignore");
  upsertBlock(target, file, GITIGNORE_LINES.join("\n"), log, { start: GITIGNORE_START, end: GITIGNORE_END });
}

// ---------------------------------------------------------------------------
// IDE selection
// ---------------------------------------------------------------------------

function normalizeIde(name) {
  const key = String(name).trim().toLowerCase();
  return ALIASES[key] || key;
}

function parseIdeList(values) {
  const ides = [];
  for (const v of values) for (const part of String(v).split(",")) if (part.trim()) ides.push(normalizeIde(part));
  const unknown = ides.filter((i) => !ALL_IDES.includes(i));
  if (unknown.length) throw new Error(`Unknown IDE: ${unknown.join(", ")}. Choose from: ${ALL_IDES.join(", ")}`);
  return Array.from(new Set(ides));
}

/** Guess the IDE(s) in use from the environment and project markers. */
function detectIdes(target) {
  const found = new Set();
  const env = process.env;
  if (env.CLAUDECODE || env.CLAUDE_CODE_ENTRYPOINT) found.add("claude-code");
  if (env.CURSOR_TRACE_ID || env.CURSOR_AGENT) found.add("cursor");
  if (env.ANTIGRAVITY_AGENT || env.ANTIGRAVITY) found.add("antigravity");
  if (env.OPENCODE || env.OPENCODE_BIN_PATH) found.add("opencode");
  if (found.size) return [...found];
  const has = (p) => fs.existsSync(path.join(target, p));
  if (has(".claude") || has("CLAUDE.md")) found.add("claude-code");
  if (has(".cursor") || has(".cursorrules")) found.add("cursor");
  if (has(".windsurf") || has(".windsurfrules")) found.add("windsurf");
  if (has(".clinerules")) found.add("cline");
  if (has(".github/copilot-instructions.md")) found.add("copilot");
  if (has("opencode.json") || has(".opencode")) found.add("opencode");
  if (has(".agents") || has(".agent") || has("GEMINI.md")) found.add("antigravity");
  return ALL_IDES.filter((i) => found.has(i));
}

function askIdes(detected) {
  const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
  console.log(c.bold("Which IDE do you use with this project?\n"));
  ALL_IDES.forEach((ide, i) => {
    const mark = detected.includes(ide) ? c.green("  (detected)") : "";
    console.log(`  ${i + 1}) ${IDE_LABELS[ide]}${mark}`);
  });
  const def = detected.length ? detected.map((d) => ALL_IDES.indexOf(d) + 1).join(",") : "";
  return new Promise((resolve) => {
    rl.question(`\nNumber(s), e.g. 2 or 2,3${def ? ` [${def}]` : ""}: `, (answer) => {
      rl.close();
      const raw = (answer || def).trim();
      if (raw === "all" || raw === "*") return resolve(ALL_IDES);
      const picked = raw.split(/[ ,]+/).map((n) => ALL_IDES[parseInt(n, 10) - 1]).filter(Boolean);
      resolve(Array.from(new Set(picked)));
    });
  });
}

async function resolveIdes(opts, target) {
  if (opts.all) return ALL_IDES;
  if (opts.ide.length) return parseIdeList(opts.ide);
  const detected = detectIdes(target);
  if (process.stdin.isTTY && process.stdout.isTTY) return askIdes(detected);
  return detected;
}

// ---------------------------------------------------------------------------
// Commands
// ---------------------------------------------------------------------------

function parseArgs(argv) {
  const opts = { _: [], ide: [] };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === "--ide" || a === "--ides" || a === "--agent" || a === "-a") opts.ide.push(argv[++i] || "");
    else if (/^--(ide|ides|agent)=/.test(a)) opts.ide.push(a.split("=")[1]);
    else if (a === "--dir") opts.dir = argv[++i];
    else if (a.startsWith("--dir=")) opts.dir = a.slice(6);
    else if (a === "--all") opts.all = true;
    else if (a === "--check") opts.check = true;
    else if (a === "--purge") opts.purge = true;
    else opts._.push(a);
  }
  return opts;
}

function updateConfig(target, fn) {
  const file = path.join(target, ".veratum", "config.json");
  const config = readJson(file);
  if (!config) return;
  fn(config);
  fs.writeFileSync(file, JSON.stringify(config, null, 2) + "\n", "utf8");
}

async function init(opts) {
  const target = path.resolve(opts.dir || process.cwd());
  console.log(c.bold(`\n🧠 Veratum v${PKG.version} — https://github.com/yadavmandeep/Veratum\n`));
  const py = detectPython();
  if (!py) {
    console.error(c.red("✗ Python 3.8+ not found (tried python3, python, py -3). Install it from https://python.org and re-run."));
    return 1;
  }
  const ides = await resolveIdes(opts, target);
  if (!ides.length) {
    console.error("Tell Veratum which IDE you use, for example:\n");
    for (const ide of ALL_IDES) console.error(`  npx github:yadavmandeep/Veratum init --ide ${ide.padEnd(12)} # ${IDE_LABELS[ide]}`);
    console.error("\n  npx github:yadavmandeep/Veratum init --all              # every IDE");
    return 1;
  }
  console.log(c.dim(`   project: ${target}\n   python:  ${py.shell}\n   ide:     ${ides.map((i) => IDE_LABELS[i]).join(", ")}\n`));

  const log = [];
  const notes = [];
  installEngine(target, log);
  const initRes = runEngine(target, py, ["init"], { capture: true });
  if (initRes.status !== 0) {
    console.error(initRes.stdout || "", initRes.stderr || "");
    console.error(c.red("✗ Engine initialization failed."));
    return 1;
  }
  log.push("ready    .veratum/brain.json (project memory)");

  const skill = readSkill();
  for (const ide of ides) {
    for (const n of IDES[ide].install(target, py, skill, log)) notes.push(`${IDE_LABELS[ide]}: ${n}`);
    installCommand(ide, target, py, log);
  }
  installGitignore(target, log);

  for (const line of log.filter((l) => !l.startsWith("ok "))) console.log(`  ${c.green("✓")} ${line}`);
  console.log("");

  // Automatically build the knowledge graph with live progress
  console.log(c.bold("  🕸️  Mapping codebase knowledge graph..."));
  const graphRes = runEngine(target, py, ["graph", "build"], { capture: false });
  if (graphRes.status === 0) {
    console.log(`  ${c.green("✓")} ready    .veratum/graph/ (code & asset knowledge graph mapped)`);
  } else {
    console.log(c.dim("  (Knowledge graph can be built later via: veratum graph build)"));
  }
  updateConfig(target, (cfg) => {
    cfg.installed_adapters = Array.from(new Set([...(cfg.installed_adapters || []), ...ides]));
    cfg.python = py.shell;
    cfg.installed_version = PKG.version;
  });
  if (notes.length) {
    console.log(c.bold("  Last step:"));
    for (const n of notes) console.log(`  ${c.yellow("→")} ${n}`);
    console.log("");
  }
  console.log(c.bold(`  ✨ Veratum is ready for ${ides.map((i) => IDE_LABELS[i]).join(", ")}.`));
  console.log("");
  console.log(c.bold("  Use it (type these in your agent's chat):"));
  const withCommands = ides.some((i) => COMMANDS[i]);
  if (withCommands) {
    console.log("    /veratum graph build                       map this project's code (it also builds itself at session start)");
    console.log("    /veratum graph query where is login?       ask the code graph instead of grepping");
    console.log("    /veratum graph export                      picture, Obsidian vault, Neo4j script");
    console.log("    /veratum impact <file>                     what breaks if you change this file");
    console.log("    /veratum status | gate | doctor            current task, completion check, health");
  }
  if (ides.some((i) => !COMMANDS[i])) {
    console.log(`    ${withCommands ? "(Cline) " : ""}no slash commands here: just write "Use Veratum: where is login handled?"`);
  }
  console.log(`    Any task:  "Use Veratum to fix <bug> and verify it."`);
  console.log("");
  return 0;
}

function uninstall(opts) {
  const target = path.resolve(opts.dir || process.cwd());
  const cfg = readJson(path.join(target, ".veratum", "config.json")) || {};
  const ides = opts.all ? ALL_IDES : opts.ide.length ? parseIdeList(opts.ide) : cfg.installed_adapters || [];
  if (!ides.length && !opts.purge) {
    console.error("Nothing to uninstall. Use --ide <ide>, --all, or --purge.");
    return 1;
  }
  const log = [];
  const notes = [];
  for (const ide of ides) {
    notes.push(...IDES[ide].uninstall(target, log));
    removeCommand(ide, target, log);
  }
  updateConfig(target, (c2) => {
    c2.installed_adapters = (c2.installed_adapters || []).filter((i) => !ides.includes(i));
  });
  if (opts.purge) {
    removePath(target, path.join(target, ".veratum"), log);
    removeBlock(target, path.join(target, ".gitignore"), log, { start: GITIGNORE_START, end: GITIGNORE_END });
  }
  for (const line of log) console.log(`  ${c.green("✓")} ${line}`);
  for (const n of notes) console.log(`  ${c.yellow("→")} ${n}`);
  console.log(opts.purge ? "\n  Veratum removed completely." : "\n  Adapters removed. Project memory kept in .veratum/ (use --purge to delete it).");
  return 0;
}

function list() {
  const target = process.cwd();
  const cfg = readJson(path.join(target, ".veratum", "config.json")) || {};
  const installed = cfg.installed_adapters || [];
  const detected = detectIdes(target);
  console.log(c.bold("Supported IDEs:\n"));
  for (const ide of ALL_IDES) {
    const state = installed.includes(ide) ? c.green("installed") : detected.includes(ide) ? c.yellow("detected") : c.dim("—");
    console.log(`  ${ide.padEnd(12)} ${IDE_LABELS[ide].padEnd(26)} ${state}`);
  }
  return 0;
}

function delegate(args) {
  const py = detectPython();
  if (!py) {
    console.error("✗ Python 3.8+ not found on PATH.");
    return 1;
  }
  let dir = path.resolve(process.cwd());
  while (!fs.existsSync(path.join(dir, ".veratum", "engine", "veratum_cli.py"))) {
    const parent = path.dirname(dir);
    if (parent === dir) {
      console.error("✗ Veratum is not installed here. Run: npx github:yadavmandeep/Veratum init --ide <your-ide>");
      return 1;
    }
    dir = parent;
  }
  const res = runEngine(dir, py, args);
  return res.status === null ? 1 : res.status;
}

function help() {
  console.log(`Veratum v${PKG.version} — https://github.com/yadavmandeep/Veratum

Install (pick your IDE):
  npx github:yadavmandeep/Veratum init --ide antigravity
  npx github:yadavmandeep/Veratum init --ide claude-code
  npx github:yadavmandeep/Veratum init --ide cursor
  npx github:yadavmandeep/Veratum init --ide windsurf
  npx github:yadavmandeep/Veratum init --ide cline
  npx github:yadavmandeep/Veratum init --ide copilot
  npx github:yadavmandeep/Veratum init --ide opencode
  npx github:yadavmandeep/Veratum init                     interactive picker / auto-detect
  npx github:yadavmandeep/Veratum init --all               every IDE

Manage:
  npx github:yadavmandeep/Veratum list                     supported / installed IDEs
  npx github:yadavmandeep/Veratum update [--ide <ide>]     refresh engine + adapters (keeps memory)
  npx github:yadavmandeep/Veratum uninstall --ide <ide>    remove one IDE adapter (add --purge to delete .veratum/)
  npx github:yadavmandeep/Veratum doctor                   health check
  npx github:yadavmandeep/Veratum status                   current task, evidence freshness

Engine (same as python3 .veratum/engine/veratum_cli.py ...):
  brain | remember | contract | impact | checkpoint | rollback | verify | gate
`);
  return 0;
}

async function main(argv) {
  const opts = parseArgs(argv);
  const cmd = opts._[0];
  try {
    switch (cmd) {
      case "init":
      case "install":
        return await init(opts);
      case "update":
      case "sync": {
        if (!opts.ide.length && !opts.all) {
          const cfg = readJson(path.join(path.resolve(opts.dir || process.cwd()), ".veratum", "config.json")) || {};
          opts.ide = cfg.installed_adapters || [];
        }
        return await init(opts);
      }
      case "uninstall":
      case "remove":
        return uninstall(opts);
      case "list":
        return list();
      case "build":
        return build(Boolean(opts.check));
      case "help":
      case "--help":
      case "-h":
      case undefined:
        return help();
      case "--version":
      case "-v":
      case "version":
        console.log(PKG.version);
        return 0;
      default:
        return delegate(argv);
    }
  } catch (err) {
    console.error(c.red(`✗ ${err.message}`));
    return 1;
  }
}

if (require.main === module) {
  main(process.argv.slice(2)).then((code) => {
    process.exitCode = code;
  });
}

module.exports = { main, build, compiledAdapters, detectPython, detectIdes, parseIdeList, ALL_IDES };
