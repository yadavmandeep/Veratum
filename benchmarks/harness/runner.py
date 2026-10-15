"""Prepare a fresh workdir per (task, setup, rep), run the driver, evaluate."""
import datetime
import json
import os
import platform
import random
import shutil
import subprocess
import sys
import tempfile
import time
import traceback

from . import RESULTS_DIR
from . import analysis
from . import workspace as ws
from .spec import expand


def default_work_root():
    # Outside the repo on purpose: the agent's cwd must not contain (or sit
    # next to) benchmarks/tasks/*/hidden.
    return os.path.join(tempfile.gettempdir(), "veratum-bench")


def run_commands(cmds, cwd, log_path, timeout=300):
    """Run each argv; pass iff all exit 0. Output goes to log_path."""
    ok = True
    with open(log_path, "w", encoding="utf-8", newline="\n") as log:
        for argv in cmds:
            log.write("$ %s\n" % " ".join(argv))
            try:
                res = subprocess.run(argv, cwd=cwd, capture_output=True, text=True, encoding="utf-8",
                                     errors="replace", timeout=timeout,
                                     env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1"})
                log.write(res.stdout + res.stderr + "\n[exit %d]\n\n" % res.returncode)
                ok = ok and res.returncode == 0
            except subprocess.TimeoutExpired:
                log.write("[timeout after %ds]\n\n" % timeout)
                ok = False
    return ok


def evaluate(task, workdir, score_dir, out_dir):
    """Score a finished workdir in a separate copy so hidden files never touch it."""
    ws.rmtree(score_dir)
    shutil.copytree(workdir, score_dir, ignore=shutil.ignore_patterns(".git", "node_modules", "__pycache__"))
    visible = None
    if task.get("visible_test_cmd"):
        visible = run_commands(expand(task["visible_test_cmd"]), score_dir, os.path.join(out_dir, "visible_tests.log"))
    hidden_target = os.path.join(score_dir, "__hidden__")
    ws.rmtree(hidden_target)
    shutil.copytree(task["hidden_dir"], hidden_target)
    hidden = run_commands(expand(task["hidden_cmd"]), score_dir, os.path.join(out_dir, "hidden_tests.log"))
    return visible, hidden


def prepare_workdir(task, setup, workdir):
    ws.copy_fixture(task["fixture_dir"], workdir)
    ws.init_repo(workdir)
    setup.install(workdir)
    return ws.commit_baseline(workdir)


def run_one(task, setup, driver, rep, run_id, out_root, work_root, prompt_mode):
    rel = os.path.join(task["id"], setup.name, "r%d" % rep)
    out_dir = os.path.join(out_root, rel)
    workdir = os.path.join(work_root, run_id, rel)
    score_dir = os.path.join(work_root, run_id, "_score", rel)
    ws.rmtree(out_dir)
    os.makedirs(out_dir)
    outcome = {"task": task["id"], "category": task["category"], "language": task["language"],
               "temptation": task.get("temptation"), "setup": setup.name, "rep": rep,
               "driver": driver.name, "prompt_mode": prompt_mode, "workdir": workdir}
    try:
        base = prepare_workdir(task, setup, workdir)
        prompt = setup.prompt(task["prompt"], prompt_mode)
        outcome["prompt"] = prompt
        started = time.time()
        agent = driver.run({"workdir": workdir, "prompt": prompt, "out_dir": out_dir,
                            "timeout_sec": task["timeout_sec"], "task": task, "setup": setup.name})
        agent.setdefault("wall_ms", int((time.time() - started) * 1000))
        with open(os.path.join(out_dir, "agent.json"), "w", encoding="utf-8") as fh:
            json.dump(agent, fh, indent=1)

        changed = ws.changed_files(workdir, base)
        scope = ws.classify(changed, task["expected_scope"])
        ws.write_patch(workdir, base, os.path.join(out_dir, "diff.patch"))
        visible, hidden = evaluate(task, workdir, score_dir, out_dir)

        if "claimed_done" in agent:
            claimed, claim_reason = bool(agent["claimed_done"]), "reported by driver"
        elif agent.get("timed_out"):
            claimed, claim_reason = False, "timed out"
        else:
            claimed, claim_reason = analysis.detect_claim(agent.get("final_text"))
        calls = agent.get("tool_calls") or []
        # API/auth/rate-limit failures say nothing about the setup: excluded from rates.
        infra = None
        if agent.get("is_error") and agent.get("api_error_status"):
            infra = "API error %s: %s" % (agent["api_error_status"], agent.get("final_text"))
        elif agent.get("final_text") is None and agent.get("error") and not agent.get("timed_out"):
            infra = agent["error"][:500]
        outcome.update({
            "infra_error": infra,
            "hidden_pass": hidden,
            "visible_pass": visible,
            "claimed_done": claimed,
            "claim_source": claim_reason,
            "false_completion": bool(claimed and not hidden),
            "changed_files": changed,
            "out_of_scope_files": scope["out_of_scope"],
            "harness_files": scope["harness"],
            "in_scope_files": scope["in_scope"],
            "timed_out": bool(agent.get("timed_out")),
            "agent_exit_code": agent.get("exit_code"),
            "agent_error": agent.get("error"),
            "wall_ms": agent.get("wall_ms"),
            "duration_ms": agent.get("duration_ms"),
            "num_turns": agent.get("num_turns"),
            "cost_usd": agent.get("cost_usd"),
            "usage": agent.get("usage"),
            "total_tokens": analysis.total_tokens(agent.get("usage")),
            "model": agent.get("model"),
            "interventions": agent.get("interventions", 0),
            "interventions_source": "driver" if "interventions" in agent else "headless (none possible)",
            "permission_denials": agent.get("permission_denials"),
            "harness_engaged": analysis.engagement(setup.name, calls) if "tool_calls" in agent else None,
            "final_text": agent.get("final_text"),
        })
        outcome.update(analysis.tool_stats(calls) if calls else {"final_edit_unverified": None})
    except Exception as exc:  # noqa: BLE001 - recorded, run continues
        outcome.update({"harness_error": "%s: %s" % (type(exc).__name__, exc),
                        "traceback": traceback.format_exc()})
    with open(os.path.join(out_dir, "outcome.json"), "w", encoding="utf-8") as fh:
        json.dump(outcome, fh, indent=1)
    return outcome


def tool_version(argv):
    try:
        return subprocess.run(argv, capture_output=True, text=True, timeout=30).stdout.strip()
    except Exception:  # noqa: BLE001
        return None


class PreflightError(RuntimeError):
    pass


def run_matrix(tasks, setups, driver, reps=1, run_id=None, work_root=None, prompt_mode="neutral",
               shuffle_seed=None, refresh_cache=False, keep_workdirs=True, preflight=True, log=print):
    if preflight:
        problem = driver.preflight()
        if problem:
            raise PreflightError("driver %s is not usable: %s" % (driver.name, problem))
    run_id = run_id or datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    work_root = work_root or default_work_root()
    out_root = os.path.join(RESULTS_DIR, run_id)
    os.makedirs(out_root, exist_ok=True)
    for s in setups:
        s.prepare(refresh=refresh_cache)

    manifest = {
        "run_id": run_id,
        "started": datetime.datetime.now().isoformat(timespec="seconds"),
        "driver": driver.name,
        "driver_version": driver.version(),
        "driver_options": driver.options,
        "prompt_mode": prompt_mode,
        "reps": reps,
        "tasks": [t["id"] for t in tasks],
        "setups": {s.name: {"description": s.description, **s.provenance()} for s in setups},
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "node": tool_version(["node", "--version"]),
        "git": tool_version(["git", "--version"]),
        "work_root": work_root,
        "shuffle_seed": shuffle_seed,
    }
    with open(os.path.join(out_root, "run.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=1)

    # Interleave setups within each (task, rep) so slow drift (API latency,
    # model-side changes) hits every setup equally; optionally shuffle order.
    jobs = [(t, s, r) for r in range(1, reps + 1) for t in tasks for s in setups]
    if shuffle_seed is not None:
        random.Random(shuffle_seed).shuffle(jobs)
    outcomes = []
    for i, (task, setup, rep) in enumerate(jobs, 1):
        log("[%d/%d] %s / %s / r%d ..." % (i, len(jobs), task["id"], setup.name, rep))
        o = run_one(task, setup, driver, rep, run_id, out_root, work_root, prompt_mode)
        if o.get("harness_error"):
            log("    HARNESS ERROR: %s" % o["harness_error"])
        elif o.get("infra_error"):
            log("    INFRA ERROR (excluded from scores): %s" % o["infra_error"])
        else:
            log("    hidden=%s claimed=%s out_of_scope=%d time=%.0fs" % (
                "PASS" if o["hidden_pass"] else "FAIL", o["claimed_done"],
                len(o["out_of_scope_files"]), (o.get("wall_ms") or 0) / 1000))
        if not keep_workdirs:
            ws.rmtree(o["workdir"])
        outcomes.append(o)
    manifest["finished"] = datetime.datetime.now().isoformat(timespec="seconds")
    with open(os.path.join(out_root, "run.json"), "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=1)
    return run_id, outcomes
