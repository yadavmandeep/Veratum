"""Fresh per-run working copies and diff/scope accounting."""
import fnmatch
import os
import shutil
import subprocess
import sys

DEFAULT_GITIGNORE = "__pycache__/\n*.pyc\nnode_modules/\n"

# Paths a harness install (or its runtime state) may legitimately touch. Changes
# here are reported separately and never counted as out-of-scope agent edits.
# One shared list for every setup so no setup gets a private exemption.
HARNESS_GLOBS = [
    ".claude/*",
    ".veratum/*",
    ".agents/*",
    ".gravitas/*",
    "CLAUDE.md",
    "AGENTS.md",
    "GEMINI.md",
    "skills-lock.json",
    ".gitignore",
]


def git(cwd, *args, check=True):
    res = subprocess.run(
        ["git", "-c", "core.quotepath=off", "-c", "core.autocrlf=false", *args],
        cwd=cwd, capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if check and res.returncode != 0:
        raise RuntimeError("git %s failed in %s:\n%s%s" % (" ".join(args), cwd, res.stdout, res.stderr))
    return res.stdout


def copy_fixture(fixture_dir, workdir):
    rmtree(workdir)
    shutil.copytree(fixture_dir, workdir)
    gi = os.path.join(workdir, ".gitignore")
    if not os.path.exists(gi):
        with open(gi, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(DEFAULT_GITIGNORE)


def init_repo(workdir):
    git(workdir, "init", "-q")
    git(workdir, "config", "user.email", "bench@localhost")
    git(workdir, "config", "user.name", "bench")
    git(workdir, "config", "commit.gpgsign", "false")


def commit_baseline(workdir):
    """Commit fixture + harness install so the agent's diff is measured against it."""
    git(workdir, "add", "-A")
    git(workdir, "commit", "-q", "--allow-empty", "-m", "benchmark baseline")
    return git(workdir, "rev-parse", "HEAD").strip()


def changed_files(workdir, base):
    """Files changed by the agent relative to ``base`` (tracked + new untracked)."""
    tracked = git(workdir, "diff", "--name-only", "--no-renames", base).splitlines()
    untracked = git(workdir, "ls-files", "--others", "--exclude-standard").splitlines()
    return sorted({p.strip() for p in tracked + untracked if p.strip()})


def write_patch(workdir, base, dest):
    git(workdir, "add", "-A")
    patch = git(workdir, "diff", "--cached", "--no-renames", base)
    with open(dest, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(patch)


def matches(path, globs):
    return any(fnmatch.fnmatchcase(path, g) for g in globs)


def classify(paths, expected_scope):
    out = {"in_scope": [], "out_of_scope": [], "harness": []}
    for p in paths:
        if matches(p, expected_scope):
            out["in_scope"].append(p)
        elif matches(p, HARNESS_GLOBS):
            out["harness"].append(p)
        else:
            out["out_of_scope"].append(p)
    return out


def _force_remove(func, path, _exc):
    # git object files are read-only on Windows
    os.chmod(path, 0o700)
    func(path)


def rmtree(path):
    if not os.path.exists(path):
        return
    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=_force_remove)
    else:
        shutil.rmtree(path, onerror=_force_remove)
