#!/usr/bin/env python3
"""A/B benchmark: no harness vs Gravitas vs Veratum. See benchmarks/README.md.

  python benchmarks/bench.py list
  python benchmarks/bench.py validate                      # oracle + pristine checks, no agent
  python benchmarks/bench.py run --driver claude-code --tasks py-pagination-bugfix
  python benchmarks/bench.py score <run_id>
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from harness import runner  # noqa: E402
from harness.drivers import load_driver  # noqa: E402
from harness.report import write_reports  # noqa: E402
from harness.setups import SETUPS, make_setups  # noqa: E402
from harness.spec import load_tasks  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def cmd_list(args):
    for t in load_tasks(args.tasks):
        print("%-28s %-9s %-11s %s" % (t["id"], t["category"], t["language"], t.get("temptation") or ""))


def cmd_validate(args):
    """Every task: hidden validator must FAIL on the pristine fixture and PASS on the reference solution."""
    import shutil
    import tempfile

    from harness import workspace as ws

    tasks = load_tasks(args.tasks)
    root = tempfile.mkdtemp(prefix="bench-validate-")
    bad = 0
    for t in tasks:
        results = {}
        for label, overlay in (("pristine", None), ("solution", t["solution_dir"])):
            work = os.path.join(root, t["id"], label)
            ws.copy_fixture(t["fixture_dir"], work)
            if overlay:
                shutil.copytree(overlay, work, dirs_exist_ok=True)
            out = os.path.join(root, t["id"], label + "-logs")
            os.makedirs(out, exist_ok=True)
            visible, hidden = runner.evaluate(t, work, os.path.join(root, t["id"], label + "-score"), out)
            results[label] = (visible, hidden, out)
        ok = results["pristine"][1] is False and results["solution"][1] is True and results["solution"][0] is not False
        bad += not ok
        print("%-4s %-28s pristine_hidden=%s solution_hidden=%s solution_visible=%s" % (
            "ok" if ok else "BAD", t["id"], results["pristine"][1], results["solution"][1], results["solution"][0]))
        if not ok:
            print("     logs: %s" % os.path.dirname(results["solution"][2]))
    if not bad:
        ws.rmtree(root)
    print("\n%d/%d tasks valid" % (len(tasks) - bad, len(tasks)))
    return 1 if bad else 0


def cmd_run(args):
    options = {"user_settings": args.user_settings, "isolate_mcp": not args.allow_mcp}
    if args.model:
        options["model"] = args.model
    if args.max_budget_usd:
        options["max_budget_usd"] = args.max_budget_usd
    if args.claude_cmd:
        options["claude_cmd"] = args.claude_cmd
    driver = load_driver(args.driver, options)
    tasks = load_tasks(args.tasks)
    setups = make_setups([s.strip() for s in args.setups.split(",")], veratum_source=args.veratum_source)
    try:
        run_id, _ = runner.run_matrix(tasks, setups, driver, reps=args.reps, run_id=args.run_id,
                                      work_root=args.work_root, prompt_mode=args.prompt_mode,
                                      shuffle_seed=args.shuffle_seed, refresh_cache=args.refresh_cache,
                                      keep_workdirs=not args.delete_workdirs, preflight=not args.skip_preflight)
    except runner.PreflightError as exc:
        print("PREFLIGHT FAILED, nothing was run: %s" % exc)
        return 2
    print()
    print(write_reports(run_id))
    print("results: %s" % os.path.join(runner.RESULTS_DIR, run_id))


def cmd_score(args):
    print(write_reports(args.run_id))


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("list", help="list tasks")
    s.add_argument("--tasks")
    s.set_defaults(fn=cmd_list)

    s = sub.add_parser("validate", help="check hidden validators against fixture and reference solution")
    s.add_argument("--tasks")
    s.set_defaults(fn=cmd_validate)

    s = sub.add_parser("run", help="run tasks x setups with a driver, then score")
    s.add_argument("--driver", default="claude-code", help="claude-code | manual | oracle | noop | module:Class")
    s.add_argument("--tasks", help="comma-separated task ids (default: all)")
    s.add_argument("--setups", default=",".join(SETUPS), help="comma-separated (default: %(default)s)")
    s.add_argument("--reps", type=int, default=1, help="repetitions per task x setup")
    s.add_argument("--model", help="model passed to the driver (claude-code: --model)")
    s.add_argument("--max-budget-usd", type=float, help="per-run spend cap (claude-code)")
    s.add_argument("--prompt-mode", choices=["neutral", "named"], default="neutral",
                   help="neutral: identical prompt for all setups; named: prefix 'Use <harness>' for harness setups")
    s.add_argument("--veratum-source", choices=["local", "npm"], default="local",
                   help="local: this checkout's bin/veratum.js; npm: npx veratum-code")
    s.add_argument("--user-settings", action="store_true",
                   help="also load your ~/.claude user settings (off by default for isolation)")
    s.add_argument("--allow-mcp", action="store_true", help="do not pass --strict-mcp-config")
    s.add_argument("--claude-cmd", help="command used instead of `claude` (e.g. the fake agent in tests/)")
    s.add_argument("--skip-preflight", action="store_true", help="do not send the one-line auth check first")
    s.add_argument("--shuffle-seed", type=int, help="randomise job order with this seed")
    s.add_argument("--run-id")
    s.add_argument("--work-root", help="where workdirs go (default: %s)" % runner.default_work_root())
    s.add_argument("--refresh-cache", action="store_true", help="re-download Gravitas")
    s.add_argument("--delete-workdirs", action="store_true")
    s.set_defaults(fn=cmd_run)

    s = sub.add_parser("score", help="(re)build score.md / score.csv / runs.csv for a run")
    s.add_argument("run_id")
    s.set_defaults(fn=cmd_score)

    args = p.parse_args(argv)
    return args.fn(args) or 0


if __name__ == "__main__":
    sys.exit(main())
