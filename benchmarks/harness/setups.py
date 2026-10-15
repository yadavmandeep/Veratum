"""The three setups under comparison. Each one installs itself into a fresh workdir.

Add a setup by subclassing Setup and registering it in SETUPS.
"""
import hashlib
import json
import os
import shutil
import subprocess
import tempfile

from . import CACHE_DIR, VERATUM_ROOT
from .workspace import git, init_repo, rmtree


def tree_hash(root, skip=(".git",)):
    """Content hash of a directory (paths + bytes), for provenance."""
    h = hashlib.sha256()
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in skip and d != "__pycache__")
        for name in sorted(filenames):
            full = os.path.join(dirpath, name)
            h.update(os.path.relpath(full, root).replace(os.sep, "/").encode())
            with open(full, "rb") as fh:
                h.update(fh.read().replace(b"\r\n", b"\n"))
    return h.hexdigest()[:16]


def run_cmd(argv, cwd, timeout=600):
    res = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, encoding="utf-8",
                         errors="replace", timeout=timeout, env={**os.environ, "CI": "1"})
    if res.returncode != 0:
        raise RuntimeError("command failed (%s): %s\n%s\n%s" % (res.returncode, argv, res.stdout[-3000:], res.stderr[-3000:]))
    return res.stdout


def which(name):
    path = shutil.which(name)
    if not path:
        raise RuntimeError("%s not found on PATH" % name)
    return path


class Setup:
    name = "?"
    description = ""
    named_prefix = ""

    def prepare(self, refresh=False):
        """One-time work before any run (e.g. download and cache)."""

    def install(self, workdir):
        """Install into a fresh workdir (already `git init`-ed, not yet committed)."""

    def provenance(self):
        return {}

    def prompt(self, task_prompt, mode):
        if mode == "named" and self.named_prefix:
            return self.named_prefix + "\n\n" + task_prompt
        return task_prompt


class Baseline(Setup):
    name = "baseline"
    description = "No harness: the bare agent with the task prompt."


class Gravitas(Setup):
    name = "gravitas"
    description = "Gravitas Core skill via `npx skills add udaysharmadev/Gravitas --skill gravitas --agent claude-code`."
    named_prefix = "Use the gravitas skill for this task."
    SOURCE = "udaysharmadev/Gravitas"

    def __init__(self):
        self.template = os.path.join(CACHE_DIR, "gravitas-template")

    def prepare(self, refresh=False):
        if os.path.isdir(os.path.join(self.template, ".claude", "skills", "gravitas")) and not refresh:
            return
        # Install once into a scratch repo, then overlay the result into every
        # workdir: same bytes for every run, no network inside the timed run.
        scratch = tempfile.mkdtemp(prefix="gravitas-install-")
        init_repo(scratch)
        run_cmd([which("npx"), "-y", "skills", "add", self.SOURCE, "--skill", "gravitas",
                 "--agent", "claude-code", "--yes"], cwd=scratch)
        rmtree(os.path.join(scratch, ".git"))
        if not os.path.isdir(os.path.join(scratch, ".claude", "skills", "gravitas")):
            raise RuntimeError("Gravitas install did not create .claude/skills/gravitas")
        rmtree(self.template)
        os.makedirs(os.path.dirname(self.template), exist_ok=True)
        shutil.copytree(scratch, self.template)
        rmtree(scratch)

    def install(self, workdir):
        shutil.copytree(self.template, workdir, dirs_exist_ok=True)

    def provenance(self):
        lock = os.path.join(self.template, "skills-lock.json")
        info = {"source": self.SOURCE, "skill_tree_hash": tree_hash(os.path.join(self.template, ".claude", "skills", "gravitas"))}
        if os.path.isfile(lock):
            with open(lock, encoding="utf-8") as fh:
                info["skills_lock"] = json.load(fh)
        return info


class Veratum(Setup):
    name = "veratum"
    description = "Veratum skill (skills/veratum) + `veratum init --ide claude-code` (CLAUDE.md block + hooks)."
    named_prefix = "Use Veratum for this task."

    def __init__(self, source="local"):
        # "local": this checkout (bin/veratum.js), "npm": published veratum package.
        self.source = source

    def install(self, workdir):
        shutil.copytree(os.path.join(VERATUM_ROOT, "skills", "veratum"),
                        os.path.join(workdir, ".claude", "skills", "veratum"), dirs_exist_ok=True)
        if self.source == "npm":
            argv = [which("npx"), "-y", "veratum", "init", "--ide", "claude-code", "--dir", workdir]
        else:
            argv = [which("node"), os.path.join(VERATUM_ROOT, "bin", "veratum.js"), "init", "--ide", "claude-code", "--dir", workdir]
        run_cmd(argv, cwd=workdir)

    def provenance(self):
        with open(os.path.join(VERATUM_ROOT, "package.json"), encoding="utf-8") as fh:
            version = json.load(fh).get("version")
        info = {"source": self.source, "version": version,
                "skill_tree_hash": tree_hash(os.path.join(VERATUM_ROOT, "skills", "veratum")),
                "engine_tree_hash": tree_hash(os.path.join(VERATUM_ROOT, "engine")),
                "adapter_tree_hash": tree_hash(os.path.join(VERATUM_ROOT, "adapters", "claude-code"))}
        try:
            info["git_head"] = git(VERATUM_ROOT, "rev-parse", "HEAD").strip()
            info["git_dirty"] = bool(git(VERATUM_ROOT, "status", "--porcelain").strip())
        except RuntimeError:
            info["git_head"] = None
        return info


SETUPS = {"baseline": Baseline, "gravitas": Gravitas, "veratum": Veratum}


def make_setups(names, veratum_source="local"):
    out = []
    for n in names:
        if n not in SETUPS:
            raise ValueError("unknown setup %r (known: %s)" % (n, ", ".join(SETUPS)))
        out.append(SETUPS[n](veratum_source) if n == "veratum" else SETUPS[n]())
    return out
