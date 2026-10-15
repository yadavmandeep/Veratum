"""Task spec loading and validation.

A task is a directory under benchmarks/tasks/<id>/ containing:

  task.json   the spec (fields below)
  fixture/    the repo the agent works in (copied fresh for every run)
  hidden/     validator files the agent never sees; copied to __hidden__/ in a
              separate scoring copy after the agent has finished
  solution/   reference solution overlaid by the `oracle` driver, used to prove
              that the hidden validator passes on a correct answer

task.json fields:
  id                 str, must equal the directory name
  category           bugfix | feature | refactor | review
  language           python | typescript | ...
  prompt             exact text given to every setup
  hidden_cmd         argv list, or list of argv lists; all must exit 0 to pass
  expected_scope     glob list (posix paths) of files the agent may change
  visible_test_cmd   optional argv list the agent is told about (informational)
  temptation         null | out-of-scope | post-verify-edit
  temptation_note    optional human explanation
  timeout_sec        agent wall-clock limit (default 900)

Placeholders in commands: {python} -> this interpreter, {node} -> node on PATH.
"""
import json
import os
import shutil
import sys

from . import TASKS_DIR

CATEGORIES = {"bugfix", "feature", "refactor", "review"}
TEMPTATIONS = {None, "out-of-scope", "post-verify-edit"}
REQUIRED = ("id", "category", "language", "prompt", "hidden_cmd", "expected_scope")


class SpecError(ValueError):
    pass


def placeholders():
    return {"python": sys.executable, "node": shutil.which("node") or "node"}


def expand(cmd):
    """Normalise a command field to a list of argv lists with placeholders filled."""
    if not cmd:
        return []
    cmds = cmd if isinstance(cmd[0], list) else [cmd]
    subs = placeholders()
    return [[arg.format(**subs) for arg in argv] for argv in cmds]


def load_task(task_dir):
    path = os.path.join(task_dir, "task.json")
    with open(path, encoding="utf-8") as fh:
        spec = json.load(fh)
    missing = [k for k in REQUIRED if k not in spec]
    if missing:
        raise SpecError("%s: missing fields %s" % (path, missing))
    if spec["id"] != os.path.basename(task_dir):
        raise SpecError("%s: id %r does not match directory" % (path, spec["id"]))
    if spec["category"] not in CATEGORIES:
        raise SpecError("%s: category must be one of %s" % (path, sorted(CATEGORIES)))
    if spec.get("temptation") not in TEMPTATIONS:
        raise SpecError("%s: bad temptation %r" % (path, spec.get("temptation")))
    for sub in ("fixture", "hidden"):
        if not os.path.isdir(os.path.join(task_dir, sub)):
            raise SpecError("%s: missing %s/ directory" % (task_dir, sub))
    spec.setdefault("temptation", None)
    spec.setdefault("timeout_sec", 900)
    spec["dir"] = task_dir
    spec["fixture_dir"] = os.path.join(task_dir, "fixture")
    spec["hidden_dir"] = os.path.join(task_dir, "hidden")
    spec["solution_dir"] = os.path.join(task_dir, "solution")
    return spec


def load_tasks(selector=None):
    """Load all tasks, or those whose id is in the comma-separated ``selector``."""
    ids = sorted(d for d in os.listdir(TASKS_DIR) if os.path.isfile(os.path.join(TASKS_DIR, d, "task.json")))
    if selector:
        wanted = [s.strip() for s in selector.split(",") if s.strip()]
        unknown = [w for w in wanted if w not in ids]
        if unknown:
            raise SpecError("unknown task(s): %s (known: %s)" % (unknown, ", ".join(ids)))
        ids = wanted
    return [load_task(os.path.join(TASKS_DIR, i)) for i in ids]
