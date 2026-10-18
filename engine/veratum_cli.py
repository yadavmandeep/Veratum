#!/usr/bin/env python3
"""
Veratum Engine CLI
=====================================

Zero-dependency (Python 3.8+ standard library only) runtime for the Veratum
6-Gate Engineering Protocol:

    Brain Sync -> Contract & Blast-Radius -> Shadow Checkpoint ->
    Scoped Execution -> Compacted Validation -> Cryptographic Gate

Subcommands
-----------
    init                      Create .veratum/ and auto-detect the project stack
    brain show|remember|set-cmd|forget|scan|context
    remember "<insight>"      Shortcut for `brain remember`
    contract --goal --files --verify   Lock task scope (+ blast radius, ledger reset)
    check-scope <path>        Exit 0 if <path> may be edited under the contract
    impact <path>             Static blast-radius / dependent analysis
    checkpoint create|rollback|list   Shadow git snapshots (incl. untracked files)
    rollback [id]             Shortcut for `checkpoint rollback`
    verify "<cmd>"            Run validation, compact the log, bind tree hash
    gate                      Hard completion gate (exit 1 when blocked)
    status                    Contract / ledger / freshness overview
    doctor                    Diagnose installation health
    hook <event>              Host hook entry point (Claude Code, Antigravity, Cursor)
"""
from __future__ import annotations

import argparse
import datetime as _dt
import fnmatch
import hashlib
import json
import os
import platform
import posixpath
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from pathlib import Path

VERSION = "1.3.0"
BRAND = "Veratum"
HOMEPAGE = "https://github.com/yadavmandeep/Veratum"
VERATUM_DIRNAME = ".veratum"
VERATUM_DIRNAME = VERATUM_DIRNAME
# Runtime files installed together into .veratum/engine/ (graph and export load on demand from veratum_cli.py)
ENGINE_FILES = ("veratum_cli.py", "veratum_graph.py", "veratum_export.py", "mcp_server.py")

IGNORE_DIRS = {
    ".git", ".hg", ".svn", VERATUM_DIRNAME, "node_modules", "bower_components",
    ".next", ".nuxt", ".svelte-kit", ".turbo", ".cache", ".parcel-cache",
    "dist", "build", "out", "target", "coverage", ".nyc_output",
    "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", ".tox",
    "venv", ".venv", "env", ".env", ".idea", ".gradle", "vendor", "Pods",
}

JS_EXTS = (".js", ".mjs", ".cjs", ".jsx", ".vue", ".svelte")
TS_EXTS = (".ts", ".mts", ".cts")
TSX_EXTS = (".tsx",)
PLSQL_EXTS = (".sql", ".spc", ".bdy", ".trg", ".pdc", ".prc", ".fnc", ".pks", ".pkb")
C_EXTS = (".c", ".h")
CPP_EXTS = (".cc", ".cpp", ".cxx", ".hpp", ".hh", ".hxx")
CS_EXTS = (".cs",)
RUBY_EXTS = (".rb", ".rake")
PHP_EXTS = (".php", ".phtml")
BASH_EXTS = (".sh", ".bash", ".zsh")
LUA_EXTS = (".lua",)
SCALA_EXTS = (".scala", ".sc")
KOTLIN_EXTS = (".kt", ".kts")
SWIFT_EXTS = (".swift",)
ELIXIR_EXTS = (".ex", ".exs")
GROOVY_EXTS = (".groovy", ".gvy", ".gradle")
JULIA_EXTS = (".jl",)
POWERSHELL_EXTS = (".ps1", ".psm1", ".psd1")
OBJC_EXTS = (".m", ".mm")
ZIG_EXTS = (".zig",)
JSON_EXTS = (".json",)

LANG_BY_EXT = {
    **{ext: "js" for ext in JS_EXTS},
    **{ext: "ts" for ext in TS_EXTS},
    **{ext: "tsx" for ext in TSX_EXTS},
    **{ext: "sql" for ext in PLSQL_EXTS},
    **{ext: "c" for ext in C_EXTS},
    **{ext: "cpp" for ext in CPP_EXTS},
    **{ext: "c_sharp" for ext in CS_EXTS},
    **{ext: "ruby" for ext in RUBY_EXTS},
    **{ext: "php" for ext in PHP_EXTS},
    **{ext: "bash" for ext in BASH_EXTS},
    **{ext: "lua" for ext in LUA_EXTS},
    **{ext: "scala" for ext in SCALA_EXTS},
    **{ext: "kotlin" for ext in KOTLIN_EXTS},
    **{ext: "swift" for ext in SWIFT_EXTS},
    **{ext: "elixir" for ext in ELIXIR_EXTS},
    **{ext: "groovy" for ext in GROOVY_EXTS},
    **{ext: "julia" for ext in JULIA_EXTS},
    **{ext: "powershell" for ext in POWERSHELL_EXTS},
    **{ext: "objc" for ext in OBJC_EXTS},
    **{ext: "zig" for ext in ZIG_EXTS},
    **{ext: "json" for ext in JSON_EXTS},
    ".py": "py", ".pyi": "py",
    ".go": "go",
    ".rs": "rs",
    ".java": "java",
    ".jsp": "js",
    ".tag": "js",
}

DEFAULT_CONFIG = {
    "schema": "veratum.config/v1",
    "enforcement": "strict",          # strict | advisory | off
    "trivial_bypass": False,          # allow edits without a contract (scope check always passes)
    "read_before_write": True,        # hooks block edits to files not read (or changed since read) in this task
    "max_retries": 2,                 # failed verifications before rollback/escalation advice
    "compact_max_lines": 40,
    "verify_timeout_sec": 1800,
    "stop_gate_max_blocks": 3,        # consecutive Stop-hook blocks before failing open (0 = never)
    "fingerprint_exclude": [],        # extra fnmatch patterns ignored by the tree hash
    "protected_paths": [
        ".veratum/ledger.json", ".veratum/contract.json", ".veratum/baseline.json",
        ".veratum/state.json", ".veratum/snapshots/*",
    ],
    "installed_adapters": [],
    "python": "",
    "graph_auto": "auto",             # auto: build the graph at session start (small repos) and keep it fresh | refresh | off
}

STATUS_PASSED = "PASSED"
STATUS_FAILED = "FAILED"
STATUS_STALE = "STALE"
STATUS_IN_PROGRESS = "IN_PROGRESS"
STATUS_UNVERIFIED = "UNVERIFIED"


class VeratumError(Exception):
    """User-facing error with an exit code."""

    def __init__(self, message: str, code: int = 1):
        super().__init__(message)
        self.code = code


# ---------------------------------------------------------------------------
# Small utilities
# ---------------------------------------------------------------------------

def _utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except Exception:
            pass


def now_iso() -> str:
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def read_json(path: Path, default=None):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp-" + uuid.uuid4().hex[:6])
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    for attempt in range(5):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            time.sleep(0.05 * (attempt + 1))
    os.replace(tmp, path)


def to_posix(p: str) -> str:
    return p.replace("\\", "/")


def norm_case(p: str) -> str:
    return p.lower() if os.name == "nt" else p


def split_csv(values) -> list:
    out = []
    if not values:
        return out
    if isinstance(values, str):
        values = [values]
    for value in values:
        for part in str(value).split(","):
            part = part.strip()
            if part:
                out.append(part)
    return out


def short_hash(h: str, n: int = 16) -> str:
    return (h or "")[:n]


def _graph_module():
    """Load the graph engine (veratum_graph.py, installed next to this file) and bind it to this module's helpers."""
    here = os.path.dirname(os.path.abspath(__file__))
    if here not in sys.path:
        sys.path.insert(0, here)
    try:
        import veratum_graph
    except ImportError:
        raise VeratumError("veratum_graph.py is missing next to veratum_cli.py. Run `npx github:yadavmandeep/Veratum update` (or re-add the skill).")
    veratum_graph.bind(sys.modules[__name__])
    return veratum_graph


# ---------------------------------------------------------------------------
# Workspace
# ---------------------------------------------------------------------------

class Workspace:
    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self.dir = self.root / VERATUM_DIRNAME
        self.brain_path = self.dir / "brain.json"
        self.contract_path = self.dir / "contract.json"
        self.ledger_path = self.dir / "ledger.json"
        self.baseline_path = self.dir / "baseline.json"
        self.config_path = self.dir / "config.json"
        self.state_path = self.dir / "state.json"
        self.logs_dir = self.dir / "logs"
        self.last_log = self.logs_dir / "last_run.log"
        self.history_log = self.logs_dir / "history.jsonl"
        self.snapshots_dir = self.dir / "snapshots"
        self.verified_snapshot = self.snapshots_dir / "verified.json"
        self.engine_dir = self.dir / "engine"

    # -- path helpers ------------------------------------------------------
    def rel(self, path) -> str | None:
        """Return the workspace-relative POSIX path, or None if outside the workspace."""
        p = Path(path)
        if not p.is_absolute():
            p = self.root / p
        try:
            resolved = Path(os.path.normpath(str(p)))
            rel = os.path.relpath(str(resolved), str(self.root))
        except ValueError:  # different drive on Windows
            return None
        rel = to_posix(rel)
        if rel == "." or rel == "":
            return ""
        if rel.startswith("../") or rel == "..":
            return None
        return rel

    # -- persisted documents ---------------------------------------------
    def config(self) -> dict:
        cfg = dict(DEFAULT_CONFIG)
        cfg.update(read_json(self.config_path, {}) or {})
        return cfg

    def save_config(self, cfg: dict) -> None:
        write_json(self.config_path, cfg)

    def brain(self) -> dict:
        return read_json(self.brain_path, None) or new_brain(self.root)

    def save_brain(self, brain: dict) -> None:
        brain["updated_at"] = now_iso()
        write_json(self.brain_path, brain)

    def contract(self) -> dict:
        return read_json(self.contract_path, None) or {"schema": "veratum.contract/v1", "status": "NONE"}

    def save_contract(self, contract: dict) -> None:
        write_json(self.contract_path, contract)

    def ledger(self) -> dict:
        return read_json(self.ledger_path, None) or new_ledger()

    def save_ledger(self, ledger: dict) -> None:
        write_json(self.ledger_path, ledger)

    def state(self) -> dict:
        return read_json(self.state_path, None) or {"schema": "veratum.state/v1", "checkpoints": [], "stop_blocks": 0}

    def save_state(self, state: dict) -> None:
        write_json(self.state_path, state)

    def initialized(self) -> bool:
        return self.dir.is_dir() and self.brain_path.exists()

    def require_init(self) -> None:
        if not self.initialized():
            initialize(self, quiet=True)


def find_root(explicit: str | None = None) -> Path:
    if explicit:
        return Path(explicit).resolve()
    env_root = os.environ.get("VERATUM_ROOT")
    if env_root:
        return Path(env_root).resolve()
    here = Path(__file__).resolve().parent
    if here.name == "engine" and here.parent.name == VERATUM_DIRNAME:
        return here.parent.parent
    cwd = Path.cwd().resolve()
    for candidate in [cwd] + list(cwd.parents):
        if (candidate / VERATUM_DIRNAME).is_dir():
            return candidate
    top = git_toplevel(cwd)
    return top or cwd


# ---------------------------------------------------------------------------
# Git helpers
# ---------------------------------------------------------------------------

_GIT_REPO_CACHE: dict = {}


def git_available() -> bool:
    return shutil.which("git") is not None


def _git_env(extra: dict | None = None) -> dict:
    env = dict(os.environ)
    env.setdefault("GIT_AUTHOR_NAME", "Veratum")
    env.setdefault("GIT_AUTHOR_EMAIL", "checkpoint@veratum.local")
    env.setdefault("GIT_COMMITTER_NAME", "Veratum")
    env.setdefault("GIT_COMMITTER_EMAIL", "checkpoint@veratum.local")
    env["GIT_TERMINAL_PROMPT"] = "0"
    if extra:
        env.update(extra)
    return env


def git(root: Path, args: list, input_text: str | None = None, env: dict | None = None,
        check: bool = True, timeout: int = 120) -> str:
    kwargs = dict(cwd=str(root), capture_output=True, env=_git_env(env), timeout=timeout)
    if input_text is not None:
        kwargs["input"] = input_text.encode("utf-8")
    else:
        kwargs["stdin"] = subprocess.DEVNULL
    proc = subprocess.run(["git"] + list(args), **kwargs)
    out = proc.stdout.decode("utf-8", errors="replace")
    if check and proc.returncode != 0:
        err = proc.stderr.decode("utf-8", errors="replace").strip()
        raise VeratumError("git {} failed: {}".format(" ".join(args[:3]), err or out.strip()), 2)
    return out


def git_toplevel(path: Path) -> Path | None:
    if not git_available():
        return None
    try:
        out = git(path, ["rev-parse", "--show-toplevel"], check=True).strip()
        return Path(out).resolve() if out else None
    except (VeratumError, OSError, subprocess.SubprocessError):
        return None


def is_git_repo(root: Path) -> bool:
    key = str(root)
    if key in _GIT_REPO_CACHE:
        return _GIT_REPO_CACHE[key]
    ok = False
    if git_available():
        try:
            ok = git(root, ["rev-parse", "--is-inside-work-tree"], check=True).strip() == "true"
        except (VeratumError, OSError, subprocess.SubprocessError):
            ok = False
    _GIT_REPO_CACHE[key] = ok
    return ok


def _zsplit(out: str) -> list:
    return [item for item in out.split("\0") if item]


# ---------------------------------------------------------------------------
# Working-tree fingerprint (cryptographic evidence binding)
# ---------------------------------------------------------------------------

def _excluded(rel: str, extra_patterns: list) -> bool:
    if rel == VERATUM_DIRNAME or rel.startswith(VERATUM_DIRNAME + "/"):
        return True
    return any(fnmatch.fnmatch(rel, pat) for pat in extra_patterns)


def _git_hash_objects(root: Path, paths: list) -> dict:
    result = {}
    safe = [p for p in paths if "\n" not in p]
    for i in range(0, len(safe), 500):
        chunk = safe[i:i + 500]
        out = git(root, ["hash-object", "--stdin-paths"], input_text="\n".join(chunk) + "\n")
        shas = out.split()
        for path, sha in zip(chunk, shas):
            result[path] = sha
    return result


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def snapshot(ws: Workspace) -> dict:
    """Map of workspace-relative path -> content id for every non-ignored file.

    Git workspaces use blob ids (index ids for clean files, `git hash-object`
    for modified/untracked files), so the fingerprint is content-addressed:
    it is invariant to staging and committing but changes on ANY byte edit,
    file creation or deletion. Non-git workspaces fall back to SHA-256 of
    every file outside ignored directories.
    """
    extra = list(ws.config().get("fingerprint_exclude") or [])
    entries: dict = {}
    if is_git_repo(ws.root):
        root = ws.root
        git(root, ["update-index", "-q", "--refresh"], check=False)
        for rec in _zsplit(git(root, ["ls-files", "-s", "-z"])):
            meta, _, path = rec.partition("\t")
            parts = meta.split()
            if len(parts) >= 2 and path:
                entries[path] = parts[1]
        to_hash = []
        for path in _zsplit(git(root, ["ls-files", "-m", "-z"])):
            full = root / path
            if full.is_file():
                to_hash.append(path)
            elif not full.exists():
                entries.pop(path, None)
        for path in _zsplit(git(root, ["ls-files", "-o", "--exclude-standard", "-z"])):
            if (root / path).is_file():
                to_hash.append(path)
        to_hash = [p for p in dict.fromkeys(to_hash) if not _excluded(p, extra)]
        entries.update(_git_hash_objects(root, to_hash))
    else:
        for dirpath, dirnames, filenames in os.walk(ws.root):
            dirnames[:] = [d for d in dirnames if d not in IGNORE_DIRS]
            for name in filenames:
                full = Path(dirpath) / name
                rel = to_posix(os.path.relpath(str(full), str(ws.root)))
                try:
                    entries[rel] = "sha256:" + _sha256_file(full)
                except OSError:
                    continue
    return {p: s for p, s in entries.items() if not _excluded(p, extra)}


def tree_hash(entries: dict) -> str:
    h = hashlib.sha256()
    h.update(b"veratum-tree-v1\n")
    for path in sorted(entries):
        h.update(path.encode("utf-8", errors="surrogateescape"))
        h.update(b"\0")
        h.update(entries[path].encode("ascii", errors="replace"))
        h.update(b"\n")
    return h.hexdigest()


def diff_entries(before: dict, after: dict) -> list:
    return sorted(p for p in set(before) | set(after) if before.get(p) != after.get(p))


# ---------------------------------------------------------------------------
# Stack detection & brain
# ---------------------------------------------------------------------------

def _read_text(path: Path, limit: int = 512 * 1024) -> str:
    try:
        with open(path, "rb") as fh:
            return fh.read(limit).decode("utf-8", errors="replace")
    except OSError:
        return ""


def detect_stack(root: Path) -> dict:
    stack: list = []
    commands: dict = {}
    package_manager = None

    pkg = read_json(root / "package.json", None)
    if isinstance(pkg, dict):
        stack.append("node")
        if (root / "pnpm-lock.yaml").exists():
            package_manager = "pnpm"
        elif (root / "yarn.lock").exists():
            package_manager = "yarn"
        elif (root / "bun.lockb").exists() or (root / "bun.lock").exists():
            package_manager = "bun"
        else:
            package_manager = "npm"
        scripts = pkg.get("scripts") or {}
        deps = {}
        deps.update(pkg.get("dependencies") or {})
        deps.update(pkg.get("devDependencies") or {})
        if "typescript" in deps or (root / "tsconfig.json").exists():
            stack.append("typescript")
        for framework in ("next", "react", "vue", "svelte", "express", "nestjs", "@nestjs/core", "vite"):
            if framework in deps:
                stack.append(framework.replace("@nestjs/core", "nestjs"))

        def run(script: str) -> str:
            if package_manager == "npm":
                return "npm test" if script == "test" else "npm run " + script
            return "{} {}".format(package_manager, script if script == "test" else "run " + script)

        test_script = scripts.get("test", "")
        if test_script and "no test specified" not in test_script:
            commands["test"] = run("test")
        for kind, names in (("build", ["build"]), ("lint", ["lint"]),
                            ("typecheck", ["typecheck", "type-check", "tsc", "check-types"])):
            for name in names:
                if name in scripts:
                    commands[kind] = run(name)
                    break
        if "typecheck" not in commands and "typescript" in stack:
            commands["typecheck"] = "npx tsc --noEmit"

    pyproject = _read_text(root / "pyproject.toml")
    if pyproject or (root / "setup.py").exists() or (root / "requirements.txt").exists() or (root / "setup.cfg").exists():
        stack.append("python")
        reqs = pyproject + _read_text(root / "requirements.txt") + _read_text(root / "requirements-dev.txt")
        has_pytest = "pytest" in reqs or (root / "pytest.ini").exists() or (root / "conftest.py").exists()
        commands.setdefault("test", "python -m pytest -q" if has_pytest else "python -m unittest discover -s tests")
        if "ruff" in reqs:
            commands.setdefault("lint", "ruff check .")
        elif "flake8" in reqs:
            commands.setdefault("lint", "flake8")
        if "mypy" in reqs:
            commands.setdefault("typecheck", "mypy .")

    if (root / "Cargo.toml").exists():
        stack.append("rust")
        commands.setdefault("test", "cargo test")
        commands.setdefault("build", "cargo build")
        commands.setdefault("lint", "cargo clippy -- -D warnings")

    if (root / "go.mod").exists():
        stack.append("go")
        commands.setdefault("test", "go test ./...")
        commands.setdefault("build", "go build ./...")
        commands.setdefault("lint", "go vet ./...")

    if (root / "pom.xml").exists():
        stack.append("java")
        commands.setdefault("test", "mvn -q test")
        commands.setdefault("build", "mvn -q package -DskipTests")
    elif (root / "build.gradle").exists() or (root / "build.gradle.kts").exists():
        stack.append("java")
        wrapper = "./gradlew" if (root / "gradlew").exists() else "gradle"
        commands.setdefault("test", wrapper + " test")
        commands.setdefault("build", wrapper + " build -x test")

    makefile = _read_text(root / "Makefile")
    if makefile:
        stack.append("make")
        if re.search(r"^test\s*:", makefile, re.M):
            commands.setdefault("test", "make test")
        if re.search(r"^build\s*:", makefile, re.M):
            commands.setdefault("build", "make build")

    return {"stack": list(dict.fromkeys(stack)), "commands": commands, "package_manager": package_manager}


def scan_modules(root: Path, max_files: int = 20000) -> dict:
    modules: dict = {}
    entrypoints: list = []
    entry_names = {"main.py", "app.py", "__main__.py", "manage.py", "index.ts", "index.js", "main.ts",
                   "main.go", "main.rs", "lib.rs", "server.ts", "server.js", "app.ts", "app.js", "Main.java"}
    count = 0
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in IGNORE_DIRS and not d.startswith("."))
        rel_dir = to_posix(os.path.relpath(dirpath, str(root)))
        top = "." if rel_dir == "." else rel_dir.split("/")[0]
        for name in filenames:
            ext = os.path.splitext(name)[1].lower()
            if ext not in LANG_BY_EXT:
                continue
            count += 1
            if count > max_files:
                break
            mod = modules.setdefault(top, {"files": 0, "languages": {}})
            mod["files"] += 1
            lang = ext.lstrip(".")
            mod["languages"][lang] = mod["languages"].get(lang, 0) + 1
            if name in entry_names and len(entrypoints) < 15:
                entrypoints.append(("" if rel_dir == "." else rel_dir + "/") + name)
        if count > max_files:
            break
    return {"modules": modules, "entrypoints": entrypoints, "source_files": min(count, max_files)}


def new_brain(root: Path) -> dict:
    return {
        "schema": "veratum.brain/v1",
        "project": Path(root).name,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "stack": [],
        "package_manager": None,
        "commands": {},
        "known_good_commands": {},
        "modules": {},
        "entrypoints": [],
        "insights": [],
        "task_history": [],
        "stats": {"verify_runs": 0, "verify_passes": 0, "tasks_completed": 0, "log_lines_saved": 0},
    }


def new_ledger() -> dict:
    return {
        "schema": "veratum.ledger/v1",
        "status": STATUS_UNVERIFIED,
        "contract_id": None,
        "command": None,
        "exit_code": None,
        "duration_sec": None,
        "timestamp": None,
        "tree_hash": None,
        "consecutive_failures": 0,
        "history": [],
    }


INSIGHT_KINDS = ("insight", "decision", "pitfall", "architecture", "command")


def brain_remember(ws: Workspace, text: str, kind: str = "insight", files=None) -> dict:
    ws.require_init()
    text = text.strip()
    if not text:
        raise VeratumError("Nothing to remember: provide a non-empty insight.")
    if kind not in INSIGHT_KINDS:
        raise VeratumError("Unknown insight kind '{}'. Use one of: {}".format(kind, ", ".join(INSIGHT_KINDS)))
    brain = ws.brain()
    for item in brain.get("insights", []):
        if item.get("text", "").strip().lower() == text.lower():
            return item
    next_id = 1 + max([int(str(i.get("id", "m0"))[1:] or 0) for i in brain.get("insights", [])] + [0])
    item = {"id": "m{}".format(next_id), "kind": kind, "text": text, "files": split_csv(files), "created_at": now_iso()}
    brain.setdefault("insights", []).append(item)
    ws.save_brain(brain)
    return item


# ---------------------------------------------------------------------------
# Background Auto-Update Checker
# ---------------------------------------------------------------------------

UPDATE_CHECK_INTERVAL_SEC = 86400  # check at most once every 24 hours on success
UPDATE_FAILURE_BACKOFF_SEC = 21600  # 6 hours backoff on network failure / offline / rate limit


def _detect_update_command(ws: Workspace) -> str:
    """Determine recommended update command based on execution environment."""
    if (ws.root / "package.json").is_file():
        try:
            pkg = read_json(ws.root / "package.json", {}) or {}
            deps = dict(pkg.get("dependencies", {}))
            deps.update(pkg.get("devDependencies", {}))
            if "veratum" in deps:
                return "npm update veratum"
        except Exception:
            pass
    if (ws.root / ".git").is_dir() and (ws.root / "bin" / "veratum.js").is_file():
        return "git pull && npm run build"
    return "npx veratum init"


def check_auto_update(ws: Workspace, force: bool = False, fetcher=None) -> dict:
    """Check GitHub release for a newer Veratum version with 100% silent offline fallback and failure backoff."""
    state = ws.state()
    update_info = state.get("update_check") or {}
    now = time.time()
    last_check = update_info.get("checked_at_ts") or 0
    last_success = update_info.get("last_success", True)
    interval = UPDATE_CHECK_INTERVAL_SEC if last_success else UPDATE_FAILURE_BACKOFF_SEC

    if not force and (now - last_check) < interval:
        return update_info

    latest_tag = None
    fetch_success = False
    error_reason = None
    if fetcher:
        try:
            latest_tag = fetcher()
            fetch_success = bool(latest_tag)
        except BaseException as e:
            error_reason = str(e)
            latest_tag = None
    else:
        try:
            import urllib.error
            import urllib.request
            req = urllib.request.Request(
                "https://api.github.com/repos/yadavmandeep/Veratum/releases/latest",
                headers={"User-Agent": "Veratum-Engine/{}".format(VERSION), "Accept": "application/vnd.github.v3+json"}
            )
            with urllib.request.urlopen(req, timeout=1.0) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode("utf-8"))
                    latest_tag = data.get("tag_name")
                    fetch_success = True
        except BaseException as e:
            error_reason = type(e).__name__
            latest_tag = None

    update_cmd = _detect_update_command(ws)
    if fetch_success and latest_tag:
        clean_latest = latest_tag.lstrip("v").strip()
        has_update = _version_tuple(clean_latest) > _version_tuple(VERSION)
        update_info = {
            "checked_at_ts": now,
            "checked_at": now_iso(),
            "current_version": VERSION,
            "latest_version": clean_latest,
            "update_available": has_update,
            "last_success": True,
            "update_command": update_cmd,
        }
    else:
        prev_latest = update_info.get("latest_version") or VERSION
        prev_avail = update_info.get("update_available", False)
        update_info = {
            "checked_at_ts": now,
            "checked_at": now_iso(),
            "current_version": VERSION,
            "latest_version": prev_latest,
            "update_available": prev_avail,
            "last_success": False,
            "last_error": error_reason or "offline",
            "update_command": update_cmd,
        }
    state["update_check"] = update_info
    ws.save_state(state)
    return update_info


def _version_tuple(v: str) -> tuple:
    try:
        return tuple(int(x) for x in re.findall(r"\d+", str(v)))
    except Exception:
        return (0,)


def brain_context(ws: Workspace, max_insights: int = 12) -> str:
    """Compact brain summary for session-start injection (token-efficient)."""
    brain = ws.brain()
    lines = ["[VERATUM BRAIN] project={} | stack={}".format(
        brain.get("project"), ", ".join(brain.get("stack") or []) or "unknown")]
    # Version & auto-update notice
    update_info = ws.state().get("update_check") or {}
    if update_info.get("update_available"):
        cmd = update_info.get("update_command") or _detect_update_command(ws)
        lines.append("✨ [VERATUM UPDATE AVAILABLE] v{} → v{} (Run `{}`)".format(
            VERSION, update_info.get("latest_version"), cmd))
    cmds = brain.get("commands") or {}
    if cmds:
        lines.append("Commands: " + " | ".join("{}=`{}`".format(k, v) for k, v in sorted(cmds.items())))
    mods = brain.get("modules") or {}
    if mods:
        top = sorted(mods.items(), key=lambda kv: -kv[1].get("files", 0))[:8]
        lines.append("Modules: " + ", ".join(
            "{}({} {})".format(name, info.get("files"), "/".join(sorted(info.get("languages", {}), key=lambda l: -info["languages"][l])[:2]))
            for name, info in top))
    if brain.get("entrypoints"):
        lines.append("Entrypoints: " + ", ".join(brain["entrypoints"][:6]))
    insights = brain.get("insights") or []
    pitfalls = [i for i in insights if i.get("kind") == "pitfall"]
    others = [i for i in insights if i.get("kind") != "pitfall"]
    if pitfalls:
        lines.append("Pitfalls (avoid repeating):")
        lines.extend("  - [{}] {}".format(i["id"], i["text"]) for i in pitfalls[-6:])
    if others:
        lines.append("Memory:")
        lines.extend("  - [{}|{}] {}".format(i["id"], i.get("kind"), i["text"]) for i in others[-max_insights:])
    gstats = (read_json(ws.dir / "graph" / "graph.json", {}) or {}).get("stats")
    if gstats:
        lines.append("Knowledge graph: {} files · {} nodes · {} edges. Use `graph query \"<question>\"` (or MCP veratum_graph) "
                     "BEFORE grepping or opening many files; overview in .veratum/graph/GRAPH_REPORT.md.".format(
                         gstats.get("files"), gstats.get("nodes"), gstats.get("edges")))
    history = brain.get("task_history") or []
    if history:
        last = history[-1]
        lines.append("Last completed task: {} ({})".format(last.get("goal"), last.get("completed_at")))
    contract = ws.contract()
    if contract.get("status") == "ACTIVE":
        ledger = ws.ledger()
        lines.append("ACTIVE CONTRACT {}: {} | files: {} | ledger: {}".format(
            contract.get("id"), contract.get("goal"), ", ".join(contract.get("files", [])), ledger.get("status")))
    else:
        lines.append("No active contract. Before editing: `veratum_cli.py contract --goal \"...\" --files \"a,b\" --verify \"<cmd>\"`.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Blast-radius / dependency analysis
# ---------------------------------------------------------------------------

TEST_FILE_RE = re.compile(
    r"(^|/)(test_[^/]+\.py|[^/]+_test\.(py|go)|[^/]+\.(test|spec)\.(t|j)sx?|[^/]+(Test|Tests|IT)\.(java|kt)|[^/]+_spec\.rb)$"
    r"|(^|/)(tests?|__tests__|spec)/"
)

_JS_IMPORT_RE = re.compile(r"""(?:\bfrom\s*|\bimport\s*\(?\s*|\brequire\s*\(\s*)['"]([^'"\n]+)['"]""")
_PY_FROM_RE = re.compile(r"^[ \t]*from[ \t]+([.\w]+)[ \t]+import[ \t]+(\([^)]*\)|[^\n#]+)", re.M)
_PY_IMPORT_RE = re.compile(r"^[ \t]*import[ \t]+([^\n#]+)", re.M)
_GO_BLOCK_RE = re.compile(r"\bimport\s*\(([^)]*)\)", re.S)
_GO_SINGLE_RE = re.compile(r'\bimport\s+(?:[\w.]+\s+)?"([^"]+)"')
_QUOTED_RE = re.compile(r'"([^"]+)"')
_RS_USE_RE = re.compile(r"^[ \t]*(?:pub(?:\([^)]*\))?[ \t]+)?use[ \t]+([\w:]+)", re.M)
_RS_MOD_RE = re.compile(r"^[ \t]*(?:pub(?:\([^)]*\))?[ \t]+)?mod[ \t]+(\w+)[ \t]*;", re.M)
_JAVA_IMPORT_RE = re.compile(r"^[ \t]*import[ \t]+(?:static[ \t]+)?(\w+(?:\.\w+)*(?:\.\*)?)[ \t]*;?", re.M)
_JAVA_PACKAGE_RE = re.compile(r"^[ \t]*package[ \t]+([\w.]+)", re.M)
_C_INCLUDE_RE = re.compile(r'^[ \t]*#[ \t]*include[ \t]*"([^"]+)"', re.M)


def _py_import_names(raw: str) -> list:
    clean = [n.strip().split(" as ")[0].strip() for n in raw.strip("() \t").replace("\n", " ").split(",")]
    return [n for n in clean if n and n != "*" and n.isidentifier()]


_IMPORT_LINE_PREFIXES = ("import ", "from ", "use ", "pub use ", "pub mod ", "mod ", "package ", "#include")

# Relationship confidence (borrowed from Graphify's EXTRACTED / INFERRED idea, implemented natively):
#   EXTRACTED - an import / include / use statement in the source resolves to the target (evidence = that line)
#   INFERRED  - deduced from names or history: symbol mentions, dynamic references, git co-change, test naming
CONF_EXTRACTED = "EXTRACTED"
CONF_INFERRED = "INFERRED"


def _strip_js_ext(path: str) -> str:
    if path.endswith(".d.ts"):
        return path[:-5]
    for ext in JS_EXTS + TS_EXTS + TSX_EXTS:
        if path.endswith(ext):
            return path[: -len(ext)]
    return path



def _py_module(rel: str) -> list:
    noext = rel[:-3] if rel.endswith(".py") else rel
    parts = noext.split("/")
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    return parts


def _rs_module(rel: str) -> list:
    parts = rel[:-3].split("/") if rel.endswith(".rs") else rel.split("/")
    if "src" in parts:
        idx = len(parts) - 1 - parts[::-1].index("src")
        parts = parts[idx + 1:]
    if parts and parts[-1] == "mod":
        parts = parts[:-1]
    if parts in (["lib"], ["main"]):
        return []
    return parts


class CodeIndex:
    """Lazy import index over the workspace's source files."""

    def __init__(self, ws: Workspace, max_files: int | None = 25000):
        self.ws = ws
        self.root = ws.root
        self.files = self._list_files(max_files)
        self._parsed: dict = {}
        self._go_module = None
        gomod = _read_text(self.root / "go.mod", 4096)
        m = re.search(r"^module\s+(\S+)", gomod, re.M)
        if m:
            self._go_module = m.group(1)

    def _list_files(self, max_files: int | None, exts=None) -> list:
        exts = exts or LANG_BY_EXT
        files = []
        if is_git_repo(self.root):
            out = git(self.root, ["ls-files", "-co", "--exclude-standard", "-z"])
            for rel in _zsplit(out):
                if os.path.splitext(rel)[1].lower() in exts and not _excluded(rel, []):
                    if not any(part in IGNORE_DIRS for part in rel.split("/")[:-1]):
                        files.append(rel)
        else:
            for dirpath, dirnames, filenames in os.walk(self.root):
                dirnames[:] = [d for d in dirnames if d not in IGNORE_DIRS]
                for name in filenames:
                    if os.path.splitext(name)[1].lower() in exts:
                        files.append(to_posix(os.path.relpath(os.path.join(dirpath, name), str(self.root))))
        files = sorted(set(files))
        return files[:max_files] if max_files else files  # None / 0 = every file

    def lang(self, rel: str) -> str | None:
        return LANG_BY_EXT.get(os.path.splitext(rel)[1].lower())

    def parsed(self, rel: str) -> dict:
        if rel in self._parsed:
            return self._parsed[rel]
        text = _read_text(self.root / rel)
        lang = self.lang(rel)
        data: dict = {"lang": lang}
        if lang in ("js", "ts", "tsx"):
            data["specs"] = _JS_IMPORT_RE.findall(text)
        elif lang == "py":
            stmts = []
            for module, names in _PY_FROM_RE.findall(text):
                stmts.append((module, _py_import_names(names)))
            for names in _PY_IMPORT_RE.findall(text):
                for name in names.split(","):
                    name = name.strip().split(" as ")[0].strip()
                    if name:
                        stmts.append((name, []))
            data["stmts"] = stmts
        elif lang == "go":
            paths = list(_GO_SINGLE_RE.findall(text))
            for block in _GO_BLOCK_RE.findall(text):
                paths.extend(_QUOTED_RE.findall(block))
            data["imports"] = paths
        elif lang == "rs":
            data["uses"] = [u.rstrip(":") for u in _RS_USE_RE.findall(text)]
            data["mods"] = _RS_MOD_RE.findall(text)
        elif lang == "java":
            data["imports"] = _JAVA_IMPORT_RE.findall(text)
            m = _JAVA_PACKAGE_RE.search(text)
            data["package"] = m.group(1) if m else ""
            data["text"] = text
        elif lang == "c":
            data["includes"] = _C_INCLUDE_RE.findall(text)
        self._parsed[rel] = data
        return data

    # -- per-language matchers ------------------------------------------
    def _match_js(self, target: str, importer: str, spec: str) -> bool:
        cands = {_strip_js_ext(target)}
        base = _strip_js_ext(target)
        if base.endswith("/index"):
            cands.add(base[: -len("/index")])
        elif base == "index":
            cands.add("")
        if spec.startswith("."):
            resolved = posixpath.normpath(posixpath.join(posixpath.dirname(importer), spec))
            resolved = "" if resolved == "." else resolved
            return _strip_js_ext(resolved) in cands or resolved == target
        segs = spec.split("/")
        tails = [spec]
        if len(segs) > 1 and segs[0][:1] in ("@", "~", "#"):
            tails.append("/".join(segs[1:]))
        for tail in tails:
            tail = _strip_js_ext(tail)
            for cand in cands:
                if cand and (cand == tail or cand.endswith("/" + tail)):
                    return True
        return False

    def _match_py(self, target: str, importer: str, stmts: list) -> bool:
        tmod = _py_module(target)
        if not tmod:
            return False
        tdotted = ".".join(tmod)
        tdir = posixpath.dirname(target)
        importer_pkg = posixpath.dirname(importer).split("/") if posixpath.dirname(importer) else []
        for module, names in stmts:
            candidates = []
            if module.startswith("."):
                level = len(module) - len(module.lstrip("."))
                rest = module.lstrip(".")
                base = importer_pkg[: len(importer_pkg) - (level - 1)] if level > 1 else list(importer_pkg)
                full = base + (rest.split(".") if rest else [])
                candidates.append((".".join(full), True))
                candidates.extend((".".join(full + [n]), True) for n in names)
            else:
                candidates.append((module, False))
                candidates.extend((module + "." + n, False) for n in names)
            for cand, absolute in candidates:
                if not cand:
                    continue
                if cand == tdotted:
                    return True
                if absolute:
                    continue
                if tdotted.endswith("." + cand):
                    if "." in cand:
                        return True
                    if posixpath.dirname(importer) == tdir or tdir in ("", "src", "lib"):
                        return True
        return False

    def _match_go(self, target: str, importer: str, imports: list) -> bool:
        tdir = posixpath.dirname(target)
        if posixpath.dirname(importer) == tdir:
            return False
        for imp in imports:
            if self._go_module:
                if imp == (self._go_module + "/" + tdir if tdir else self._go_module):
                    return True
            if tdir and (imp == tdir or imp.endswith("/" + tdir)):
                return True
        return False

    def _match_rs(self, target: str, importer: str, data: dict) -> bool:
        tmod = _rs_module(target)
        if not tmod:
            return False
        imod = _rs_module(importer)
        for use in data.get("uses", []):
            segs = [s for s in use.split("::") if s]
            if not segs:
                continue
            if segs[0] == "crate":
                path = segs[1:]
            elif segs[0] == "self":
                path = imod + segs[1:]
            elif segs[0] == "super":
                n = 0
                while n < len(segs) and segs[n] == "super":
                    n += 1
                path = imod[: max(0, len(imod) - n)] + segs[n:]
            else:
                path = segs
            if path[: len(tmod)] == tmod:
                return True
        for name in data.get("mods", []):
            declared = imod + [name]
            if declared == tmod:
                return True
        return False

    def _match_java(self, target: str, importer: str, data: dict) -> bool:
        tdata = self.parsed(target) if (self.root / target).exists() else {"package": ""}
        tpkg = tdata.get("package") or ".".join(posixpath.dirname(target).split("/"))
        cls = posixpath.splitext(posixpath.basename(target))[0]
        fqcn = (tpkg + "." + cls) if tpkg else cls
        for imp in data.get("imports", []):
            if imp == fqcn or imp.startswith(fqcn + ".") or (tpkg and imp == tpkg + ".*"):
                return True
        if data.get("package", "") == tpkg and re.search(r"\b{}\b".format(re.escape(cls)), data.get("text", "")):
            return True
        return False

    def _match_c(self, target: str, importer: str, includes: list) -> bool:
        for inc in includes:
            resolved = posixpath.normpath(posixpath.join(posixpath.dirname(importer), inc))
            if resolved == target or target == inc or target.endswith("/" + inc):
                return True
        return False

    def depends_on(self, importer: str, target: str) -> bool:
        if importer == target:
            return False
        tlang, ilang = self.lang(target), self.lang(importer)
        if not tlang or not ilang:
            return False
        js_group = {"js", "ts", "tsx"}
        if tlang in js_group and ilang in js_group:
            data = self.parsed(importer)
            return any(self._match_js(target, importer, s) for s in data.get("specs", []))
        if tlang != ilang:
            return False
        data = self.parsed(importer)
        if tlang == "py":
            return self._match_py(target, importer, data.get("stmts", []))
        if tlang == "go":
            return self._match_go(target, importer, data.get("imports", []))
        if tlang == "rs":
            return self._match_rs(target, importer, data)
        if tlang == "java":
            return self._match_java(target, importer, data)
        if tlang == "c":
            return self._match_c(target, importer, data.get("includes", []))
        return False

    def dependents(self, target: str) -> list:
        return [f for f in self.files if self.depends_on(f, target)]

    # -- symbols ------------------------------------------------------------
    _SYMBOL_PATTERNS = {
        "js": [r"export\s+(?:default\s+)?(?:declare\s+)?(?:async\s+)?(?:function\*?|class|const|let|var|interface|type|enum)\s+([A-Za-z_$][\w$]*)"],
        "py": [r"^(?:async\s+)?def\s+([A-Za-z]\w*)", r"^class\s+([A-Za-z]\w*)", r"^([A-Z][A-Z0-9_]{2,})\s*[:=]"],
        "go": [r"^func\s+(?:\([^)]*\)\s*)?([A-Z]\w*)", r"^type\s+([A-Z]\w*)", r"^(?:var|const)\s+([A-Z]\w*)"],
        "rs": [r"^\s*pub(?:\([^)]*\))?\s+(?:async\s+)?(?:unsafe\s+)?(?:fn|struct|enum|trait|type|const|static)\s+([A-Za-z_]\w*)"],
        "java": [r"^\s*public\s+(?:static\s+|final\s+|abstract\s+|sealed\s+)*(?:class|interface|enum|record)\s+(\w+)",
                 r"^\s*public\s+(?:static\s+|final\s+|synchronized\s+|abstract\s+)*[\w<>\[\],.?\s]+?\s+(\w+)\s*\("],
        "c": [r"^[A-Za-z_][\w \t\*]*?\b([A-Za-z_]\w*)\s*\([^;{]*\)\s*\{"],
    }
    _COMMON_WORDS = {"main", "init", "index", "default", "test", "setup", "run", "get", "set", "data", "config", "value",
                     "name", "type", "error", "result", "string", "number", "props", "state", "handler", "update", "create"}

    def symbols(self, rel: str) -> list:
        lang = self.lang(rel)
        text = _read_text(self.root / rel)
        found = []
        pats = self._SYMBOL_PATTERNS.get(lang) or (self._SYMBOL_PATTERNS.get("js") if lang in ("ts", "tsx") else [])
        for pat in pats:
            found.extend(re.findall(pat, text, re.M))
        if lang in ("js", "ts", "tsx"):
            for block in re.findall(r"export\s*\{([^}]*)\}", text):
                for part in block.split(","):
                    name = part.strip().split(" as ")[-1].strip()
                    if re.match(r"^[A-Za-z_$][\w$]*$", name):
                        found.append(name)
        return [s for s in dict.fromkeys(found) if s and not s.startswith("_")]

    def symbol_usage(self, dependent: str, symbols: list) -> list:
        if not symbols:
            return []
        text = _read_text(self.root / dependent)
        return [s for s in symbols if re.search(r"(?<![\w$]){}(?![\w$])".format(re.escape(s)), text)]

    def dynamic_refs(self, target: str, symbols: list, exclude: set, limit: int = 10) -> list:
        """Files that mention a distinctive exported name WITHOUT a resolvable import (dynamic import,
        reflection, string registration, re-exports through other languages)."""
        distinctive = [s for s in symbols if len(s) >= 6 and s.lower() not in self._COMMON_WORDS]
        if not distinctive:
            return []
        rx = re.compile(r"(?<![\w$])(" + "|".join(re.escape(s) for s in distinctive[:40]) + r")(?![\w$])")
        hits = []
        for f in self.files:
            if f == target or f in exclude:
                continue
            m = rx.search(_read_text(self.root / f))
            if m:
                hits.append({"file": f, "symbol": m.group(1)})
                if len(hits) >= limit:
                    break
        return hits

    # -- evidence: file:line proof behind every relationship -------------------
    @staticmethod
    def _line_no(text: str, pos: int) -> int:
        return text.count("\n", 0, pos) + 1

    def _find_line(self, text: str, needle: str):
        pos = text.find(needle)
        return None if pos < 0 else self._line_no(text, pos)

    def import_evidence(self, importer: str, target: str, limit: int = 3) -> tuple:
        """(evidence, confidence): the import statement line(s) in `importer` that resolve to `target`."""
        text = _read_text(self.root / importer)
        lines = text.splitlines()
        lang = self.lang(importer)
        data = self.parsed(importer)
        found: list = []
        confidence = CONF_EXTRACTED
        if lang in ("js", "ts", "tsx"):
            for m in _JS_IMPORT_RE.finditer(text):
                if self._match_js(target, importer, m.group(1)):
                    found.append(self._line_no(text, m.start()))
        elif lang == "py":
            for m in _PY_FROM_RE.finditer(text):
                if self._match_py(target, importer, [(m.group(1), _py_import_names(m.group(2)))]):
                    found.append(self._line_no(text, m.start()))
            for m in _PY_IMPORT_RE.finditer(text):
                stmts = [(n.strip().split(" as ")[0].strip(), []) for n in m.group(1).split(",") if n.strip()]
                if stmts and self._match_py(target, importer, stmts):
                    found.append(self._line_no(text, m.start()))
        elif lang == "go":
            for imp in data.get("imports", []):
                if self._match_go(target, importer, [imp]):
                    found.append(self._find_line(text, '"{}"'.format(imp)))
        elif lang == "rs":
            for use in data.get("uses", []):
                if self._match_rs(target, importer, {"uses": [use], "mods": []}):
                    found.append(self._find_line(text, use))
            for name in data.get("mods", []):
                if self._match_rs(target, importer, {"uses": [], "mods": [name]}):
                    found.append(self._find_line(text, "mod " + name))
        elif lang == "java":
            for imp in data.get("imports", []):
                if self._match_java(target, importer, {"imports": [imp], "package": "", "text": ""}):
                    found.append(self._find_line(text, imp))
            if not found:  # same-package use without an import: a name match, not a statement
                confidence = CONF_INFERRED
                cls = posixpath.splitext(posixpath.basename(target))[0]
                m = re.search(r"\b{}\b".format(re.escape(cls)), text)
                if m:
                    found.append(self._line_no(text, m.start()))
        elif lang == "c":
            for inc in data.get("includes", []):
                if self._match_c(target, importer, [inc]):
                    found.append(self._find_line(text, inc))
        evidence = []
        for ln in dict.fromkeys(n for n in found if n):
            evidence.append({"file": importer, "line": ln, "text": lines[ln - 1].strip()[:160] if ln <= len(lines) else ""})
            if len(evidence) >= limit:
                break
        if not evidence:
            confidence = CONF_INFERRED  # resolved by the matcher but the statement could not be located
        return evidence, confidence

    def symbol_sites(self, rel: str, symbols: list, limit: int = 4) -> list:
        """First non-import line where each symbol appears in `rel` (call vs plain reference). Name match only."""
        lines = _read_text(self.root / rel).splitlines()
        out: list = []
        for sym in symbols:
            rx = re.compile(r"(?<![\w$]){}(?![\w$])".format(re.escape(sym)))
            in_import = False
            for i, line in enumerate(lines, 1):
                stripped = line.strip()
                if in_import:
                    in_import = ")" not in stripped
                    continue
                if stripped.startswith(_IMPORT_LINE_PREFIXES) or _JS_IMPORT_RE.search(line):
                    in_import = ("(" in stripped or stripped.endswith("{")) and ")" not in stripped and "}" not in stripped
                    continue
                if stripped.startswith(("#", "//", "*", "/*", "--")):
                    continue
                m = rx.search(line)
                if m:
                    call = re.match(r"\s*\(", line[m.end():]) is not None
                    out.append({"file": rel, "line": i, "symbol": sym, "kind": "call" if call else "reference",
                                "text": stripped[:160]})
                    break
            if len(out) >= limit:
                break
        return out

    def co_changed(self, target: str, max_commits: int = 200) -> list:
        """Files that historically changed in the same commits as `target` (git log)."""
        if not is_git_repo(self.root):
            return []
        out = git(self.root, ["log", "-n", str(max_commits), "--full-diff", "--format=@@%H", "--name-only", "--", target],
                  check=False, timeout=30)
        counts: dict = {}
        commits = 0
        for chunk in out.split("@@")[1:]:
            names = [to_posix(n.strip()) for n in chunk.splitlines()[1:] if n.strip()]
            if target not in names:
                continue
            commits += 1
            for n in names:
                if n != target:
                    counts[n] = counts.get(n, 0) + 1
        threshold = 2 if commits >= 3 else 1
        ranked = sorted(((n, c) for n, c in counts.items() if c >= threshold and (self.root / n).exists()),
                        key=lambda kv: (-kv[1], kv[0]))
        return [{"file": n, "commits": c, "of": commits} for n, c in ranked[:8]]

    def impact_edges(self, target: str, direct: list, usage: dict, levels: list, via: dict, co: list,
                     dynamic: list, tests: dict) -> list:
        """Relationship records with file:line evidence and EXTRACTED / INFERRED confidence."""
        edges: list = []

        def add(source, tgt, relation, confidence, evidence, depth=1):
            edges.append({"source": source, "target": tgt, "relation": relation, "confidence": confidence,
                          "depth": depth, "evidence": evidence})

        for d in direct:
            evidence, conf = self.import_evidence(d, target)
            add(d, target, "imports", conf, evidence)
            for site in self.symbol_sites(d, usage.get(d) or []):
                add(d, "{}::{}".format(target, site["symbol"]), "calls" if site["kind"] == "call" else "references",
                    CONF_INFERRED, [site])
        for depth_no, level in enumerate(levels[1:], start=2):
            for node in level:
                parent = via.get(node, target)
                evidence, conf = self.import_evidence(node, parent)
                add(node, parent, "imports", conf, evidence, depth_no)
        for hit in dynamic:
            add(hit["file"], "{}::{}".format(target, hit["symbol"]), "mentions", CONF_INFERRED,
                self.symbol_sites(hit["file"], [hit["symbol"]], 1))
        for item in co:
            add(item["file"], target, "co_changes", CONF_INFERRED,
                [{"commits": item["commits"], "of": item["of"], "source": "git log"}])
        for test, reason in sorted(tests.items()):
            add(test, target, "tests", CONF_INFERRED, [{"file": test, "reason": reason}])
        return edges

    def blast_radius(self, target: str, depth: int = 1, symbol: str | None = None, evidence: bool = False) -> dict:
        direct = self.dependents(target)
        exported = self.symbols(target) if (self.root / target).is_file() else []
        usage = {d: self.symbol_usage(d, exported) for d in direct}
        if symbol:
            direct = [d for d in direct if symbol in self.symbol_usage(d, [symbol])]
        levels = [direct]
        seen = {target, *direct}
        frontier = direct
        via: dict = {}
        for _ in range(max(0, depth - 1)):
            nxt = []
            for node in frontier:
                for dep in self.dependents(node):
                    if dep not in seen:
                        seen.add(dep)
                        via[dep] = node
                        nxt.append(dep)
            if not nxt:
                break
            levels.append(sorted(nxt))
            frontier = nxt
        all_deps = sorted(seen - {target})
        stem = posixpath.splitext(posixpath.basename(target))[0]
        stem_key = re.sub(r"[^a-z0-9]", "", stem.lower())
        tests = set(d for d in all_deps if TEST_FILE_RE.search(d))
        inferred_tests: dict = {}  # test file -> why it is only an inferred relationship
        if stem_key and len(stem_key) >= 3:
            for f in self.files:
                if TEST_FILE_RE.search(f) and stem_key in re.sub(r"[^a-z0-9]", "", posixpath.basename(f).lower()):
                    tests.add(f)
                    inferred_tests.setdefault(f, "test file name matches '{}'".format(stem))
        co = self.co_changed(target)
        for item in co:
            if TEST_FILE_RE.search(item["file"]):
                tests.add(item["file"])
                inferred_tests.setdefault(item["file"], "changed with target in {}/{} commits".format(item["commits"], item["of"]))
        tests.discard(target)
        inferred_tests = {t: why for t, why in inferred_tests.items() if t not in all_deps and t != target}
        dyn_syms = [symbol] if symbol else exported
        dynamic = self.dynamic_refs(target, dyn_syms, exclude=set(all_deps)) if (depth > 1 or symbol) else []
        n = len(all_deps)
        risk = "NONE" if n == 0 else "LOW" if n <= 2 else "MEDIUM" if n <= 8 else "HIGH"
        report = {
            "target": target,
            "exists": (self.root / target).exists(),
            "symbols": exported,
            "symbol_filter": symbol,
            "direct": direct,
            "usage": {d: usage.get(d, []) for d in direct},
            "transitive": levels[1:] if len(levels) > 1 else [],
            "all": all_deps,
            "tests": sorted(tests),
            "co_changed": co,
            "dynamic_refs": dynamic,
            "risk": risk,
        }
        if evidence:
            edges = self.impact_edges(target, direct, usage, levels, via, co, dynamic, inferred_tests)
            report["edges"] = edges
            report["confidence"] = {c: sum(1 for e in edges if e["confidence"] == c)
                                    for c in (CONF_EXTRACTED, CONF_INFERRED)}
        return report


def render_impact(report: dict) -> str:
    lines = ["🎯 [VERATUM BLAST-RADIUS] {}{}{}".format(
        report["target"], "" if report["exists"] else "  (new file)",
        "  · symbol `{}`".format(report["symbol_filter"]) if report.get("symbol_filter") else "")]
    if report.get("symbols"):
        lines.append("   Exports: " + ", ".join(report["symbols"][:15]) + (" …" if len(report["symbols"]) > 15 else ""))
    if report["direct"]:
        lines.append("   ⚠️  Direct dependents ({}):".format(len(report["direct"])))
        for d in report["direct"][:25]:
            used = (report.get("usage") or {}).get(d) or []
            lines.append("      - {}{}".format(d, "  uses: " + ", ".join(used[:6]) if used else ""))
        if len(report["direct"]) > 25:
            lines.append("      … +{} more".format(len(report["direct"]) - 25))
    else:
        lines.append("   ✅ Isolated change: 0 direct dependents detected.")
    for i, level in enumerate(report.get("transitive") or [], start=2):
        lines.append("   ↳ Depth {} ({}): {}".format(i, len(level), ", ".join(level[:10]) + (" …" if len(level) > 10 else "")))
    if report.get("co_changed"):
        lines.append("   🕘 Usually changes with (git history): " + ", ".join(
            "{} ({}/{})".format(c["file"], c["commits"], c["of"]) for c in report["co_changed"][:6]))
    if report.get("dynamic_refs"):
        lines.append("   🔎 Mentions without a static import (check for dynamic use): " + ", ".join(
            "{} [{}]".format(h["file"], h["symbol"]) for h in report["dynamic_refs"][:8]))
    if report["tests"]:
        lines.append("   🧪 Related tests to run: " + ", ".join(report["tests"][:12]))
    if report.get("edges") is not None:
        conf = report.get("confidence") or {}
        lines.append("   🧾 Evidence ({} EXTRACTED = import statement in source, {} INFERRED = name/history match):".format(
            conf.get(CONF_EXTRACTED, 0), conf.get(CONF_INFERRED, 0)))
        for e in report["edges"][:30]:
            ev = (e.get("evidence") or [{}])[0]
            if ev.get("line"):
                where = "{}:{}".format(ev.get("file", e["source"]), ev["line"])
                proof = "  | " + ev.get("text", "") if ev.get("text") else ""
            elif ev.get("commits"):
                where, proof = e["source"], "  | git log: {}/{} commits".format(ev["commits"], ev["of"])
            else:
                where, proof = e["source"], "  | " + ev["reason"] if ev.get("reason") else ""
            lines.append("      [{}] {} {} → {}{}".format(e["confidence"], where, e["relation"], e["target"], proof))
        if len(report["edges"]) > 30:
            lines.append("      … +{} more (use --json for all)".format(len(report["edges"]) - 30))
    lines.append("   Risk: {}".format(report["risk"]))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Scope enforcement
# ---------------------------------------------------------------------------

def _pattern_match(rel: str, pattern: str, root: Path) -> bool:
    rel_c = norm_case(rel)
    pat = norm_case(to_posix(pattern).strip())
    if pat.startswith("./"):
        pat = pat[2:]
    if not pat:
        return False
    if rel_c == pat.rstrip("/"):
        return True
    if pat.endswith("/") or (root / pattern).is_dir():
        return rel_c.startswith(pat.rstrip("/") + "/")
    if any(ch in pat for ch in "*?["):
        return fnmatch.fnmatchcase(rel_c, pat)
    return False


def normalize_scope_entry(ws: Workspace, entry: str) -> str | None:
    """Workspace-relative scope pattern; keeps globs verbatim and directory trailing slashes."""
    entry = to_posix(entry.strip())
    if any(ch in entry for ch in "*?["):
        return entry[2:] if entry.startswith("./") else entry
    rel = ws.rel(entry)
    if rel is None:
        return None
    if entry.endswith("/") and rel and not rel.endswith("/"):
        rel += "/"
    return rel


def in_scope(ws: Workspace, rel: str, contract: dict) -> bool:
    return any(_pattern_match(rel, pat, ws.root) for pat in contract.get("files", []))


def is_protected(ws: Workspace, rel: str) -> bool:
    return any(fnmatch.fnmatchcase(norm_case(rel), norm_case(p)) for p in ws.config().get("protected_paths", []))


def scope_decision(ws: Workspace, path: str) -> tuple:
    """Return (allowed: bool, message: str) for editing `path`."""
    rel = ws.rel(path)
    if rel is None:
        return True, "outside workspace — not governed by Veratum"
    if rel == VERATUM_DIRNAME or rel.startswith(VERATUM_DIRNAME + "/"):
        if is_protected(ws, rel):
            return False, ("{} is Veratum-managed evidence. Do not edit it directly — use the veratum_cli.py "
                           "commands (contract / verify / gate).".format(rel))
        return True, "Veratum internal file"
    cfg = ws.config()
    mode = cfg.get("enforcement", "strict")
    if mode == "off":
        return True, "enforcement disabled"
    if cfg.get("trivial_bypass") or os.environ.get("VERATUM_TRIVIAL") == "1":
        return True, "trivial bypass enabled"
    contract = ws.contract()
    if contract.get("status") != "ACTIVE":
        msg = ("No active Veratum contract. Lock scope first:\n"
               "  python3 .veratum/engine/veratum_cli.py contract --goal \"<goal>\" --files \"{}\" --verify \"<cmd>\"".format(rel))
        return (mode == "advisory"), msg
    if contract.get("mode") in ("plan", "review"):
        return False, ("[ACTION LOCK] Contract {} is in {} mode — no file changes. When the plan is approved: "
                       "python3 .veratum/engine/veratum_cli.py contract --mode implement".format(contract.get("id"), contract.get("mode")))
    if in_scope(ws, rel, contract):
        if mode == "strict" and needs_checkpoint(contract, contract_settings(ws, contract)):
            return False, ("Profile '{}' ({}) requires a shadow checkpoint before the first edit:\n"
                           "  python3 .veratum/engine/veratum_cli.py checkpoint create --label \"before {}\"".format(
                               contract.get("profile"), contract.get("profile_reason", ""), contract.get("goal", "")[:40]))
        return True, "in contract scope"
    msg = ("{} is OUTSIDE the active contract scope ({}).\n"
           "If this edit is required, extend the contract first:\n"
           "  python3 .veratum/engine/veratum_cli.py contract --extend \"{}\"".format(
               rel, ", ".join(contract.get("files", [])) or "none", rel))
    return (mode == "advisory"), msg


# ---------------------------------------------------------------------------
# Init
# ---------------------------------------------------------------------------

VERATUM_GITIGNORE = """# Veratum runtime state (machine-local). brain.json and config.json stay tracked.
logs/
ledger.json
contract.json
baseline.json
state.json
snapshots/
cache/
graph/
*.tmp-*
"""


def install_engine(ws: Workspace) -> list:
    """Copy this engine (and the sibling MCP server) into <root>/.veratum/engine/.

    Lets a skills.sh install (`.agents/skills/veratum/scripts/veratum_cli.py init`)
    bootstrap the canonical `.veratum/engine/` location every IDE config points to.
    """
    here = Path(__file__).resolve().parent
    if here == ws.engine_dir.resolve():
        return []
    ws.engine_dir.mkdir(parents=True, exist_ok=True)
    copied = []
    for refs in (here.parent / "references", here.parent / "skills" / "veratum" / "references"):
        if refs.is_dir():
            dest = ws.dir / "references"
            dest.mkdir(parents=True, exist_ok=True)
            for src in refs.glob("*.md"):
                dst = dest / src.name
                if not dst.exists() or dst.read_bytes() != src.read_bytes():
                    shutil.copyfile(str(src), str(dst))
                    copied.append(dst)
            break
    for name in ENGINE_FILES:
        src = here / name
        dst = ws.engine_dir / name
        if src.is_file():
            if not dst.exists() or dst.read_bytes() != src.read_bytes():
                shutil.copyfile(str(src), str(dst))
                copied.append(dst)
    return copied


def initialize(ws: Workspace, quiet: bool = False, rescan: bool = False) -> list:
    created = install_engine(ws)
    for d in (ws.dir, ws.logs_dir, ws.snapshots_dir):
        if not d.exists():
            d.mkdir(parents=True, exist_ok=True)
            created.append(d)
    gi = ws.dir / ".gitignore"
    if not gi.exists():
        gi.write_text(VERATUM_GITIGNORE, encoding="utf-8")
        created.append(gi)
    elif "graph/" not in gi.read_text(encoding="utf-8", errors="replace").splitlines():
        with open(gi, "a", encoding="utf-8", newline="\n") as fh:  # older installs: keep the generated graph out of git
            fh.write("graph/\n")
    if not ws.config_path.exists():
        ws.save_config(dict(DEFAULT_CONFIG))
        created.append(ws.config_path)
    brain = read_json(ws.brain_path, None)
    if brain is None or rescan:
        brain = brain or new_brain(ws.root)
        det = detect_stack(ws.root)
        brain["stack"] = det["stack"]
        brain["package_manager"] = det["package_manager"]
        for k, v in det["commands"].items():
            brain.setdefault("commands", {}).setdefault(k, v)
        mods = scan_modules(ws.root)
        brain["modules"] = mods["modules"]
        brain["entrypoints"] = mods["entrypoints"]
        if not ws.brain_path.exists():
            created.append(ws.brain_path)
        ws.save_brain(brain)
    if not ws.contract_path.exists():
        ws.save_contract({"schema": "veratum.contract/v1", "status": "NONE"})
        created.append(ws.contract_path)
    if not ws.ledger_path.exists():
        ws.save_ledger(new_ledger())
        created.append(ws.ledger_path)
    if not ws.state_path.exists():
        ws.save_state(ws.state())
        created.append(ws.state_path)
    if not quiet:
        print("✨ [{}] Initialized {} in {}".format(BRAND, VERATUM_DIRNAME, ws.root))
        for p in created:
            print("   + " + to_posix(os.path.relpath(str(p), str(ws.root))))
        b = ws.brain()
        print("   Stack: {}".format(", ".join(b.get("stack") or []) or "not detected"))
        for k, v in sorted((b.get("commands") or {}).items()):
            print("   {:<10} {}".format(k + ":", v))
    return created


# ---------------------------------------------------------------------------
# Adaptive risk profiles & modes
# ---------------------------------------------------------------------------

MODES = ("implement", "plan", "review")
PROFILES = {
    "eco":        {"impact_depth": 1, "max_retries": 2, "compact_max_lines": 25, "read_before_write": False, "require_checkpoint": False},
    "balanced":   {"impact_depth": 1, "max_retries": 2, "compact_max_lines": 40, "read_before_write": True,  "require_checkpoint": False},
    "deep":       {"impact_depth": 2, "max_retries": 2, "compact_max_lines": 60, "read_before_write": True,  "require_checkpoint": True},
    "highstakes": {"impact_depth": 2, "max_retries": 1, "compact_max_lines": 60, "read_before_write": True,  "require_checkpoint": True},
}
SENSITIVE_RE = re.compile(
    r"(auth|login|logout|session|token|jwt|oauth|saml|passw|credential|secret|crypt|permission|rbac|acl|"
    r"payment|billing|invoice|checkout|stripe|paypal|wallet|refund|migrat|schema\.(sql|prisma|rb)|\.sql$|"
    r"terraform|\.tf$|helm|k8s|kubernetes|deploy|dockerfile|docker-compose|\.github/workflows|nginx|"
    r"(^|/)prod|\.env)", re.I)


def assess_risk(files: list, impact: dict, trivial: bool = False) -> tuple:
    """Pick a verification profile from what the change touches (adaptive effort)."""
    sensitive = [f for f in files if SENSITIVE_RE.search(f)]
    deps = sorted({d for info in impact.values() for d in info.get("dependents", [])})
    if sensitive:
        return "highstakes", "sensitive paths: " + ", ".join(sensitive[:4])
    if len(deps) > 8 or len(files) > 6:
        return "deep", "{} dependents across {} contracted path(s)".format(len(deps), len(files))
    if trivial or (len(files) == 1 and not deps and not any(ch in files[0] for ch in "*?[") and not files[0].endswith("/")):
        return "eco", "single isolated file"
    return "balanced", "{} dependent(s), {} file(s)".format(len(deps), len(files))


def contract_settings(ws: Workspace, contract: dict | None = None) -> dict:
    """Effective limits: the active contract's profile, else the workspace config."""
    cfg = ws.config()
    base = {"impact_depth": 1, "max_retries": int(cfg.get("max_retries") or 2),
            "compact_max_lines": int(cfg.get("compact_max_lines") or 40),
            "read_before_write": bool(cfg.get("read_before_write", True)), "require_checkpoint": False}
    contract = contract if contract is not None else ws.contract()
    if contract.get("status") == "ACTIVE" and contract.get("profile") in PROFILES:
        base.update(PROFILES[contract["profile"]])
        if cfg.get("read_before_write") is False:
            base["read_before_write"] = False
    return base


def needs_checkpoint(contract: dict, settings: dict) -> bool:
    if not settings.get("require_checkpoint") or contract.get("checkpoints"):
        return False
    if contract.get("profile") == "highstakes":
        return True
    files = contract.get("files", [])
    return len(files) > 1 or any(f.endswith("/") or any(ch in f for ch in "*?[") for f in files)


# ---------------------------------------------------------------------------
# Shell command analysis (tokenizer + capability levels)
# ---------------------------------------------------------------------------

CAP_ORDER = ("read", "exec", "network", "write", "install", "destructive")
_SHELL_SEPARATORS = {"&&", "||", ";", "|", "&", "|&", ";;", "\n"}
_SHELL_REDIRECTS = {">", ">>", ">|", "&>", "&>>", "1>", "2>", "1>>", "2>>"}
_SHELL_WRAPPERS = {"sudo", "env", "time", "nohup", "nice", "command", "builtin", "exec", "timeout", "stdbuf", "xargs", "npx", "bunx", "pnpx"}
_READ_CMDS = {"cat", "less", "more", "head", "tail", "bat", "grep", "egrep", "fgrep", "rg", "ag", "ls", "dir", "tree", "find", "fd",
              "wc", "stat", "file", "du", "df", "pwd", "which", "where", "type", "echo", "printf", "sort", "uniq", "cut",
              "awk", "jq", "yq", "diff", "cmp", "basename", "dirname", "realpath", "readlink", "date", "whoami", "printenv",
              "true", "false", "test", "[", "cd", "pushd", "popd", "get-content", "get-childitem", "select-string", "sleep"}
_READ_FILE_CMDS = {"cat", "less", "more", "head", "tail", "bat", "get-content", "type"}
_NETWORK_CMDS = {"curl", "wget", "ssh", "scp", "sftp", "rsync", "nc", "telnet", "ftp", "invoke-webrequest", "iwr", "invoke-restmethod", "irm"}
_INLINE_INTERPRETERS = {"python": "-c", "python3": "-c", "py": "-c", "node": "-e", "perl": "-e", "ruby": "-e", "deno": "eval", "php": "-r"}
_NESTED_SHELLS = {"bash", "sh", "zsh", "dash", "fish", "cmd", "powershell", "pwsh"}
_GIT_READ = {"status", "diff", "log", "show", "blame", "rev-parse", "ls-files", "ls-tree", "describe", "shortlog", "reflog",
             "grep", "cat-file", "rev-list", "whatchanged", "check-ignore", "for-each-ref", "name-rev", "help", "version", "--version"}
_GIT_NETWORK = {"push", "fetch", "clone", "pull", "ls-remote", "submodule"}
_PKG_MANAGERS = {"npm", "pnpm", "yarn", "bun", "pip", "pip3", "uv", "poetry", "cargo", "go", "gem", "composer", "apt", "apt-get",
                 "brew", "choco", "winget", "conda", "dotnet"}
_PKG_INSTALL_SUBS = {"install", "i", "add", "remove", "rm", "uninstall", "un", "update", "upgrade", "up", "ci", "get", "sync", "lock"}
_MANIFEST_FOR = {"npm": ["package.json"], "pnpm": ["package.json"], "yarn": ["package.json"], "bun": ["package.json"],
                 "uv": ["pyproject.toml"], "poetry": ["pyproject.toml"], "cargo": ["Cargo.toml"], "go": ["go.mod"],
                 "composer": ["composer.json"], "dotnet": []}


def _tokenize_shell(command: str) -> list:
    import shlex
    text = command.replace("\\\n", " ")
    text = re.sub(r"(?<![\w$])\\(?=[\w.\-])", "/", text)  # Windows backslash paths → forward slashes
    try:
        lex = shlex.shlex(text, posix=True, punctuation_chars=";&|<>")
        lex.whitespace_split = True
        lex.whitespace = " \t\r"
        tokens = []
        for tok in lex:
            if "\n" in tok:
                parts = tok.split("\n")
                for i, part in enumerate(parts):
                    if part:
                        tokens.append(part)
                    if i < len(parts) - 1:
                        tokens.append("\n")
            else:
                tokens.append(tok)
        return tokens
    except ValueError:  # unbalanced quotes: fall back to whitespace split
        return re.findall(r"&&|\|\||[;|&<>]+|[^\s;|&<>]+|\n", text)


def _win_path(p: str) -> str:
    m = re.match(r"^/([a-zA-Z])/(.*)$", p)  # git-bash style /c/Users/...
    return "{}:/{}".format(m.group(1).upper(), m.group(2)) if m and os.name == "nt" else p


def analyze_shell(command: str, cwd: str = ".") -> dict:
    """Classify a shell command into capability levels and extract the files it reads/writes.

    Handles quoting, pipelines, `&&`/`||`/`;` chains, redirections, `cd` between segments,
    env-var prefixes, wrappers (sudo/env/npx/xargs…), nested `bash -c "…"` and git/package-manager
    subcommands. Unknown programs are `exec` (they may write; post-tool drift detection covers them).
    """
    tokens = _tokenize_shell(command or "")
    segments, current = [], []
    for tok in tokens:
        if tok in _SHELL_SEPARATORS:
            if current:
                segments.append(current)
            current = []
        else:
            current.append(tok)
    if current:
        segments.append(current)

    caps, writes, reads, inline, notes, seg_out = set(), [], [], [], [], []
    cur_dir = cwd

    def resolve(p: str) -> str:
        p = _win_path(p.strip())
        if not p or p in ("-", "/dev/null", "NUL", "nul") or p.startswith("/dev/") or re.match(r"^&?\d$", p):
            return ""
        if p.startswith("~"):
            p = os.path.expanduser(p)
        return to_posix(os.path.normpath(p if os.path.isabs(p) else os.path.join(cur_dir, p)))

    def add_write(p: str):
        r = resolve(p)
        if r and "$" not in p and r not in writes:
            writes.append(r)

    for seg in segments:
        seg_caps = set()
        argv = []
        i = 0
        while i < len(seg):  # pull out redirections
            tok = seg[i]
            if tok in _SHELL_REDIRECTS or (tok in (">", ">>") ):
                if i + 1 < len(seg):
                    target = seg[i + 1]
                    if not target.startswith("&"):
                        add_write(target)
                        seg_caps.add("write")
                i += 2
                continue
            if tok in ("<", "<<", "<<<"):
                if tok == "<" and i + 1 < len(seg):
                    r = resolve(seg[i + 1])
                    if r:
                        reads.append(r)
                i += 2
                continue
            if tok in (">&", "<&"):
                i += 2
                continue
            argv.append(tok)
            i += 1
        while argv and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", argv[0]):
            argv.pop(0)
        while argv and argv[0].lower() in _SHELL_WRAPPERS:
            argv.pop(0)
            while argv and argv[0].startswith("-"):
                argv.pop(0)
        if not argv:
            caps |= seg_caps
            continue
        prog = posixpath.basename(to_posix(argv[0])).lower()
        prog = re.sub(r"\.(exe|cmd|bat|ps1)$", "", prog)
        args = argv[1:]
        plain = [a for a in args if not a.startswith("-")]
        flags = [a for a in args if a.startswith("-")]

        if prog == "cd" and plain:
            cur_dir = resolve(plain[0]) or cur_dir
            seg_caps.add("read")
        elif prog in _NESTED_SHELLS and any(f.lower() in ("-c", "/c", "-command") for f in flags):
            idx = next(k for k, a in enumerate(args) if a.lower() in ("-c", "/c", "-command"))
            if idx + 1 < len(args):
                inner = analyze_shell(" ".join(args[idx + 1:]), cur_dir)
                seg_caps |= set(inner["caps"])
                writes.extend(w for w in inner["writes"] if w not in writes)
                reads.extend(inner["reads"])
                inline.extend(inner["inline_code"])
        elif prog in _INLINE_INTERPRETERS and _INLINE_INTERPRETERS[prog] in args:
            idx = args.index(_INLINE_INTERPRETERS[prog])
            code = args[idx + 1] if idx + 1 < len(args) else ""
            inline.append(code)
            seg_caps.add("exec")
            if re.search(r"open\([^)]*['\"][wa]\+?b?['\"]|write_text|write_bytes|writeFile|unlink|rmtree|os\.remove|fs\.rm", code):
                seg_caps.add("write")
                notes.append("inline {} code writes files".format(prog))
        elif prog in ("python", "python3", "py") and args[:2] in (["-m", "pip"], ["-m", "pip3"]):
            sub = next((a for a in args[2:] if not a.startswith("-")), "")
            seg_caps.add("install" if sub in _PKG_INSTALL_SUBS else "exec")
        elif prog == "git":
            sub = plain[0] if plain else ""
            rest = args[args.index(sub) + 1:] if sub in args else []
            rest_s = " ".join(rest)
            if sub in _GIT_READ or (sub == "branch" and not re.search(r"(^|\s)-(d|D|m|M|-delete|-move)\b", rest_s)) \
                    or (sub == "stash" and rest[:1] in (["list"], ["show"])) or (sub in ("tag", "remote", "config") and not rest):
                seg_caps.add("read")
            elif sub == "reset" and "--hard" in rest:
                seg_caps.add("destructive")
                notes.append("git reset --hard discards uncommitted work")
            elif sub == "clean" and re.search(r"-[a-zA-Z]*f", rest_s):
                seg_caps.add("destructive")
                notes.append("git clean -f deletes untracked files")
            elif sub in ("checkout", "restore") and (". " in rest_s + " " or rest_s.strip() in (".", "-- .", ":/")):
                seg_caps.add("destructive")
                notes.append("git {} . discards all local changes".format(sub))
            elif sub == "push" and re.search(r"(^|\s)(-f|--force(-with-lease)?|--mirror|--delete)\b|\s:\S", " " + rest_s):
                seg_caps |= {"destructive", "network"}
                notes.append("force/delete push rewrites remote history")
            elif sub == "branch" or (sub == "stash" and rest[:1] in (["drop"], ["clear"])) or sub in ("filter-branch", "filter-repo"):
                seg_caps.add("destructive")
                notes.append("git {} {} deletes refs/history".format(sub, rest_s).strip())
            elif sub in _GIT_NETWORK:
                seg_caps.add("network")
                if sub == "pull":
                    seg_caps.add("write")
            else:
                seg_caps.add("write")
                if sub in ("rm", "mv", "checkout", "restore") and len(plain) > 1:
                    for p in plain[1:]:
                        if p != "--":
                            add_write(p)
        elif prog in _PKG_MANAGERS:
            sub = plain[0] if plain else ""
            if prog in ("go",) and sub in ("test", "build", "vet", "run", "fmt"):
                seg_caps.add("exec")
            elif sub in _PKG_INSTALL_SUBS or (prog in ("pip", "pip3") and sub == "install"):
                seg_caps.add("install")
                pkgs = [p for p in plain[1:]]
                if pkgs and sub not in ("ci", "sync", "lock"):
                    for manifest in _MANIFEST_FOR.get(prog, []):
                        add_write(manifest)
            elif prog == "npm" and sub == "publish" or prog == "cargo" and sub == "publish":
                seg_caps |= {"network", "destructive"}
                notes.append("publishing a package is irreversible")
            else:
                seg_caps.add("exec")
        elif prog in _NETWORK_CMDS:
            seg_caps.add("network")
            for k, a in enumerate(args):
                if a in ("-o", "--output", "-O", "-OutFile") and k + 1 < len(args):
                    add_write(args[k + 1])
                    seg_caps.add("write")
        elif prog in ("sed", "perl") and any(f.startswith("-i") or f == "--in-place" or f.startswith("--in-place=") or (prog == "perl" and "i" in f.lstrip("-")) for f in flags):
            files = list(plain)
            if not any(f in ("-e", "-f", "--expression", "--file") for f in flags) and files:
                files = files[1:]
            for f in files:
                add_write(f)
            seg_caps.add("write")
        elif prog == "tee":
            for f in plain:
                add_write(f)
            seg_caps.add("write")
        elif prog in ("cp", "copy", "copy-item", "install", "ln", "rsync"):
            if plain:
                add_write(plain[-1])
            seg_caps.add("write")
        elif prog in ("mv", "move", "move-item", "rename", "ren"):
            for f in plain:
                add_write(f)
            seg_caps.add("write")
        elif prog in ("rm", "del", "erase", "unlink", "rmdir", "rd", "remove-item", "shred"):
            for f in plain:
                add_write(f)
            recursive = any(re.match(r"^-[a-zA-Z]*[rR]", f) or f.lower() in ("--recursive", "-recurse", "/s") for f in flags)
            seg_caps.add("destructive" if recursive or prog == "shred" else "write")
            if recursive:
                notes.append("recursive delete")
        elif prog in ("touch", "mkdir", "md", "new-item", "ni", "truncate", "chmod", "chown", "set-content", "add-content", "out-file"):
            skip_first = prog in ("chmod", "chown")
            targets = plain[1:] if skip_first else plain
            for k, a in enumerate(args):
                if a.lower() in ("-path", "-filepath", "-literalpath") and k + 1 < len(args):
                    targets = [args[k + 1]]
            for f in targets:
                add_write(f)
            seg_caps.add("write")
        elif prog == "dd":
            for a in args:
                if a.startswith("of="):
                    target = a[3:]
                    if target.startswith("/dev/"):
                        seg_caps.add("destructive")
                        notes.append("dd to a device")
                    else:
                        add_write(target)
            seg_caps.add("write")
        elif prog in ("mkfs", "fdisk", "format", "diskpart", "shutdown", "reboot", "kill", "killall", "pkill"):
            seg_caps.add("destructive")
            notes.append("{} is a system-level destructive command".format(prog))
        elif prog == "find":
            if "-delete" in args or ("-exec" in args and any(a in ("rm", "del", "shred") for a in args)):
                seg_caps.add("destructive")
                notes.append("find -delete / -exec rm")
            else:
                seg_caps.add("read")
        elif prog in _READ_CMDS:
            seg_caps.add("read")
            if prog in _READ_FILE_CMDS:
                for f in plain:
                    r = resolve(f)
                    if r:
                        reads.append(r)
        else:
            seg_caps.add("exec")
        caps |= seg_caps
        seg_out.append({"argv": argv, "caps": sorted(seg_caps, key=CAP_ORDER.index)})

    if not caps:
        caps.add("read")
    level = max(caps, key=CAP_ORDER.index)
    return {"level": level, "caps": sorted(caps, key=CAP_ORDER.index), "writes": writes, "reads": reads,
            "inline_code": inline, "notes": notes, "segments": seg_out}


def _ignored_paths(ws: Workspace, rels: list) -> set:
    if not rels:
        return set()
    if is_git_repo(ws.root):
        out = git(ws.root, ["check-ignore", "--stdin", "--no-index"], input_text="\n".join(rels) + "\n", check=False)
        return {to_posix(line.strip()) for line in out.splitlines() if line.strip()}
    return {r for r in rels if any(part in IGNORE_DIRS for part in r.split("/"))}


def shell_decision(ws: Workspace, command: str, cwd: str | None = None) -> tuple:
    """Decide whether a shell command may run BEFORE it executes. Returns (allowed, message, analysis)."""
    analysis = analyze_shell(command, cwd or str(ws.root))
    cfg = ws.config()
    contract = ws.contract()
    active = contract.get("status") == "ACTIVE"
    strict = cfg.get("enforcement", "strict") == "strict"
    level = analysis["level"]
    rels = []
    for w in analysis["writes"]:
        rel = ws.rel(w)
        if rel is not None:
            rels.append(rel)
    for rel in rels:
        if is_protected(ws, rel):
            return False, ("🛑 [VERATUM TAMPER GUARD] `{}` would write Veratum evidence ({}). "
                           "Use veratum_cli.py verify / gate / contract instead.".format(command, rel)), analysis
    if _TAMPER_RE.search(command) and "veratum_cli" not in command and level != "read":
        return False, "🛑 [VERATUM TAMPER GUARD] This command touches Veratum evidence files. Use the veratum_cli.py commands.", analysis
    if cfg.get("enforcement") == "off":
        return True, "", analysis
    if active and contract.get("mode") in ("plan", "review") and level in ("write", "install", "destructive"):
        return False, ("🛑 [VERATUM ACTION LOCK] Contract {} is in {} mode: commands that change files are blocked ({}). "
                       "Switch when ready: veratum_cli.py contract --mode implement".format(
                           contract.get("id"), contract.get("mode"), ", ".join(analysis["notes"]) or level)), analysis
    if "destructive" in analysis["caps"] and strict:
        state = ws.state()
        recent = [c for c in state.get("checkpoints", []) if _age_seconds(c.get("created_at")) < 1800]
        if not (active and contract.get("checkpoints")) and not recent:
            return False, ("🛑 [VERATUM SAFETY] Destructive command ({}). Create a shadow checkpoint first so it can be undone:\n"
                           "  python3 .veratum/engine/veratum_cli.py checkpoint create --label \"before: {}\"".format(
                               "; ".join(analysis["notes"]) or "destructive", command[:40])), analysis
    if strict and rels:
        candidates = [r for r in rels if r and not r.startswith(VERATUM_DIRNAME + "/")]
        ignored = _ignored_paths(ws, candidates)
        for rel in candidates:
            if rel in ignored:
                continue
            allowed, msg = scope_decision(ws, rel)
            if not allowed:
                return False, "🛑 [VERATUM SCOPE GUARD] Shell command would write {}.\n{}".format(rel, msg), analysis
            if active:
                ok, msg = read_guard(ws, rel, contract, host="shell")
                if not ok:
                    return False, msg, analysis
    return True, "", analysis


def _age_seconds(iso: str | None) -> float:
    if not iso:
        return float("inf")
    try:
        then = _dt.datetime.strptime(iso.replace("Z", "+0000"), "%Y-%m-%dT%H:%M:%S%z")
        return (_dt.datetime.now(_dt.timezone.utc) - then).total_seconds()
    except ValueError:
        return float("inf")


def render_shell(command: str, analysis: dict, allowed: bool, message: str) -> str:
    lines = ["🐚 [VERATUM SHELL ANALYSIS] level={}  caps={}".format(analysis["level"], ",".join(analysis["caps"]))]
    if analysis["writes"]:
        lines.append("   writes: " + ", ".join(analysis["writes"][:12]))
    if analysis["reads"]:
        lines.append("   reads:  " + ", ".join(analysis["reads"][:12]))
    if analysis["notes"]:
        lines.append("   notes:  " + "; ".join(analysis["notes"]))
    lines.append("   decision: " + ("ALLOW" if allowed else "DENY"))
    if message:
        lines.append(message)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Read-before-write & stale-read detection
# ---------------------------------------------------------------------------

READ_TOOLS = {"Read", "view_file", "read_file", "read", "view_code_item", "NotebookRead"}


def file_digest(path: Path) -> str | None:
    try:
        return _sha256_file(path) if path.is_file() else None
    except OSError:
        return None


def record_reads(ws: Workspace, rels: list) -> int:
    contract = ws.contract()
    if contract.get("status") != "ACTIVE":
        return 0
    reads = contract.setdefault("reads", {})
    n = 0
    for rel in rels:
        if rel and not rel.startswith(VERATUM_DIRNAME + "/"):
            digest = file_digest(ws.root / rel)
            if digest:
                reads[rel] = digest
                n += 1
    if n:
        contract.setdefault("read_hosts", [])
        ws.save_contract(contract)
    return n


def read_guard(ws: Workspace, rel: str, contract: dict, host: str) -> tuple:
    """Existing files must be read in this task before being modified, and not changed since that read."""
    settings = contract_settings(ws, contract)
    if not settings.get("read_before_write") or contract.get("status") != "ACTIVE":
        return True, ""
    if host not in ("claude", "antigravity", "shell") and not contract.get("reads"):
        return True, ""  # host never reports reads: cannot enforce honestly
    full = ws.root / rel
    current = file_digest(full)
    if current is None:
        return True, ""  # new file
    seen = (contract.get("reads") or {}).get(rel)
    if seen is None:
        return False, ("🛑 [VERATUM READ-BEFORE-WRITE] You have not read {} in this task. Read it first "
                       "(Read / view_file), then edit — never patch code you have not seen.".format(rel))
    if seen != current:
        return False, ("🛑 [VERATUM STALE READ] {} changed since you last read it (modified by another tool, a shell "
                       "command or a different process). Re-read it before editing so you do not overwrite that change.".format(rel))
    return True, ""


# ---------------------------------------------------------------------------
# Hash-chained evidence log
# ---------------------------------------------------------------------------

def _record_hash(prev: str, record: dict) -> str:
    body = {k: v for k, v in record.items() if k != "hash"}
    payload = prev + "\n" + json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _last_chain_hash(path: Path) -> str:
    try:
        with open(path, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            fh.seek(max(0, size - 65536))
            tail = fh.read().decode("utf-8", errors="replace").splitlines()
        for line in reversed(tail):
            line = line.strip()
            if line:
                try:
                    return json.loads(line).get("hash") or "GENESIS"
                except ValueError:
                    return "BROKEN"
    except OSError:
        pass
    return "GENESIS"


def audit_chain(ws: Workspace) -> dict:
    """Recompute every link of .veratum/logs/history.jsonl."""
    records, problems = [], []
    prev = None
    legacy = 0
    try:
        lines = ws.history_log.read_text(encoding="utf-8").splitlines()
    except OSError:
        lines = []
    for n, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            problems.append("line {}: not valid JSON".format(n))
            break
        if "hash" not in rec:
            if prev is None:
                legacy += 1
                continue
            problems.append("line {}: unchained record after the chain started".format(n))
            break
        expected_prev = prev if prev is not None else "GENESIS"
        if rec.get("prev") != expected_prev:
            problems.append("line {}: broken link (prev does not match the previous record)".format(n))
            break
        if _record_hash(rec["prev"], rec) != rec["hash"]:
            problems.append("line {}: record content was modified (hash mismatch)".format(n))
            break
        prev = rec["hash"]
        records.append(rec)
    return {"ok": not problems, "problems": problems, "records": records, "head": prev, "legacy": legacy}


# ---------------------------------------------------------------------------
# Contract
# ---------------------------------------------------------------------------

def lock_contract(ws: Workspace, goal: str, files: list, verify: str | None,
                  trivial: bool = False, run_impact: bool = True, mode: str = "implement",
                  profile: str = "auto") -> dict:
    ws.require_init()
    if not goal or not goal.strip():
        raise VeratumError("Contract requires --goal.")
    if mode not in MODES:
        raise VeratumError("Unknown mode '{}'. Use one of: {}".format(mode, ", ".join(MODES)))
    if profile != "auto" and profile not in PROFILES:
        raise VeratumError("Unknown profile '{}'. Use auto or one of: {}".format(profile, ", ".join(PROFILES)))
    norm_files = []
    for f in files:
        rel = normalize_scope_entry(ws, f)
        if rel is None:
            raise VeratumError("Contract file '{}' is outside the workspace {}.".format(f, ws.root))
        norm_files.append(rel)
    if not norm_files:
        raise VeratumError("Contract requires --files (comma separated paths or globs).")
    previous = ws.contract()
    brain = ws.brain()
    if previous.get("status") == "ACTIVE":
        previous["status"] = "SUPERSEDED"
        previous["closed_at"] = now_iso()
        _append_history(ws, {"event": "contract_superseded", "contract_id": previous.get("id")})
    if not verify:
        verify = (brain.get("commands") or {}).get("test")
    impact: dict = {}
    index = CodeIndex(ws) if run_impact else None

    def compute_impact(depth: int) -> dict:
        result = {}
        for f in norm_files:
            if any(ch in f for ch in "*?[") or (ws.root / f).is_dir():
                continue
            report = index.blast_radius(f, depth=depth)
            result[f] = {"dependents": report["all"], "tests": report["tests"], "risk": report["risk"],
                         "co_changed": [c["file"] for c in report.get("co_changed", [])][:5]}
        return result

    if index:
        impact = compute_impact(1)
    if profile == "auto":
        profile, reason = assess_risk(norm_files, impact, trivial)
    else:
        reason = "chosen explicitly"
    if index and PROFILES[profile]["impact_depth"] > 1:
        impact = compute_impact(PROFILES[profile]["impact_depth"])
    base = snapshot(ws)
    contract = {
        "schema": "veratum.contract/v1",
        "id": "c-" + _dt.datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:4],
        "status": "ACTIVE",
        "goal": goal.strip(),
        "files": norm_files,
        "verify": verify,
        "mode": mode,
        "profile": profile,
        "profile_reason": reason,
        "trivial": bool(trivial),
        "created_at": now_iso(),
        "impact": impact,
        "baseline_hash": tree_hash(base),
        "checkpoints": [],
        "touched": [],
        "reads": {},
    }
    write_json(ws.baseline_path, {"contract_id": contract["id"], "entries": base})
    ws.save_contract(contract)
    ledger = ws.ledger()
    history = ledger.get("history", [])
    ledger = new_ledger()
    ledger.update({"status": STATUS_IN_PROGRESS, "contract_id": contract["id"], "history": history[-20:]})
    ws.save_ledger(ledger)
    state = ws.state()
    state["stop_blocks"] = 0
    state["reported_drift"] = []
    ws.save_state(state)
    _append_history(ws, {"event": "contract_locked", "contract_id": contract["id"], "goal": contract["goal"]})
    return contract


def extend_contract(ws: Workspace, files: list) -> dict:
    contract = ws.contract()
    if contract.get("status") != "ACTIVE":
        raise VeratumError("No active contract to extend. Lock one with `contract --goal ... --files ...`.")
    added = []
    index = None
    for f in files:
        rel = normalize_scope_entry(ws, f)
        if rel is None:
            raise VeratumError("'{}' is outside the workspace.".format(f))
        if rel not in contract["files"]:
            contract["files"].append(rel)
            added.append(rel)
            if (ws.root / rel).is_file():
                index = index or CodeIndex(ws)
                report = index.blast_radius(rel, depth=1)
                contract.setdefault("impact", {})[rel] = {"dependents": report["all"], "tests": report["tests"], "risk": report["risk"]}
    contract.setdefault("amendments", []).append({"added": added, "at": now_iso()})
    ws.save_contract(contract)
    return {"contract": contract, "added": added}


def render_contract(contract: dict) -> str:
    if contract.get("status") in (None, "NONE"):
        return "📄 No contract has been locked yet."
    lines = ["📜 [VERATUM CONTRACT] {} — {}".format(contract.get("id"), contract.get("status")),
             "   Goal:    {}".format(contract.get("goal")),
             "   Mode:    {}   Profile: {} ({})".format(contract.get("mode", "implement"), contract.get("profile", "balanced"),
                                                       contract.get("profile_reason", "")),
             "   Scope:   {}".format(", ".join(contract.get("files", []))),
             "   Verify:  {}".format(contract.get("verify") or "(any passing command — set --verify to pin it)")]
    impact = contract.get("impact") or {}
    for f, info in impact.items():
        deps = info.get("dependents") or []
        lines.append("   Impact:  {} → {} dependent(s) [{}]{}".format(
            f, len(deps), info.get("risk"), (": " + ", ".join(deps[:6]) + (" …" if len(deps) > 6 else "")) if deps else ""))
        if info.get("tests"):
            lines.append("            tests: " + ", ".join(info["tests"][:6]))
        if info.get("co_changed"):
            lines.append("            usually changes with: " + ", ".join(info["co_changed"][:5]))
    profile = contract.get("profile")
    if contract.get("status") == "ACTIVE" and profile in PROFILES:
        rules = PROFILES[profile]
        notes = ["max {} retr{}".format(rules["max_retries"], "y" if rules["max_retries"] == 1 else "ies")]
        if rules["read_before_write"]:
            notes.append("read-before-write")
        if needs_checkpoint(contract, rules):
            notes.append("checkpoint REQUIRED before the first edit")
        if contract.get("mode") in ("plan", "review"):
            notes.append("ACTION LOCK: no file changes allowed")
        lines.append("   Rules:   " + ", ".join(notes))
    return "\n".join(lines)


def set_contract_mode(ws: Workspace, mode: str) -> dict:
    contract = ws.contract()
    if contract.get("status") != "ACTIVE":
        raise VeratumError("No active contract. Lock one with `contract --goal ... --files ... --mode {}`.".format(mode))
    if mode not in MODES:
        raise VeratumError("Unknown mode '{}'. Use one of: {}".format(mode, ", ".join(MODES)))
    old = contract.get("mode", "implement")
    contract["mode"] = mode
    contract.setdefault("amendments", []).append({"mode": [old, mode], "at": now_iso()})
    ws.save_contract(contract)
    _append_history(ws, {"event": "contract_mode", "contract_id": contract.get("id"), "from": old, "to": mode})
    return contract


# ---------------------------------------------------------------------------
# Smart context compaction
# ---------------------------------------------------------------------------

_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07]*\x07|\r")
_SIGNAL_RE = re.compile(
    r"(\berror\b|\berrors?:|\bfail(ed|ure|ing)?\b|\bFAIL\b|exception|traceback|assert|\bpanic|\bfatal\b|"
    r"segmentation fault|undefined reference|cannot find|not found|no such file|\bexpected\b|\breceived\b|"
    r"✕|✗|✘|×|\bE\s{2,}|\bERR!|warning: unused|error\[E\d+\]|\bTS\d{4}\b|did not match|mismatch|"
    r"\bdenied\b|\btimed? ?out\b|exit (code|status) [1-9])",
    re.I,
)
_LOCATION_RE = re.compile(
    r"(File \".+\", line \d+|\bat .+[:(]\d+(:\d+)?\)?|[\w./\\-]+\.(py|js|jsx|ts|tsx|mjs|go|rs|java|kt|c|cc|cpp|h|rb|php|cs|swift):\d+|"
    r"-->\s+\S+:\d+:\d+|\(\d+,\d+\): error|^\s+\^+\s*$)"
)
_NOISE_RE = re.compile(
    r"^\s*(PASS\b|ok\s|✓|√|✔|passed\b|\.+$|collecting|=+ test session starts|platform |rootdir:|plugins:|cachedir:|"
    r"Compiling |Downloading|Downloaded|Fetching|Resolving|npm (WARN|notice)|\[\d+/\d+\]|\s*\d+%|Progress)",
    re.I,
)
_SUMMARY_RE = re.compile(r"(\b\d+ (passed|failed|errors?|skipped|tests?)\b|\bTests?:|Test Suites:|Ran \d+ tests?|test result:|(?-i:^OK\b|FAILED|ERROR))", re.I)


def compact_output(raw: str, max_lines: int = 40, tail_lines: int = 8) -> dict:
    """Keep only failing tests, compiler errors, stack traces and the summary tail."""
    lines = [_ANSI_RE.sub("", ln).rstrip() for ln in raw.splitlines()]
    lines = [ln for ln in lines if ln.strip()]
    raw_chars = sum(len(ln) + 1 for ln in lines)
    if len(lines) <= max_lines:
        return {"text": "\n".join(lines), "raw_lines": len(lines), "kept_lines": len(lines),
                "raw_chars": raw_chars, "kept_chars": raw_chars, "saved_pct": 0}

    keep: list = []
    i = 0
    n = len(lines)
    while i < n:
        ln = lines[i]
        if ln.lstrip().startswith("Traceback (most recent call last)"):
            j = i
            block = []
            while j < n and len(block) < 14:
                block.append(j)
                j += 1
                if j < n and not lines[j].startswith((" ", "\t")) and not lines[j].lstrip().startswith("Traceback"):
                    block.append(j)  # the exception line itself
                    j += 1
                    break
            keep.extend(block)
            i = j
            continue
        signal = bool(_SIGNAL_RE.search(ln))
        location = bool(_LOCATION_RE.search(ln))
        if signal and not (_NOISE_RE.search(ln) and not re.search(r"error|fail", ln, re.I)):
            keep.append(i)
            for k in range(i + 1, min(n, i + 4)):
                if _LOCATION_RE.search(lines[k]) or lines[k].startswith(("    ", "\t")):
                    keep.append(k)
                else:
                    break
        elif location and not _NOISE_RE.search(ln):
            keep.append(i)
        i += 1

    tail_start = max(0, n - tail_lines)
    summary_idx = [k for k in range(max(0, n - 40), tail_start) if _SUMMARY_RE.search(lines[k])][-4:]
    body_budget = max_lines - tail_lines - 1
    ordered = []
    seen_text: dict = {}
    for k in sorted(set(keep)):
        if k >= tail_start:
            continue
        text = lines[k]
        if text in seen_text:
            seen_text[text] += 1
            continue
        seen_text[text] = 1
        ordered.append(k)
    ordered = ordered[:body_budget]
    for k in summary_idx:
        if len(ordered) < body_budget and k not in ordered:
            ordered.append(k)
    ordered.sort()
    body = []
    for k in ordered:
        text = lines[k]
        rep = seen_text.get(text, 1)
        body.append(text + ("   (×{})".format(rep) if rep > 1 else ""))
    stripped = n - len(body) - (n - tail_start)
    out = body + ["··· [veratum] {} noise line(s) stripped · full log: .veratum/logs/last_run.log ···".format(max(0, stripped))]
    out += lines[tail_start:]
    text = "\n".join(out)
    kept_chars = len(text)
    saved = int(round(100 * (1 - kept_chars / raw_chars))) if raw_chars else 0
    return {"text": text, "raw_lines": n, "kept_lines": len(out), "raw_chars": raw_chars,
            "kept_chars": kept_chars, "saved_pct": max(0, saved)}


# ---------------------------------------------------------------------------
# Verify
# ---------------------------------------------------------------------------

def _norm_cmd(cmd: str | None) -> str:
    return re.sub(r"\s+", " ", (cmd or "").strip())


def _append_history(ws: Workspace, record: dict) -> str | None:
    """Append a hash-chained event: hash = sha256(prev_hash + canonical JSON). Returns the new hash."""
    try:
        ws.logs_dir.mkdir(parents=True, exist_ok=True)
        record = dict(record)
        record.setdefault("at", now_iso())
        record["prev"] = _last_chain_hash(ws.history_log)
        record["hash"] = _record_hash(record["prev"], record)
        with open(ws.history_log, "a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
        return record["hash"]
    except OSError:
        return None


_SIG_NOISE_RE = re.compile(r"\b\d+(\.\d+)?\s*(ms|s|sec|seconds)\b|0x[0-9a-fA-F]+|\d{4}-\d\d-\d\dT[\d:.]+Z?|\bin \d+(\.\d+)?s\b")


def failure_signature(compact_text: str) -> str:
    """Stable fingerprint of WHAT failed (error lines + locations), ignoring timings and addresses."""
    keep = [_SIG_NOISE_RE.sub("", ln).strip() for ln in compact_text.splitlines()
            if (_SIGNAL_RE.search(ln) or _LOCATION_RE.search(ln)) and "[veratum]" not in ln]
    return hashlib.sha256("\n".join(keep).encode("utf-8")).hexdigest()[:16] if keep else ""


def run_verify(ws: Workspace, command: str | None, timeout: int | None = None, force: bool = False) -> dict:
    ws.require_init()
    contract = ws.contract()
    brain = ws.brain()
    cfg = ws.config()
    settings = contract_settings(ws, contract)
    command = (command or "").strip() or contract.get("verify") or (brain.get("commands") or {}).get("test")
    if not command:
        raise VeratumError("No verification command given and none known. Use `verify \"<cmd>\"` or "
                          "`brain set-cmd test \"<cmd>\"`.")
    prior = ws.ledger()
    same_contract_prior = prior.get("contract_id") == contract.get("id") and contract.get("status") == "ACTIVE"
    if not force and same_contract_prior and prior.get("status") == STATUS_FAILED \
            and _norm_cmd(prior.get("command")) == _norm_cmd(command):
        current = tree_hash(snapshot(ws))
        if current == prior.get("tree_hash"):
            return {"status": "DUPLICATE", "command": command, "exit_code": 3, "duration": 0.0, "tree_hash": current,
                    "compact": {"text": "", "raw_lines": 0, "kept_lines": 0, "saved_pct": 0},
                    "consecutive_failures": prior.get("consecutive_failures", 0),
                    "max_retries": settings["max_retries"], "raw": "", "same_failure": False}
    timeout = timeout or int(cfg.get("verify_timeout_sec") or 1800)
    env = dict(os.environ)
    env["VERATUM_VERIFY"] = "1"
    started = time.time()
    timed_out = False
    try:
        proc = subprocess.run(command, shell=True, cwd=str(ws.root), stdin=subprocess.DEVNULL,
                              stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env, timeout=timeout)
        raw = proc.stdout.decode("utf-8", errors="replace")
        code = proc.returncode
    except subprocess.TimeoutExpired as exc:
        raw = (exc.stdout or b"").decode("utf-8", errors="replace") + "\n[veratum] TIMEOUT after {}s".format(timeout)
        code = 124
        timed_out = True
    duration = round(time.time() - started, 2)

    ws.logs_dir.mkdir(parents=True, exist_ok=True)
    header = "# veratum verify | {} | exit {} | {}s\n# $ {}\n".format(now_iso(), code, duration, command)
    with open(ws.last_log, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(header + raw)

    entries = snapshot(ws)
    th = tree_hash(entries)
    write_json(ws.verified_snapshot, {"tree_hash": th, "entries": entries, "at": now_iso()})

    status = STATUS_PASSED if code == 0 else STATUS_FAILED
    ledger = ws.ledger()
    same_contract = ledger.get("contract_id") == contract.get("id")
    failures = (ledger.get("consecutive_failures", 0) if same_contract else 0)
    failures = 0 if status == STATUS_PASSED else failures + 1
    compact = compact_output(raw, max_lines=settings["compact_max_lines"])
    signature = failure_signature(compact["text"]) if status == STATUS_FAILED else ""
    same_failure = False
    if signature and same_contract:
        same_failure = any(h.get("signature") == signature and h.get("tree_hash") != th
                           for h in (ledger.get("history") or []) if h.get("status") == STATUS_FAILED)
    contract_id = contract.get("id") if contract.get("status") == "ACTIVE" else None
    evidence_hash = _append_history(ws, {"event": "verify", "status": status, "command": command, "exit_code": code,
                                         "tree_hash": th, "contract_id": contract_id, "signature": signature})
    record = {
        "status": status, "command": command, "exit_code": code, "duration_sec": duration,
        "timestamp": now_iso(), "tree_hash": th, "signature": signature, "evidence_hash": evidence_hash,
    }
    history = (ledger.get("history") or []) + [record]
    ledger.update(record)
    ledger.update({
        "schema": "veratum.ledger/v1",
        "contract_id": contract_id,
        "consecutive_failures": failures,
        "log_path": to_posix(os.path.relpath(str(ws.last_log), str(ws.root))),
        "log_lines": compact["raw_lines"],
        "compacted_lines": compact["kept_lines"],
        "timed_out": timed_out,
        "same_failure": same_failure,
        "history": history[-20:],
    })
    ledger.pop("stale_reason", None)
    ledger.pop("stale_at", None)
    ws.save_ledger(ledger)

    stats = brain.setdefault("stats", {})
    stats["verify_runs"] = stats.get("verify_runs", 0) + 1
    if status == STATUS_PASSED:
        stats["verify_passes"] = stats.get("verify_passes", 0) + 1
        kg = brain.setdefault("known_good_commands", {})
        entry = kg.setdefault(command, {"passes": 0})
        entry["passes"] += 1
        entry["last_pass"] = now_iso()
        if "test" not in (brain.get("commands") or {}) and re.search(r"test|spec|check", command, re.I):
            brain.setdefault("commands", {})["test"] = command
    stats["log_lines_saved"] = stats.get("log_lines_saved", 0) + max(0, compact["raw_lines"] - compact["kept_lines"])
    ws.save_brain(brain)
    state = ws.state()
    state["stop_blocks"] = 0
    ws.save_state(state)
    return {"status": status, "command": command, "exit_code": code, "duration": duration,
            "tree_hash": th, "compact": compact, "consecutive_failures": failures,
            "max_retries": settings["max_retries"], "raw": raw, "same_failure": same_failure}


def render_verify(result: dict) -> str:
    c = result["compact"]
    if result["status"] == "DUPLICATE":
        return ("🔁 [VERATUM DUPLICATE-FAILURE GUARD] `{}` already FAILED on this exact code (tree sha256:{}).\n"
                "   Re-running it unchanged cannot produce new information. Change the code (fix the root cause) first,\n"
                "   or if you suspect a flaky test, re-run once with `verify --force` and say so in your evidence.\n"
                "   Last trace: .veratum/logs/last_run.log").format(result["command"], short_hash(result["tree_hash"]))
    if result["status"] == STATUS_PASSED:
        lines = ["✅ [VERATUM VERIFIED] `{}` → EXIT 0 in {}s".format(result["command"], result["duration"]),
                 "   Proof locked: tree sha256:{} → .veratum/ledger.json".format(short_hash(result["tree_hash"]))]
        if c["raw_lines"] > 6:
            tail = c["text"].splitlines()[-3:]
            lines.append("   Summary: " + " | ".join(t.strip() for t in tail))
        lines.append("   Any edit from now on invalidates this proof. Next: run `gate`.")
        return "\n".join(lines)
    lines = ["❌ [VERATUM FAILED] `{}` → EXIT {} in {}s (attempt {} of {})".format(
        result["command"], result["exit_code"], result["duration"], result["consecutive_failures"], result["max_retries"]),
        "──── COMPACTED ERROR TRACE ({} → {} lines, ~{}% tokens saved) ────".format(c["raw_lines"], c["kept_lines"], c["saved_pct"]),
        c["text"],
        "────────────────────────────────────────────────────────────"]
    if result.get("same_failure"):
        lines.append("♻️  SAME FAILURE as an earlier attempt, although the code changed: your last edit did not touch the cause.")
        lines.append("   Stop patching symptoms. Re-read the trace from the first failing frame and state the root cause before editing again.")
    if result["consecutive_failures"] >= result["max_retries"]:
        lines.append("🧯 Retry budget exhausted ({} consecutive failures). Do NOT keep patching blindly:".format(result["consecutive_failures"]))
        lines.append("   • python3 .veratum/engine/veratum_cli.py rollback      (restore last checkpoint)")
        lines.append("   • or escalate to the user with the trace above as evidence.")
    else:
        lines.append("Fix the ROOT CAUSE shown above, then re-run verify.")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Completion gate
# ---------------------------------------------------------------------------

def evaluate_gate(ws: Workspace) -> dict:
    ws.require_init()
    contract = ws.contract()
    ledger = ws.ledger()
    cfg = ws.config()
    problems: list = []
    fixes: list = []
    current_entries = snapshot(ws)
    current_hash = tree_hash(current_entries)
    baseline = read_json(ws.baseline_path, {}) or {}
    changed: list = []
    drift: list = []

    if contract.get("status") != "ACTIVE":
        problems.append("No active contract in .veratum/contract.json (status: {}).".format(contract.get("status", "NONE")))
        fixes.append('python3 .veratum/engine/veratum_cli.py contract --goal "<goal>" --files "<files>" --verify "<cmd>"')
    else:
        if baseline.get("contract_id") == contract.get("id"):
            changed = diff_entries(baseline.get("entries") or {}, current_entries)
            drift = [p for p in changed if not in_scope(ws, p, contract)]
        if contract.get("mode") in ("plan", "review"):
            if changed:
                problems.append("{} mode is read-only, but files changed: {}".format(
                    contract.get("mode").upper(), ", ".join(changed[:10])))
                fixes.append("python3 .veratum/engine/veratum_cli.py rollback   (or `contract --mode implement` and verify)")
            return {"passed": not problems, "problems": problems, "fixes": fixes, "contract": contract, "ledger": ledger,
                    "current_hash": current_hash, "changed": changed, "drift": [], "chain": None}
        if ledger.get("status") != STATUS_PASSED:
            if ledger.get("status") == STATUS_STALE:
                problems.append("Ledger is STALE: {}".format(ledger.get("stale_reason") or "files changed after verification."))
            elif ledger.get("status") == STATUS_FAILED:
                problems.append("Last verification FAILED (exit {}): `{}`.".format(ledger.get("exit_code"), ledger.get("command")))
            else:
                problems.append("No passing verification recorded (ledger status: {}).".format(ledger.get("status")))
            fixes.append('python3 .veratum/engine/veratum_cli.py verify "{}"'.format(contract.get("verify") or "<test cmd>"))
        else:
            if ledger.get("contract_id") != contract.get("id"):
                problems.append("The passing verification belongs to a different contract ({}).".format(ledger.get("contract_id")))
                fixes.append('python3 .veratum/engine/veratum_cli.py verify "{}"'.format(contract.get("verify") or "<test cmd>"))
            if contract.get("verify") and _norm_cmd(ledger.get("command")) != _norm_cmd(contract.get("verify")):
                problems.append("Verified command `{}` is not the contracted verification `{}`.".format(
                    ledger.get("command"), contract.get("verify")))
                fixes.append('python3 .veratum/engine/veratum_cli.py verify "{}"'.format(contract.get("verify")))
            if ledger.get("tree_hash") != current_hash:
                verified = read_json(ws.verified_snapshot, {}) or {}
                after = []
                if verified.get("tree_hash") == ledger.get("tree_hash"):
                    after = diff_entries(verified.get("entries") or {}, current_entries)
                problems.append("POST-VERIFICATION EDIT DETECTED: working tree sha256:{} ≠ verified sha256:{}{}".format(
                    short_hash(current_hash), short_hash(ledger.get("tree_hash")),
                    (" — changed after verify: " + ", ".join(after[:8]) + (" …" if len(after) > 8 else "")) if after else ""))
                fixes.append('python3 .veratum/engine/veratum_cli.py verify "{}"'.format(contract.get("verify") or ledger.get("command")))
            chain_problem = _chain_binding_problem(ws, ledger)
            if chain_problem:
                problems.append("EVIDENCE INTEGRITY: " + chain_problem)
                fixes.append('python3 .veratum/engine/veratum_cli.py verify "{}"   (re-create honest evidence)'.format(
                    contract.get("verify") or ledger.get("command")))
        if drift and cfg.get("enforcement", "strict") == "strict":
            problems.append("SCOPE DRIFT: files changed outside the contract: " + ", ".join(drift[:10]) + (" …" if len(drift) > 10 else ""))
            fixes.append('python3 .veratum/engine/veratum_cli.py contract --extend "{}"   (if intentional) or revert them'.format(",".join(drift[:10])))
    return {"passed": not problems, "problems": problems, "fixes": list(dict.fromkeys(fixes)),
            "contract": contract, "ledger": ledger, "current_hash": current_hash,
            "changed": changed, "drift": drift}


def _chain_binding_problem(ws: Workspace, ledger: dict) -> str:
    """The PASSED ledger must be backed by an intact, hash-chained `verify` record with identical facts."""
    audit = audit_chain(ws)
    if not audit["ok"]:
        return "evidence log was modified ({}).".format("; ".join(audit["problems"]))
    ref = ledger.get("evidence_hash")
    if not ref:
        return "ledger has no evidence_hash (written by hand or by an old engine)."
    match = next((r for r in audit["records"] if r.get("hash") == ref), None)
    if match is None:
        return "ledger points to evidence {} that is not in the hash chain.".format(short_hash(ref, 12))
    for key in ("tree_hash", "command", "exit_code", "status", "contract_id"):
        if match.get(key) != ledger.get(key):
            return "ledger field `{}` does not match the chained evidence record.".format(key)
    return ""


def close_contract(ws: Workspace, result: dict) -> None:
    contract = result["contract"]
    ledger = result["ledger"]
    contract["status"] = "COMPLETED"
    contract["completed_at"] = now_iso()
    contract["evidence"] = {"command": ledger.get("command"), "exit_code": ledger.get("exit_code"),
                            "tree_hash": result["current_hash"], "changed": result["changed"]}
    ws.save_contract(contract)
    ledger["completed_at"] = contract["completed_at"]
    ws.save_ledger(ledger)
    brain = ws.brain()
    brain.setdefault("task_history", []).append({
        "contract_id": contract.get("id"), "goal": contract.get("goal"), "files_changed": result["changed"][:50],
        "verify": ledger.get("command"), "tree_hash": result["current_hash"], "completed_at": contract["completed_at"],
    })
    brain["task_history"] = brain["task_history"][-50:]
    stats = brain.setdefault("stats", {})
    stats["tasks_completed"] = stats.get("tasks_completed", 0) + 1
    ws.save_brain(brain)
    state = ws.state()
    state["stop_blocks"] = 0
    ws.save_state(state)
    _append_history(ws, {"event": "gate_passed", "contract_id": contract.get("id"), "tree_hash": result["current_hash"]})
    try:
        gm = _graph_module()
        task_data = {
            "id": contract.get("id"),
            "contract_id": contract.get("id"),
            "goal": contract.get("goal"),
            "query": contract.get("goal"),
            "completed_at": contract["completed_at"],
            "files_changed": result["changed"],
            "files": result["changed"] or contract.get("files", []),
            "verify": ledger.get("command"),
            "tree_hash": result["current_hash"],
            "status": "COMPLETED",
        }
        gm.record_task_history(ws, task_data)
        if hasattr(gm, "graph_update_task"):
            gm.graph_update_task(ws, task_data, files_changed=result.get("changed", []))
        else:
            gm.graph_build(ws)
    except Exception:
        pass


def render_gate(result: dict) -> str:
    if not result["passed"]:
        lines = ["🛑 [VERATUM COMPLETION GATE BLOCKED]"]
        lines.extend("   ✗ " + p for p in result["problems"])
        lines.append("   Required action:")
        lines.extend("   → " + f for f in result["fixes"])
        lines.append("   You may NOT declare this task done until `gate` passes.")
        return "\n".join(lines)
    c, l = result["contract"], result["ledger"]
    impact = c.get("impact") or {}
    deps = sorted({d for info in impact.values() for d in info.get("dependents", [])})
    changed = result["changed"]
    if c.get("mode") in ("plan", "review"):
        return "\n".join([
            "✅ [VERATUM COMPLETION GATE PASSED — {} MODE]".format(c.get("mode").upper()),
            "━━━━━━━━━━━━━━━━ VERATUM EVIDENCE BLOCK ━━━━━━━━━━━━━━━━",
            "Goal:            {}".format(c.get("goal")),
            "Contract:        {}".format(c.get("id")),
            "Changed:         nothing (read-only verified: tree sha256:{} == baseline)".format(short_hash(result["current_hash"], 24)),
            "Impact mapped:   {}".format(", ".join(deps[:12]) if deps else "isolated (0 dependents)"),
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        ])
    lines = [
        "✅ [VERATUM COMPLETION GATE PASSED]",
        "━━━━━━━━━━━━━━━━ VERATUM EVIDENCE BLOCK ━━━━━━━━━━━━━━━━",
        "Engine:          Veratum v{}".format(VERSION),
        "Goal:            {}".format(c.get("goal")),
        "Contract:        {}".format(c.get("id")),
        "Changed ({}):     {}".format(len(changed), ", ".join(changed[:15]) + (" …" if len(changed) > 15 else "") if changed else "(no file changes)"),
        "Scope:           ✓ all changes inside contract" if not result["drift"] else "Scope:           ⚠ drift (advisory): " + ", ".join(result["drift"][:8]),
        "Impact checked:  {}".format(", ".join(deps[:12]) + (" …" if len(deps) > 12 else "") if deps else "isolated (0 dependents)"),
        "Verified by:     `{}` → EXIT {} ({}s) @ {}".format(l.get("command"), l.get("exit_code"), l.get("duration_sec"), l.get("timestamp")),
        "Tree hash:       sha256:{} (matches verified state)".format(short_hash(result["current_hash"], 24)),
        "Evidence chain:  ✓ intact · record {} · profile {}".format(short_hash(l.get("evidence_hash"), 12), c.get("profile", "balanced")),
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "Memory commit: save new learnings → python3 .veratum/engine/veratum_cli.py remember \"<insight>\"",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Shadow checkpoints
# ---------------------------------------------------------------------------

def _require_git(ws: Workspace) -> None:
    if not is_git_repo(ws.root):
        raise VeratumError("Shadow checkpoints require a git repository. Run `git init` in {} first.".format(ws.root), 2)


def checkpoint_create(ws: Workspace, label: str = "") -> dict:
    ws.require_init()
    _require_git(ws)
    root = ws.root
    real_index = Path(git(root, ["rev-parse", "--path-format=absolute", "--git-path", "index"], check=False).strip() or "")
    fd, tmp_index = tempfile.mkstemp(prefix="veratum-index-")
    os.close(fd)
    try:
        if real_index and real_index.is_file():
            shutil.copyfile(str(real_index), tmp_index)
        else:
            os.unlink(tmp_index)
        env = {"GIT_INDEX_FILE": tmp_index}
        git(root, ["add", "-A"], env=env)
        tree = git(root, ["write-tree"], env=env).strip()
    finally:
        if os.path.exists(tmp_index):
            os.unlink(tmp_index)
    head = git(root, ["rev-parse", "-q", "--verify", "HEAD"], check=False).strip()
    cid = "cp-" + _dt.datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid.uuid4().hex[:4]
    message = "veratum checkpoint {}{}".format(cid, (": " + label) if label else "")
    args = ["commit-tree", tree, "-m", message] + (["-p", head] if head else [])
    commit = git(root, args).strip()
    ref = "refs/veratum/checkpoints/" + cid
    git(root, ["update-ref", ref, commit])
    contract = ws.contract()
    record = {"id": cid, "ref": ref, "commit": commit, "tree": tree, "label": label,
              "created_at": now_iso(), "contract_id": contract.get("id")}
    state = ws.state()
    state.setdefault("checkpoints", []).append(record)
    state["checkpoints"] = state["checkpoints"][-30:]
    ws.save_state(state)
    if contract.get("status") == "ACTIVE":
        contract.setdefault("checkpoints", []).append(cid)
        ws.save_contract(contract)
    _append_history(ws, {"event": "checkpoint", "id": cid, "commit": commit})
    return record


def checkpoint_rollback(ws: Workspace, cid: str | None = None) -> dict:
    ws.require_init()
    _require_git(ws)
    root = ws.root
    state = ws.state()
    checkpoints = [c for c in state.get("checkpoints", []) if not c.get("label", "").startswith("auto: pre-rollback")]
    if cid:
        matches = [c for c in state.get("checkpoints", []) if c["id"] == cid or c["commit"].startswith(cid)]
        if not matches:
            raise VeratumError("Checkpoint '{}' not found. See `checkpoint list`.".format(cid))
        target = matches[-1]
    else:
        if not checkpoints:
            raise VeratumError("No checkpoints exist. Create one with `checkpoint create` before risky edits.")
        contract = ws.contract()
        mine = [c for c in checkpoints if c.get("contract_id") == contract.get("id")]
        target = (mine or checkpoints)[-1]
    safety = checkpoint_create(ws, label="auto: pre-rollback safety ({})".format(target["id"]))
    commit = target["commit"]
    git(root, ["restore", "--source=" + commit, "--worktree", "--", ".", ":(exclude).veratum"])
    in_checkpoint = set(_zsplit(git(root, ["ls-tree", "-r", "--name-only", "-z", commit])))
    removed = []
    for path in _zsplit(git(root, ["ls-files", "-o", "--exclude-standard", "-z"])):
        if _excluded(path, []) or path in in_checkpoint:
            continue
        full = root / path
        if full.is_file():
            full.unlink()
            removed.append(path)
    ledger = ws.ledger()
    ledger["status"] = STATUS_STALE if ledger.get("status") == STATUS_PASSED else ledger.get("status", STATUS_IN_PROGRESS)
    if ledger["status"] == STATUS_FAILED:
        ledger["status"] = STATUS_IN_PROGRESS
    ledger["consecutive_failures"] = 0
    ledger["stale_reason"] = "workspace rolled back to {}".format(target["id"])
    ws.save_ledger(ledger)
    _append_history(ws, {"event": "rollback", "to": target["id"], "safety": safety["id"], "removed": removed})
    return {"target": target, "safety": safety, "removed": removed}


# ---------------------------------------------------------------------------
# Status & doctor
# ---------------------------------------------------------------------------

def compute_status(ws: Workspace) -> dict:
    ws.require_init()
    contract, ledger = ws.contract(), ws.ledger()
    entries = snapshot(ws)
    current = tree_hash(entries)
    baseline = read_json(ws.baseline_path, {}) or {}
    changed = []
    if contract.get("status") == "ACTIVE" and baseline.get("contract_id") == contract.get("id"):
        changed = diff_entries(baseline.get("entries") or {}, entries)
    fresh = ledger.get("status") == STATUS_PASSED and ledger.get("tree_hash") == current
    return {"contract": contract, "ledger": ledger, "current_hash": current, "changed": changed,
            "drift": [p for p in changed if contract.get("status") == "ACTIVE" and not in_scope(ws, p, contract)],
            "evidence_fresh": fresh}


def render_status(st: dict) -> str:
    c, l = st["contract"], st["ledger"]
    lines = ["🧠 [VERATUM STATUS]"]
    if c.get("status") == "ACTIVE":
        lines.append("   Contract: {} — {}".format(c.get("id"), c.get("goal")))
        lines.append("   Scope:    {}".format(", ".join(c.get("files", []))))
    else:
        lines.append("   Contract: none active (last: {})".format(c.get("status", "NONE")))
    lines.append("   Ledger:   {}{}".format(l.get("status"), "  (`{}` exit {})".format(l.get("command"), l.get("exit_code")) if l.get("command") else ""))
    lines.append("   Evidence: {}".format("FRESH ✓ (tree matches verified hash)" if st["evidence_fresh"] else "not fresh — verify required before gate"))
    if st["changed"]:
        lines.append("   Changed since contract ({}): {}".format(len(st["changed"]), ", ".join(st["changed"][:12])))
    if st["drift"]:
        lines.append("   ⚠ Out-of-scope changes: " + ", ".join(st["drift"][:10]))
    lines.append("   Tree:     sha256:{}".format(short_hash(st["current_hash"])))
    return "\n".join(lines)


ADAPTER_FILES = {
    "antigravity": [".agents/skills/veratum/SKILL.md", ".agents/plugins/veratum/plugin.json",
                    ".agents/plugins/veratum/hooks.json", ".agents/plugins/veratum/hooks/_veratum_bridge.py",
                    ".agents/plugins/veratum/hooks/pre_edit.py", ".agents/plugins/veratum/hooks/post_edit.py",
                    ".agents/plugins/veratum/hooks/completion_gate.py"],
    "claude-code": ["CLAUDE.md", ".claude/settings.json"],
    "cursor": [".cursor/rules/veratum.mdc", ".cursor/mcp.json", ".cursor/hooks.json"],
    "windsurf": [".windsurfrules"],
    "cline": [".clinerules"],
    "copilot": [".github/copilot-instructions.md", ".vscode/mcp.json"],
    "opencode": ["AGENTS.md", "opencode.json", ".opencode/plugin/veratum.js"],
}


def _mcp_selftest(server: Path, root: Path) -> tuple:
    msgs = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize",
         "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "veratum-doctor", "version": VERSION}}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    ]
    payload = "".join(json.dumps(m) + "\n" for m in msgs)
    try:
        proc = subprocess.run([sys.executable, str(server), "--root", str(root)], input=payload.encode("utf-8"),
                              capture_output=True, timeout=20)
        replies = [json.loads(line) for line in proc.stdout.decode("utf-8").splitlines() if line.strip()]
        tools = next((r["result"]["tools"] for r in replies if r.get("id") == 2 and "result" in r), [])
        return bool(tools), "{} tools exposed over stdio".format(len(tools))
    except Exception as exc:  # pragma: no cover - diagnostic path
        return False, "self-test failed: {}".format(exc)


def run_doctor(ws: Workspace) -> dict:
    checks: list = []

    def add(name: str, ok: bool, detail: str, required: bool = True):
        checks.append({"name": name, "ok": bool(ok), "detail": detail, "required": required})

    add("Python >= 3.8", sys.version_info >= (3, 8), "{} ({})".format(platform.python_version(), sys.executable))
    git_ok = git_available()
    add("Git available", git_ok, (git(ws.root, ["--version"], check=False).strip() if git_ok else "git not on PATH"))
    add("Git repository", is_git_repo(ws.root), "required for checkpoints; non-git fallback hashing otherwise", required=False)
    add(".veratum/ directory", ws.dir.is_dir(), str(ws.dir))
    for label, path in (("brain.json", ws.brain_path), ("contract.json", ws.contract_path),
                        ("ledger.json", ws.ledger_path), ("config.json", ws.config_path)):
        data = read_json(path, None)
        add(label + " valid", isinstance(data, dict) and (str(data.get("schema", "")).startswith("veratum.")),
            "ok" if isinstance(data, dict) else "missing or invalid JSON")
    add("logs/ directory", ws.logs_dir.is_dir(), to_posix(os.path.relpath(str(ws.logs_dir), str(ws.root))))
    engine_mcp = ws.engine_dir / "mcp_server.py"
    missing = [n for n in ENGINE_FILES if not (ws.engine_dir / n).is_file()]
    add("Engine installed (.veratum/engine)", not missing,
        " + ".join(ENGINE_FILES) if not missing else "missing {}: run `npx github:yadavmandeep/Veratum update`".format(", ".join(missing)))
    if engine_mcp.is_file():
        ok, detail = _mcp_selftest(engine_mcp, ws.root)
        add("MCP server self-test", ok, detail)
    try:
        snap = snapshot(ws)
        add("Tree fingerprint", True, "{} files hashed → sha256:{}".format(len(snap), short_hash(tree_hash(snap))))
    except Exception as exc:
        add("Tree fingerprint", False, str(exc))
    cfg = ws.config()
    installed = cfg.get("installed_adapters") or []
    for name, files in ADAPTER_FILES.items():
        present = [f for f in files if (ws.root / f).exists()]
        required = name in installed
        add("Adapter: " + name, len(present) == len(files),
            "{}/{} files{}".format(len(present), len(files), "" if len(present) == len(files) else " (missing: " + ", ".join(f for f in files if f not in present) + ")"),
            required=required)
    settings = read_json(ws.root / ".claude" / "settings.json", {}) or {}
    wired = [ev for ev, entries in (settings.get("hooks") or {}).items() if "veratum_cli.py" in json.dumps(entries)]
    add("Claude Code hooks wired", {"PreToolUse", "PostToolUse", "Stop"}.issubset(set(wired)),
        ", ".join(sorted(wired)) or "none", required="claude-code" in installed)
    required = [c for c in checks if c["required"]]
    passed = [c for c in required if c["ok"]]
    score = int(round(100 * len(passed) / len(required))) if required else 100
    return {"checks": checks, "score": score, "passed": len(passed), "required": len(required)}


def render_doctor(rep: dict) -> str:
    lines = ["🩺 [VERATUM DOCTOR] v{} · {}".format(VERSION, HOMEPAGE)]
    for c in rep["checks"]:
        icon = "✅" if c["ok"] else ("❌" if c["required"] else "➖")
        lines.append("  {} {:<36} {}".format(icon, c["name"], c["detail"]))
    lines.append("Health: {}% ({}/{} required checks passed)".format(rep["score"], rep["passed"], rep["required"]))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Host hooks (Claude Code / Antigravity / Cursor)
# ---------------------------------------------------------------------------

WRITE_TOOLS = {
    "Edit", "Write", "MultiEdit", "NotebookEdit",                       # Claude Code
    "write_to_file", "replace_file_content", "multi_replace_file_content",  # Antigravity
    "edit_file", "write_file", "create_file", "edit", "write", "patch",     # aliases / OpenCode
}
SHELL_TOOLS = {"Bash", "run_command", "bash", "shell", "run_terminal_cmd"}
# File-search tools of the hosts that let a hook add context before/after a search (see graph_hint).
SEARCH_TOOLS = {"Grep", "Glob", "grep", "glob", "grep_search", "find_by_name", "codebase_search", "search_files"}
GRAPH_HINT_MAX = 2  # reminders per task before the hint stays quiet
GRAPH_HINT = ("[VERATUM] A code graph of this project exists. Before searching raw files, try "
              "`graph query \"<what you are looking for>\"` (chat shortcut: /veratum <question>): it returns the relevant "
              "files and symbols with file:line. Overview: .veratum/graph/GRAPH_REPORT.md")


def _graph_hint_key(ws: Workspace) -> str:
    contract = ws.contract()
    return str(contract.get("id")) if contract.get("status") == "ACTIVE" else _dt.date.today().isoformat()


def graph_hint(ws: Workspace) -> str:
    """Reminder to use the graph before raw search: only when a graph exists, graph_auto is not off, the agent has not
    queried the graph in this task, and fewer than GRAPH_HINT_MAX reminders were shown (a task = the active contract,
    or the calendar day without one)."""
    if str(ws.config().get("graph_auto", "auto")) == "off" or not (ws.dir / "graph" / "graph.json").is_file():
        return ""
    key = _graph_hint_key(ws)
    state = ws.state()
    hint = state.get("graph_hint") or {}
    if hint.get("key") != key:
        hint = {"key": key, "shown": 0, "used": False}
    if hint.get("used") or hint.get("shown", 0) >= GRAPH_HINT_MAX:
        return ""
    hint["shown"] = hint.get("shown", 0) + 1
    state["graph_hint"] = hint
    ws.save_state(state)
    return GRAPH_HINT


def graph_hint_used(ws: Workspace) -> None:
    """Called when the agent queries the graph: no more reminders for this task."""
    state = ws.state()
    hint = state.get("graph_hint") or {}
    if hint.get("key") != _graph_hint_key(ws):
        hint = {"key": _graph_hint_key(ws), "shown": 0}
    hint["used"] = True
    state["graph_hint"] = hint
    ws.save_state(state)


def _emit_hint(host: str, message: str) -> int:
    """Allow the tool call and hand the model a note. Claude Code reads `additionalContext`; Antigravity and the OpenCode
    plugin read `reason`; Cursor has no channel for it, so nothing is added there."""
    if host == "claude":
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "additionalContext": message}}))
    elif host == "antigravity":
        print(json.dumps({"decision": "allow", "reason": message}))
    elif host == "cursor":
        print(json.dumps({"permission": "allow"}))
    return 0


PATH_KEYS = ("file_path", "notebook_path", "TargetFile", "target_file", "filePath", "path", "AbsolutePath")
_TAMPER_RE = re.compile(r"\.veratum[\\/]+(ledger|contract|baseline|state)\.json|\.veratum[\\/]+snapshots", re.I)


def _parse_hook_payload(raw: str) -> dict:
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except ValueError:
        payload = {}
    return payload if isinstance(payload, dict) else {}


def _detect_host(payload: dict, requested: str) -> str:
    if requested and requested != "auto":
        return requested
    if "toolCall" in payload or "workspacePaths" in payload or "conversationId" in payload:
        return "antigravity"
    if "hook_event_name" in payload or "session_id" in payload:
        return "claude"
    if "workspace_roots" in payload or "cursor_version" in payload:
        return "cursor"
    return "claude"


def _normalize_tool(payload: dict) -> tuple:
    call = payload.get("toolCall")
    if isinstance(call, dict):
        name, args = call.get("name") or "", call.get("args") or {}
    else:
        name = payload.get("tool_name") or payload.get("tool") or ""
        args = payload.get("tool_input") or payload.get("args") or {}
    if not isinstance(args, dict):
        args = {}
    paths = []
    for key in PATH_KEYS:
        val = args.get(key) or (payload.get(key) if key in ("file_path",) else None)
        if isinstance(val, str) and val:
            paths.append(val)
            break
    for edit in args.get("edits") or []:
        if isinstance(edit, dict) and isinstance(edit.get("file_path"), str):
            paths.append(edit["file_path"])
    command = args.get("command") or args.get("CommandLine") or payload.get("command") or ""
    if not name and payload.get("file_path"):
        name = "edit_file"
    if not name and command:
        name = "run_command"
    return name, list(dict.fromkeys(paths)), command if isinstance(command, str) else ""


def _hook_root(payload: dict, fallback: Path) -> Path:
    for key in ("workspacePaths", "workspace_paths", "workspace_roots"):
        vals = payload.get(key)
        if isinstance(vals, list):
            for v in vals:
                if isinstance(v, str) and (Path(v) / VERATUM_DIRNAME).is_dir():
                    return Path(v).resolve()
    cwd = payload.get("cwd")
    if isinstance(cwd, str) and cwd:
        p = Path(cwd).resolve()
        for cand in [p] + list(p.parents):
            if (cand / VERATUM_DIRNAME).is_dir():
                return cand
    env_dir = os.environ.get("CLAUDE_PROJECT_DIR")
    if env_dir and (Path(env_dir) / VERATUM_DIRNAME).is_dir():
        return Path(env_dir).resolve()
    return fallback


def _emit(host: str, event: str, allow: bool, message: str = "") -> int:
    """Translate a decision into the host's hook protocol. Returns exit code."""
    if host == "antigravity":
        if event == "stop":
            print(json.dumps({"decision": "allow"} if allow else {"decision": "continue", "reason": message}))
        else:
            print(json.dumps({"decision": "allow"} if allow else {"decision": "deny", "reason": message}))
        return 0
    if host == "cursor":
        if event == "stop":
            print(json.dumps({} if allow else {"followup_message": message}))
        elif event == "pre-tool":
            print(json.dumps({"permission": "allow"} if allow else
                             {"permission": "deny", "userMessage": message.splitlines()[0] if message else "Blocked by Veratum", "agentMessage": message}))
        else:
            print(json.dumps({}))
        return 0
    # Claude Code: exit 2 + stderr blocks the tool / the stop and feeds the reason to the model.
    if allow:
        if message:
            print(message)
        return 0
    sys.stderr.write(message.rstrip() + "\n")
    return 2


def run_hook(event: str, host: str, fallback_root: Path, raw: str) -> int:
    payload = _parse_hook_payload(raw)
    host = _detect_host(payload, host)
    event = {"pre-edit": "pre-tool", "post-edit": "post-tool", "completion-gate": "stop"}.get(event, event)
    ws = Workspace(_hook_root(payload, fallback_root))
    if not ws.dir.is_dir():
        return _emit(host, event, True)  # Veratum not installed in this workspace: never interfere.
    try:
        if event == "session-start":
            try:
                _graph_module().graph_auto_refresh(ws)
            except VeratumError:
                pass
            try:
                check_auto_update(ws)
            except Exception:
                pass
            print(brain_context(ws))
            return 0
        if event == "read":
            return _hook_read(ws, host, payload)
        if event == "pre-tool":
            return _hook_pre_tool(ws, host, payload)
        if event == "post-tool":
            return _hook_post_tool(ws, host, payload)
        if event == "stop":
            return _hook_stop(ws, host, payload)
    except VeratumError as exc:
        return _emit(host, event, event != "pre-tool", "[VERATUM] hook error: {}".format(exc))
    raise VeratumError("Unknown hook event '{}'. Use pre-tool | post-tool | read | stop | session-start.".format(event))


def _hook_cwd(ws: Workspace, payload: dict) -> str:
    cwd = payload.get("cwd")
    return cwd if isinstance(cwd, str) and cwd and os.path.isdir(cwd) else str(ws.root)


def _hook_read(ws: Workspace, host: str, payload: dict) -> int:
    """Hosts with a dedicated read hook (Cursor beforeReadFile): record the read, never block it."""
    _, paths, _ = _normalize_tool(payload)
    record_reads(ws, [r for r in (ws.rel(p) for p in paths) if r])
    if host == "cursor":
        print(json.dumps({"permission": "allow"}))
        return 0
    return _emit(host, "post-tool", True)


def _hook_pre_tool(ws: Workspace, host: str, payload: dict) -> int:
    name, paths, command = _normalize_tool(payload)
    if name in READ_TOOLS:
        return _emit(host, "pre-tool", True)
    if name in SEARCH_TOOLS:
        hint = graph_hint(ws)
        return _emit_hint(host, hint) if hint else _emit(host, "pre-tool", True)
    if name in WRITE_TOOLS or (host == "cursor" and paths and not command):
        contract = ws.contract()
        for p in paths:
            allowed, msg = scope_decision(ws, p)
            if not allowed:
                return _emit(host, "pre-tool", False, "🛑 [VERATUM SCOPE GUARD] " + msg)
            rel = ws.rel(p)
            if rel is not None and not rel.startswith(VERATUM_DIRNAME + "/"):
                ok, msg = read_guard(ws, rel, contract, host)
                if not ok:
                    return _emit(host, "pre-tool", False, msg)
        return _emit(host, "pre-tool", True)
    if name in SHELL_TOOLS or command:
        allowed, msg, _ = shell_decision(ws, command, _hook_cwd(ws, payload))
        if not allowed:
            return _emit(host, "pre-tool", False, msg)
    return _emit(host, "pre-tool", True)


def _hook_post_tool(ws: Workspace, host: str, payload: dict) -> int:
    name, paths, command = _normalize_tool(payload)
    if name in READ_TOOLS:
        record_reads(ws, [r for r in (ws.rel(p) for p in paths) if r])
        return _emit(host, "post-tool", True)
    is_write = name in WRITE_TOOLS or (host == "cursor" and bool(paths))
    is_shell = name in SHELL_TOOLS or bool(command)
    if not (is_write or is_shell):
        return _emit(host, "post-tool", True)
    contract = ws.contract()
    if contract.get("status") != "ACTIVE":
        return _emit(host, "post-tool", True)
    messages = []
    if is_write and paths:
        touched = contract.setdefault("touched", [])
        reads = contract.setdefault("reads", {})
        for p in paths:
            rel = ws.rel(p)
            if rel and not rel.startswith(VERATUM_DIRNAME + "/"):
                if rel not in touched:
                    touched.append(rel)
                digest = file_digest(ws.root / rel)
                if digest:
                    reads[rel] = digest  # the agent knows what it just wrote: its view is fresh
        ws.save_contract(contract)
    if is_shell:
        shell_reads = analyze_shell(command, _hook_cwd(ws, payload))["reads"]
        record_reads(ws, [r for r in (ws.rel(p) for p in shell_reads) if r])
    ledger = ws.ledger()
    entries = None
    if ledger.get("status") == STATUS_PASSED:
        entries = snapshot(ws)
        if tree_hash(entries) != ledger.get("tree_hash"):
            verified = read_json(ws.verified_snapshot, {}) or {}
            after = diff_entries(verified.get("entries") or {}, entries) if verified.get("tree_hash") == ledger.get("tree_hash") else []
            ledger["status"] = STATUS_STALE
            ledger["stale_at"] = now_iso()
            ledger["stale_reason"] = "modified after verification: " + (", ".join(after[:8]) if after else "working tree changed")
            ws.save_ledger(ledger)
            messages.append("⚠️ [VERATUM] Verification evidence invalidated ({}). Re-run verify before completing.".format(ledger["stale_reason"]))
    if is_shell and ws.config().get("enforcement") == "strict":
        baseline = read_json(ws.baseline_path, {}) or {}
        if baseline.get("contract_id") == contract.get("id"):
            entries = entries if entries is not None else snapshot(ws)
            drift = [p for p in diff_entries(baseline.get("entries") or {}, entries) if not in_scope(ws, p, contract)]
            state = ws.state()
            new = [p for p in drift if p not in state.get("reported_drift", [])]
            if new:
                state["reported_drift"] = sorted(set(state.get("reported_drift", [])) | set(new))
                ws.save_state(state)
                messages.append("⚠️ [VERATUM SCOPE DRIFT] Shell command changed files outside the contract: {}. "
                                "Revert them or run `contract --extend \"{}\"`. The completion gate will block otherwise.".format(
                                    ", ".join(new[:8]), ",".join(new[:8])))
    if messages and host == "claude":
        sys.stderr.write("\n".join(messages) + "\n")
        return 2
    if host == "antigravity":
        print(json.dumps({"decision": "allow", "reason": "\n".join(messages)} if messages else {"decision": "allow"}))
        return 0
    if host == "cursor":
        print(json.dumps({}))
        return 0
    return 0


def _hook_stop(ws: Workspace, host: str, payload: dict) -> int:
    contract = ws.contract()
    if contract.get("status") != "ACTIVE":
        return _emit(host, "stop", True)
    result = evaluate_gate(ws)
    if contract.get("mode") in ("plan", "review"):
        # Read-only contracts stay open across turns (plan → approval → implement); only block if files changed.
        return _emit(host, "stop", result["passed"], "" if result["passed"] else render_gate(result))
    if not result["changed"] and ws.ledger().get("status") != STATUS_FAILED and not result["passed"]:
        # Contract locked but nothing modified yet (e.g. a planning/Q&A turn): nothing to gate.
        return _emit(host, "stop", True)
    state = ws.state()
    if result["passed"]:
        close_contract(ws, result)
        return _emit(host, "stop", True, render_gate(result) if host == "claude" else "")
    limit = int(ws.config().get("stop_gate_max_blocks") or 0)
    state["stop_blocks"] = int(state.get("stop_blocks", 0)) + 1
    ws.save_state(state)
    if limit and state["stop_blocks"] > limit:
        _append_history(ws, {"event": "gate_circuit_breaker", "contract_id": contract.get("id"), "problems": result["problems"]})
        ledger = ws.ledger()
        ledger["gate_overridden"] = {"at": now_iso(), "problems": result["problems"]}
        ws.save_ledger(ledger)
        state["stop_blocks"] = 0
        ws.save_state(state)
        return _emit(host, "stop", True,
                     "⚠️ [VERATUM] Completion gate circuit breaker tripped after {} blocks. Stop allowed, but the task is "
                     "recorded as UNVERIFIED in .veratum/ledger.json. Tell the user it is NOT verified.".format(limit))
    return _emit(host, "stop", False, render_gate(result))


# ---------------------------------------------------------------------------
# `config` command: a few safe settings without hand-editing .veratum/config.json
# ---------------------------------------------------------------------------

# Only convenience settings are settable here. Anything that loosens enforcement (enforcement, trivial_bypass,
# read_before_write, protected_paths, ...) stays a deliberate manual edit of config.json, so an agent cannot switch the
# guards off by running a command.
CONFIG_SETTABLE = {
    "graph_auto": ("choice", ("auto", "refresh", "off"),
                   "auto = build the code graph at session start and keep it fresh; refresh = only refresh an existing graph; off = never"),
    "compact_max_lines": ("int", (5, 500), "lines kept when a failing verify log is compacted"),
    "verify_timeout_sec": ("int", (10, 86400), "seconds before `verify` gives up"),
}


def config_show(ws: Workspace) -> str:
    cfg = ws.config()
    lines = ["⚙️  [VERATUM CONFIG] .veratum/config.json (change with: python .veratum/engine/veratum_cli.py config <name> <value>)"]
    for key, (_, allowed, hint) in CONFIG_SETTABLE.items():
        shown = "|".join(allowed) if isinstance(allowed[0], str) else "{}-{}".format(*allowed)
        lines.append("   {:<20} = {:<9} {}  [{}]".format(key, cfg.get(key), hint, shown))
    lines.append("   Other keys (enforcement, protected_paths, ...) are edited by hand in .veratum/config.json on purpose.")
    return "\n".join(lines)


def config_set(ws: Workspace, key: str, raw: str) -> tuple:
    if key not in CONFIG_SETTABLE:
        if key in DEFAULT_CONFIG:
            raise VeratumError("'{}' cannot be changed from the command line (it affects enforcement). "
                               "Edit .veratum/config.json yourself if you really mean it.".format(key))
        raise VeratumError("Unknown setting '{}'. Settable: {}.".format(key, ", ".join(CONFIG_SETTABLE)))
    kind, allowed, _ = CONFIG_SETTABLE[key]
    value = raw.strip().lower()
    if kind == "choice":
        value = {"on": "auto", "true": "auto", "no": "off", "false": "off"}.get(value, value)
        if value not in allowed:
            raise VeratumError("{} must be one of: {} (got '{}').".format(key, ", ".join(allowed), raw))
    else:
        try:
            value = int(value)
        except ValueError:
            raise VeratumError("{} must be a number (got '{}').".format(key, raw))
        if not allowed[0] <= value <= allowed[1]:
            raise VeratumError("{} must be between {} and {}.".format(key, allowed[0], allowed[1]))
    stored = read_json(ws.config_path, {}) or {}
    before = ws.config().get(key)
    stored[key] = value
    ws.save_config(stored)
    return before, value


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="veratum", description="{} engine v{} — {}".format(BRAND, VERSION, HOMEPAGE))
    p.add_argument("--root", help="Workspace root (default: auto-detect)")
    p.add_argument("--version", action="version", version="veratum " + VERSION)
    sub = p.add_subparsers(dest="cmd")

    s = sub.add_parser("init", help="Create .veratum/ and detect the project stack")
    s.add_argument("--rescan", action="store_true", help="Re-detect stack and module map")

    s = sub.add_parser("brain", help="Persistent cross-session memory")
    bs = s.add_subparsers(dest="brain_cmd")
    b = bs.add_parser("show"); b.add_argument("--json", action="store_true")
    b = bs.add_parser("remember"); b.add_argument("text", nargs="+"); b.add_argument("--kind", default="insight", choices=INSIGHT_KINDS); b.add_argument("--files")
    b = bs.add_parser("set-cmd"); b.add_argument("type"); b.add_argument("command", nargs="+")
    b = bs.add_parser("forget"); b.add_argument("id")
    bs.add_parser("scan")
    bs.add_parser("context")

    s = sub.add_parser("remember", help="Shortcut: brain remember")
    s.add_argument("text", nargs="+"); s.add_argument("--kind", default="insight", choices=INSIGHT_KINDS); s.add_argument("--files")

    s = sub.add_parser("contract", help="Lock / show / extend the task contract")
    s.add_argument("--goal")
    s.add_argument("--files", action="append", help="Comma separated paths or globs (repeatable)")
    s.add_argument("--verify", help="Verification command that must pass")
    s.add_argument("--trivial", action="store_true", help="Mark as a trivial one-file fix")
    s.add_argument("--no-impact", action="store_true", help="Skip blast-radius analysis")
    s.add_argument("--extend", action="append", help="Add files to the active contract")
    s.add_argument("--show", action="store_true")
    s.add_argument("--abandon", action="store_true")
    s.add_argument("--mode", choices=list(MODES), help="implement (default) | plan | review (read-only action lock)")
    s.add_argument("--profile", default="auto", help="auto (risk-adaptive, default) | eco | balanced | deep | highstakes")
    s.add_argument("--json", action="store_true")

    s = sub.add_parser("check-scope", help="Exit 0 if a path may be edited")
    s.add_argument("path")

    s = sub.add_parser("impact", help="Blast-radius analysis")
    s.add_argument("paths", nargs="+")
    s.add_argument("--depth", type=int, default=1)
    s.add_argument("--symbol", help="Only dependents that use this exported symbol")
    s.add_argument("--evidence", action="store_true", help="Show file:line proof and EXTRACTED/INFERRED confidence per relationship (always included with --json)")
    s.add_argument("--json", action="store_true")

    s = sub.add_parser("graph", help="Knowledge graph: build/query/path/explain/report/benchmark/status")
    s.add_argument("action", choices=["build", "query", "path", "explain", "report", "benchmark", "status",
                                      "export", "watch", "semantic", "history"])
    s.add_argument("text", nargs="*", help="question (query/benchmark), two node names (path), node name (explain), "
                                           "list|add [file.json] (semantic)")
    s.add_argument("--format", choices=["html", "svg", "obsidian", "cypher", "all"], default="all", help="export format")
    s.add_argument("--out", help="export directory inside the workspace (default .veratum/graph/export)")
    s.add_argument("--max-nodes", type=int, default=400, help="export: most-connected nodes to draw (html/svg)")
    s.add_argument("--interval", type=float, default=2.0, help="watch: seconds between checks")
    s.add_argument("--debounce", type=float, default=3.0, help="watch: quiet seconds before rebuilding")
    s.add_argument("--cycles", type=int, help="watch: stop after N checks (default: run until Ctrl-C)")
    s.add_argument("--data", help="semantic add: JSON text instead of a file")
    s.add_argument("--full", action="store_true", help="build: ignore the per-file cache")
    s.add_argument("--max-files", type=int, default=0, help="build: stop after N files (default 0 = every file)")
    s.add_argument("--max-file-kb", type=int, default=5120, help="build: skip source files larger than this (generated/minified code); 0 = no limit")
    s.add_argument("--mode", choices=["bfs", "dfs"], default="bfs")
    s.add_argument("--depth", type=int, default=2)
    s.add_argument("--budget", type=int, default=2000, help="query: approximate token budget")
    s.add_argument("--json", action="store_true")

    s = sub.add_parser("checkpoint", help="Shadow git checkpoints")
    s.add_argument("action", nargs="?", default="create", choices=["create", "rollback", "list"])
    s.add_argument("id", nargs="?")
    s.add_argument("--label", default="")

    s = sub.add_parser("rollback", help="Shortcut: checkpoint rollback")
    s.add_argument("id", nargs="?")

    s = sub.add_parser("verify", help="Run validation with compaction + hash binding")
    s.add_argument("--timeout", type=int)
    s.add_argument("--force", action="store_true", help="Re-run even if the same command already failed on identical code")
    s.add_argument("--json", action="store_true")
    s.add_argument("command", nargs=argparse.REMAINDER)

    s = sub.add_parser("explain-shell", help="Show how the shell guard classifies a command")
    s.add_argument("command", nargs=argparse.REMAINDER)
    s.add_argument("--json", action="store_true")

    s = sub.add_parser("audit", help="Verify the hash-chained evidence log")
    s.add_argument("--json", action="store_true")

    s = sub.add_parser("gate", help="Hard completion gate")
    s.add_argument("--dry-run", action="store_true", help="Evaluate without closing the contract")
    s.add_argument("--json", action="store_true")

    s = sub.add_parser("config", help="Show or change a setting, e.g. `config graph_auto off`")
    s.add_argument("name", nargs="?", help="setting name (omit to list)")
    s.add_argument("value", nargs="?", help="new value (omit to read the current one)")

    s = sub.add_parser("status"); s.add_argument("--json", action="store_true")
    s = sub.add_parser("doctor"); s.add_argument("--json", action="store_true")

    s = sub.add_parser("hook", help="IDE hook entry point (reads JSON on stdin)")
    s.add_argument("event", choices=["pre-tool", "post-tool", "read", "stop", "session-start", "pre-edit", "post-edit", "completion-gate"])
    s.add_argument("--host", default="auto", choices=["auto", "claude", "antigravity", "cursor"])
    return p


def _print_json(data) -> None:
    print(json.dumps(data, indent=2, ensure_ascii=False))


def main(argv=None) -> int:
    _utf8_stdio()
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.cmd:
        parser.print_help()
        return 1
    root = find_root(args.root)
    ws = Workspace(root)
    try:
        return _dispatch(ws, args)
    except VeratumError as exc:
        print("❌ [VERATUM] {}".format(exc), file=sys.stderr)
        return exc.code


def _dispatch(ws: Workspace, args) -> int:
    cmd = args.cmd
    if cmd == "init":
        initialize(ws, rescan=args.rescan)
        return 0

    if cmd == "hook":
        raw = sys.stdin.buffer.read().decode("utf-8", errors="replace") if not sys.stdin.isatty() else ""
        return run_hook(args.event, args.host, ws.root, raw)

    if cmd == "doctor":
        rep = run_doctor(ws)
        _print_json(rep) if args.json else print(render_doctor(rep))
        return 0 if rep["score"] == 100 else 1

    ws.require_init()

    if cmd in ("brain", "remember"):
        action = "remember" if cmd == "remember" else (args.brain_cmd or "show")
        if action == "show":
            brain = ws.brain()
            if getattr(args, "json", False):
                _print_json(brain)
            else:
                print(brain_context(ws, max_insights=50))
            return 0
        if action == "remember":
            item = brain_remember(ws, " ".join(args.text), kind=args.kind, files=args.files)
            print("🧠 [VERATUM BRAIN] Remembered [{}|{}]: {}".format(item["id"], item["kind"], item["text"]))
            return 0
        if action == "set-cmd":
            brain = ws.brain()
            brain.setdefault("commands", {})[args.type] = " ".join(args.command)
            ws.save_brain(brain)
            print("🧠 [VERATUM BRAIN] {} command → `{}`".format(args.type, brain["commands"][args.type]))
            return 0
        if action == "forget":
            brain = ws.brain()
            before = len(brain.get("insights", []))
            brain["insights"] = [i for i in brain.get("insights", []) if i.get("id") != args.id]
            if len(brain["insights"]) == before:
                raise VeratumError("No memory with id '{}'.".format(args.id))
            ws.save_brain(brain)
            print("🧠 [VERATUM BRAIN] Forgot {}".format(args.id))
            return 0
        if action == "scan":
            initialize(ws, quiet=True, rescan=True)
            print(brain_context(ws))
            return 0
        if action == "context":
            print(brain_context(ws))
            return 0

    if cmd == "contract":
        if args.abandon:
            c = ws.contract()
            if c.get("status") == "ACTIVE":
                c["status"] = "ABANDONED"
                c["closed_at"] = now_iso()
                ws.save_contract(c)
                print("📜 [VERATUM] Contract {} abandoned.".format(c.get("id")))
            else:
                print("📜 [VERATUM] No active contract.")
            return 0
        if args.extend:
            res = extend_contract(ws, split_csv(args.extend))
            print("📜 [VERATUM] Scope extended: +{}".format(", ".join(res["added"]) or "(already in scope)"))
            print(render_contract(res["contract"]))
            return 0
        if args.mode and not args.goal:
            c = set_contract_mode(ws, args.mode)
            print("📜 [VERATUM] Contract {} switched to {} mode.".format(c.get("id"), args.mode))
            print(render_contract(c))
            return 0
        if args.show or not args.goal:
            c = ws.contract()
            _print_json(c) if args.json else print(render_contract(c))
            return 0 if args.show or c.get("status") == "ACTIVE" else 1
        contract = lock_contract(ws, args.goal, split_csv(args.files), args.verify,
                                 trivial=args.trivial, run_impact=not args.no_impact,
                                 mode=args.mode or "implement", profile=args.profile)
        if args.json:
            _print_json(contract)
        else:
            print("🔒 [VERATUM CONTRACT LOCKED] Ledger reset → IN_PROGRESS")
            print(render_contract(contract))
            print("   Next: `checkpoint create` for multi-file/risky edits, then edit ONLY the files above.")
        return 0

    if cmd == "check-scope":
        allowed, msg = scope_decision(ws, args.path)
        if allowed:
            print("✅ [VERATUM SCOPE] {} — {}".format(args.path, msg))
            return 0
        print("🛑 [VERATUM SCOPE GUARD] " + msg, file=sys.stderr)
        return 1

    if cmd == "impact":
        index = CodeIndex(ws)
        reports = []
        for path in args.paths:
            rel = ws.rel(path)
            if rel is None:
                raise VeratumError("'{}' is outside the workspace.".format(path))
            reports.append(index.blast_radius(rel, depth=max(1, args.depth), symbol=args.symbol,
                                              evidence=args.evidence or args.json))
        if args.json:
            _print_json(reports if len(reports) > 1 else reports[0])
        else:
            print("\n".join(render_impact(r) for r in reports))
        return 0

    if cmd == "graph":
        return _graph_module().run_command(ws, args)

    if cmd in ("checkpoint", "rollback"):
        action = "rollback" if cmd == "rollback" else args.action
        if action == "create":
            rec = checkpoint_create(ws, label=args.label)
            print("📸 [VERATUM CHECKPOINT] {} → {} (incl. untracked files, worktree untouched)".format(rec["id"], short_hash(rec["commit"], 12)))
            print("   Restore with: python3 .veratum/engine/veratum_cli.py rollback {}".format(rec["id"]))
            return 0
        if action == "list":
            cps = ws.state().get("checkpoints", [])
            if not cps:
                print("📸 No checkpoints yet.")
            for c in cps:
                print("📸 {}  {}  {}  {}".format(c["id"], short_hash(c["commit"], 10), c["created_at"], c.get("label", "")))
            return 0
        res = checkpoint_rollback(ws, args.id)
        print("⏪ [VERATUM ROLLBACK] Workspace restored to {} ({})".format(res["target"]["id"], short_hash(res["target"]["commit"], 10)))
        if res["removed"]:
            print("   Removed files created after the checkpoint: " + ", ".join(res["removed"][:12]))
        print("   Safety snapshot of the pre-rollback state: {} (undo with `rollback {}`)".format(res["safety"]["id"], res["safety"]["id"]))
        print("   Ledger needs a fresh `verify`.")
        return 0

    if cmd == "verify":
        command = " ".join(args.command).strip()
        result = run_verify(ws, command or None, timeout=args.timeout, force=args.force)
        if args.json:
            out = {k: v for k, v in result.items() if k != "raw"}
            _print_json(out)
        else:
            print(render_verify(result))
        return 0 if result["status"] == STATUS_PASSED else (result["exit_code"] or 1)

    if cmd == "explain-shell":
        command = " ".join(args.command).strip()
        allowed, msg, analysis = shell_decision(ws, command)
        if args.json:
            _print_json(dict(analysis, allowed=allowed, message=msg))
        else:
            print(render_shell(command, analysis, allowed, msg))
        return 0 if allowed else 1

    if cmd == "audit":
        audit = audit_chain(ws)
        ledger = ws.ledger()
        binding = _chain_binding_problem(ws, ledger) if ledger.get("status") == STATUS_PASSED else ""
        ok = audit["ok"] and not binding
        if args.json:
            _print_json({"ok": ok, "records": len(audit["records"]), "head": audit["head"],
                         "problems": audit["problems"] + ([binding] if binding else [])})
        else:
            print("{} [VERATUM AUDIT] evidence chain: {} record(s){}, head {}".format(
                "✅" if ok else "🛑", len(audit["records"]),
                " (+{} legacy)".format(audit["legacy"]) if audit["legacy"] else "", short_hash(audit["head"] or "", 16) or "—"))
            for prob in audit["problems"] + ([binding] if binding else []):
                print("   ✗ " + prob)
            if ledger.get("status") == STATUS_PASSED and not binding:
                print("   ✓ ledger PASSED is bound to chained record {}".format(short_hash(ledger.get("evidence_hash"), 12)))
        return 0 if ok else 1

    if cmd == "gate":
        result = evaluate_gate(ws)
        if result["passed"] and not args.dry_run:
            close_contract(ws, result)
        if args.json:
            _print_json({k: result[k] for k in ("passed", "problems", "fixes", "current_hash", "changed", "drift")})
        else:
            print(render_gate(result))
        return 0 if result["passed"] else 1

    if cmd == "config":
        if not args.name:
            print(config_show(ws))
        elif args.value is None:
            if args.name not in DEFAULT_CONFIG:
                raise VeratumError("Unknown setting '{}'. Settable: {}.".format(args.name, ", ".join(CONFIG_SETTABLE)))
            print(ws.config().get(args.name))
        else:
            before, after = config_set(ws, args.name, args.value)
            print("⚙️  [VERATUM CONFIG] {} = {}  (was {})".format(args.name, after, before))
        return 0

    if cmd == "status":
        st = compute_status(ws)
        if args.json:
            out = {k: st[k] for k in ("current_hash", "changed", "drift", "evidence_fresh")}
            out.update({"contract_status": st["contract"].get("status"), "ledger_status": st["ledger"].get("status")})
            _print_json(out)
        else:
            print(render_status(st))
        return 0

    raise VeratumError("Unknown command '{}'.".format(cmd))


if __name__ == "__main__":
    sys.exit(main())

# Backwards-compatibility aliases
VERATUM_DIRNAME = VERATUM_DIRNAME
