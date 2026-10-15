"""Agent drivers. A driver runs one agent on one prepared workdir and reports back.

Built in:
  claude-code  Claude Code headless (`claude -p`, stream-json transcript)
  manual       you drive any agent/IDE by hand; the harness prepares and scores
  oracle       overlays the task's reference solution (validates the tasks)
  noop         changes nothing and claims success (sanity-checks the metrics)

Plug in another agent with `--driver package.module:ClassName`. The class needs
`name` and `run(ctx) -> dict`; see Driver.run for the context and result keys.
"""
import importlib
import json
import os
import shlex
import shutil
import subprocess
import sys
import time


class Driver:
    name = "?"

    def __init__(self, options=None):
        self.options = options or {}

    def version(self):
        return None

    def preflight(self):
        """Return None if the agent is usable, else an error string (checked before any run)."""
        return None

    def run(self, ctx):
        """Run the agent.

        ctx keys: workdir, prompt, out_dir (outside the workdir, for logs),
        timeout_sec, task (spec dict), setup (name).

        Return a dict with any of: final_text (str), exit_code (int),
        timed_out (bool), duration_ms, num_turns, cost_usd, usage (dict of
        token counts), model, tool_calls (list of {name, summary}),
        permission_denials (int), interventions (int), claimed_done (bool,
        only if the driver knows it), error (str).
        """
        raise NotImplementedError


# ---------------------------------------------------------------------------

# Variables the host Claude Code / desktop app sets for its own session. A
# nested `claude -p` must not inherit them or it may think it is a child of
# this session (or run in a restricted mode). Auth variables are kept.
_STRIP_PREFIXES = ("CLAUDE_CODE_", "CLAUDE_AGENT_SDK_")
_STRIP_EXACT = {"CLAUDECODE", "CLAUDE_PID", "CLAUDE_EFFORT", "CLAUDE_PREVIEW_CLASSIFIER_FLOOR"}
_KEEP = {"CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_CODE_OAUTH_SCOPES", "CLAUDE_CODE_USE_BEDROCK",
         "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_SDK_HAS_HOST_AUTH_REFRESH",
         "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC", "CLAUDE_CODE_ACCOUNT_UUID",
         "CLAUDE_CODE_ORGANIZATION_UUID", "CLAUDE_CODE_USER_EMAIL"}


# Inside a Claude host session these are injected by the host and only work
# through its proxy, so a nested CLI must fall back to the operator's own login.
_HOST_AUTH = ("ANTHROPIC_API_KEY", "ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN")


def clean_env():
    nested = "CLAUDECODE" in os.environ
    env = {}
    for k, v in os.environ.items():
        if k in _KEEP:
            env[k] = v
        elif k in _STRIP_EXACT or k.startswith(_STRIP_PREFIXES):
            continue
        elif nested and k in _HOST_AUTH:
            continue
        else:
            env[k] = v
    # Explicit opt-in key for the benchmark, e.g. a separate billing key.
    if os.environ.get("BENCH_ANTHROPIC_API_KEY"):
        env["ANTHROPIC_API_KEY"] = os.environ["BENCH_ANTHROPIC_API_KEY"]
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def kill_tree(proc):
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(proc.pid)], capture_output=True)
    else:
        proc.kill()


def _summarise_tool(name, inp):
    inp = inp or {}
    for key in ("command", "file_path", "path", "skill", "pattern", "description"):
        if key in inp and isinstance(inp[key], str):
            return inp[key][:300]
    return json.dumps(inp)[:200]


class ClaudeCodeDriver(Driver):
    """`claude -p` with permissions bypassed inside the throwaway workdir.

    Options: model, max_budget_usd, claude_cmd, extra_args (list),
    user_settings (bool, default False: load only project/local settings so the
    operator's personal hooks, plugins and skills do not leak into the benchmark),
    isolate_mcp (bool, default True: no MCP servers unless a setup brings its own
    via .mcp.json and isolate_mcp is turned off).
    """

    name = "claude-code"

    def _exe(self):
        """argv prefix for the CLI; `claude_cmd` (e.g. a fake for self-tests) overrides PATH lookup."""
        if self.options.get("claude_cmd"):
            tokens = [t.strip('"') for t in shlex.split(self.options["claude_cmd"], posix=os.name != "nt")]
            # The agent runs with cwd=workdir, so pin relative script paths now.
            return [os.path.abspath(t) if os.path.exists(t) else t for t in tokens]
        exe = shutil.which("claude")
        if not exe:
            raise RuntimeError("claude CLI not found on PATH")
        return [exe]

    def version(self):
        try:
            return subprocess.run(self._exe() + ["--version"], capture_output=True, text=True,
                                  env=clean_env(), timeout=60).stdout.strip()
        except Exception as exc:  # noqa: BLE001
            return "unknown (%s)" % exc

    def preflight(self):
        argv = self._exe() + ["-p", "--output-format", "json", "--no-session-persistence"]
        if self.options.get("model"):
            argv += ["--model", self.options["model"]]
        try:
            res = subprocess.run(argv, input="Reply with the single word: ok", capture_output=True, text=True,
                                 encoding="utf-8", errors="replace", env=clean_env(), timeout=180)
            data = json.loads(res.stdout.strip().splitlines()[-1])
        except Exception as exc:  # noqa: BLE001
            return "could not run claude: %s" % exc
        if data.get("is_error"):
            return "claude -p returned an error: %s" % data.get("result")
        return None

    def command(self):
        argv = self._exe() + ["-p", "--output-format", "stream-json", "--verbose",
                "--dangerously-skip-permissions", "--no-session-persistence"]
        if not self.options.get("user_settings"):
            argv += ["--setting-sources", "project,local"]
        if self.options.get("isolate_mcp", True):
            argv += ["--strict-mcp-config"]
        if self.options.get("model"):
            argv += ["--model", self.options["model"]]
        if self.options.get("max_budget_usd"):
            argv += ["--max-budget-usd", str(self.options["max_budget_usd"])]
        argv += list(self.options.get("extra_args") or [])
        return argv

    def run(self, ctx):
        transcript = os.path.join(ctx["out_dir"], "transcript.jsonl")
        stderr_path = os.path.join(ctx["out_dir"], "agent_stderr.log")
        argv = self.command()
        with open(os.path.join(ctx["out_dir"], "agent_cmd.json"), "w", encoding="utf-8") as fh:
            json.dump(argv, fh, indent=1)
        started = time.time()
        timed_out = False
        with open(transcript, "wb") as out, open(stderr_path, "wb") as err:
            proc = subprocess.Popen(argv, cwd=ctx["workdir"], stdin=subprocess.PIPE, stdout=out,
                                    stderr=err, env=clean_env())
            try:
                proc.stdin.write(ctx["prompt"].encode("utf-8"))
                proc.stdin.close()
                proc.wait(timeout=ctx["timeout_sec"])
            except subprocess.TimeoutExpired:
                timed_out = True
                kill_tree(proc)
                proc.wait()
        wall_ms = int((time.time() - started) * 1000)
        result = parse_stream_json(transcript)
        result.update({"exit_code": proc.returncode, "timed_out": timed_out, "wall_ms": wall_ms})
        if result.get("final_text") is None and not timed_out:
            with open(stderr_path, encoding="utf-8", errors="replace") as fh:
                result["error"] = fh.read()[-2000:] or "no result event in transcript"
        return result


def parse_stream_json(path):
    out = {"final_text": None, "tool_calls": [], "model": None}
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                ev = json.loads(line)
            except ValueError:
                continue
            kind = ev.get("type")
            if kind == "system" and ev.get("subtype") == "init":
                out["model"] = ev.get("model")
                out["skills_available"] = ev.get("skills")
            elif kind == "assistant":
                for item in (ev.get("message") or {}).get("content") or []:
                    if item.get("type") == "tool_use":
                        out["tool_calls"].append({"name": item.get("name"),
                                                  "summary": _summarise_tool(item.get("name"), item.get("input"))})
            elif kind == "result":
                out["final_text"] = ev.get("result")
                out["is_error"] = ev.get("is_error")
                out["api_error_status"] = ev.get("api_error_status")
                out["terminal_reason"] = ev.get("terminal_reason")
                out["result_subtype"] = ev.get("subtype")
                out["duration_ms"] = ev.get("duration_ms")
                out["num_turns"] = ev.get("num_turns")
                out["cost_usd"] = ev.get("total_cost_usd")
                out["usage"] = ev.get("usage")
                out["permission_denials"] = len(ev.get("permission_denials") or [])
    return out


# ---------------------------------------------------------------------------


class ManualDriver(Driver):
    """For IDE agents without a headless mode (Cursor, Windsurf, Antigravity...)."""

    name = "manual"

    def run(self, ctx):
        prompt_file = os.path.join(ctx["out_dir"], "PROMPT.txt")
        with open(prompt_file, "w", encoding="utf-8") as fh:
            fh.write(ctx["prompt"])
        print("\n" + "=" * 72)
        print("Task %s / setup %s" % (ctx["task"]["id"], ctx["setup"]))
        print("Open this folder in your agent/IDE:\n  %s" % ctx["workdir"])
        print("Paste the prompt from:\n  %s" % prompt_file)
        print("Record any time you have to step in (answer a question, approve, nudge).")
        started = time.time()
        input("Press Enter when the agent has finished... ")
        wall_ms = int((time.time() - started) * 1000)
        claimed = input("Did the agent claim the task was done? [y/n] ").strip().lower().startswith("y")
        interventions = int(input("How many human interventions? [0] ").strip() or 0)
        print("Paste the agent's final message, then a line with only END:")
        lines = []
        while True:
            line = input()
            if line.strip() == "END":
                break
            lines.append(line)
        return {"final_text": "\n".join(lines), "claimed_done": claimed, "interventions": interventions,
                "wall_ms": wall_ms, "exit_code": 0}


class OracleDriver(Driver):
    name = "oracle"

    def run(self, ctx):
        sol = ctx["task"]["solution_dir"]
        if not os.path.isdir(sol):
            return {"final_text": "", "error": "task has no solution/ directory", "claimed_done": False}
        shutil.copytree(sol, ctx["workdir"], dirs_exist_ok=True)
        return {"final_text": "Done. Applied the reference solution.", "claimed_done": True, "exit_code": 0}


class NoopDriver(Driver):
    name = "noop"

    def run(self, ctx):
        return {"final_text": "Done - fixed and all tests pass.", "exit_code": 0}


DRIVERS = {d.name: d for d in (ClaudeCodeDriver, ManualDriver, OracleDriver, NoopDriver)}


def load_driver(spec, options):
    if spec in DRIVERS:
        return DRIVERS[spec](options)
    if ":" in spec:
        module, cls = spec.split(":", 1)
        sys.path.insert(0, os.getcwd())
        return getattr(importlib.import_module(module), cls)(options)
    raise ValueError("unknown driver %r (built in: %s, or module:Class)" % (spec, ", ".join(DRIVERS)))
