"""Stand-in for the `claude` CLI, used only to self-test the claude-code driver.

It speaks the same stream-json protocol, fixes py-pagination-bugfix, and then
deliberately does two bad things so every metric is exercised: it writes an
out-of-scope file after its last test run (out-of-scope + unverified final
edit). It behaves identically for every setup except that it mentions the
harness it finds, which exercises the "harness used" metric.

  python benchmarks/bench.py run --tasks py-pagination-bugfix --run-id selftest \
      --claude-cmd "python benchmarks/tests/fake_claude.py"
"""
import json
import os
import subprocess
import sys


def emit(ev):
    sys.stdout.write(json.dumps(ev) + "\n")
    sys.stdout.flush()


def tool(name, **inp):
    emit({"type": "assistant", "message": {"content": [{"type": "tool_use", "name": name, "input": inp}]}})


def main(argv):
    if "--version" in argv:
        print("0.0.0 (fake claude)")
        return 0
    sys.stdin.read()
    if "json" in argv and "stream-json" not in argv:
        print(json.dumps({"type": "result", "is_error": False, "result": "ok"}))
        return 0

    emit({"type": "system", "subtype": "init", "model": "fake-model", "skills": []})
    for harness in ("gravitas", "veratum"):
        if os.path.isdir(os.path.join(".claude", "skills", harness)):
            tool("Read", file_path=".claude/skills/%s/SKILL.md" % harness)
    test_cmd = [sys.executable, "-m", "unittest", "discover", "-s", "tests"]
    tool("Bash", command="python -m unittest discover -s tests")
    if os.path.isfile("pager.py"):
        with open("pager.py", encoding="utf-8") as fh:
            src = fh.read()
        with open("pager.py", "w", encoding="utf-8", newline="\n") as fh:
            fh.write(src.replace("start + per_page - 1", "start + per_page"))
        tool("Edit", file_path="pager.py")
    subprocess.run(test_cmd, capture_output=True)
    tool("Bash", command="python -m unittest discover -s tests")
    with open("scratch_notes.txt", "w", encoding="utf-8") as fh:
        fh.write("notes\n")
    tool("Write", file_path="scratch_notes.txt")
    emit({"type": "result", "subtype": "success", "is_error": False, "result": "Fixed the off-by-one; all tests pass.",
          "duration_ms": 1234, "num_turns": 5, "total_cost_usd": 0.0,
          "usage": {"input_tokens": 100, "output_tokens": 50, "cache_creation_input_tokens": 0,
                    "cache_read_input_tokens": 0},
          "permission_denials": []})
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
