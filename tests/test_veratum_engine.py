"""
Veratum engine test-suite (yadavmandeep).

Run:  python3 -m unittest tests/test_veratum_engine.py -v

Covers brain persistence, contract locking & scope checks, blast-radius import
detection (JS/TS, Python, Go, Rust, Java), log compaction, cryptographic
tree-hash binding (post-verification edit bypass is blocked), scope drift,
shadow checkpoints, IDE hook protocols, the MCP server and the Node installer.
"""
from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ENGINE = REPO / "engine" / "veratum_cli.py"
MCP = REPO / "engine" / "mcp_server.py"
sys.path.insert(0, str(REPO / "engine"))
import veratum_cli
veratum_cli = veratum_cli  # noqa: E402

os.environ.update({
    "GIT_AUTHOR_NAME": "Veratum Test", "GIT_AUTHOR_EMAIL": "test@yadavmandeep",
    "GIT_COMMITTER_NAME": "Veratum Test", "GIT_COMMITTER_EMAIL": "test@yadavmandeep",
    "PYTHONIOENCODING": "utf-8",
})
os.environ.pop("VERATUM_ROOT", None)
os.environ.pop("VERATUM_TRIVIAL", None)
HAS_GIT = shutil.which("git") is not None
HAS_NODE = shutil.which("node") is not None


def _rmtree(path: Path) -> None:
    def onerror(func, p, _exc):
        os.chmod(p, stat.S_IWRITE)
        func(p)
    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=onerror)
    else:
        shutil.rmtree(path, onerror=onerror)


class VeratumTestCase(unittest.TestCase):
    use_git = True

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="veratum-test-")).resolve()
        veratum_cli._GIT_REPO_CACHE.clear()
        if self.use_git:
            if not HAS_GIT:
                self.skipTest("git not available")
            self.git("init", "-q")
            self.git("config", "core.autocrlf", "false")
            self.git("config", "user.email", "test@yadavmandeep")
            self.git("config", "user.name", "Veratum Test")

    def tearDown(self):
        _rmtree(self.tmp)

    # -- helpers ---------------------------------------------------------
    def git(self, *args):
        return subprocess.run(["git", *args], cwd=self.tmp, capture_output=True, text=True, check=True).stdout

    def write(self, rel: str, content: str) -> Path:
        p = self.tmp / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8", newline="\n")
        return p

    def cli(self, *args, stdin: str | None = None, env: dict | None = None):
        full_env = {k: v for k, v in os.environ.items() if k != "CLAUDE_PROJECT_DIR"}  # never act on the host project
        full_env.update(env or {})
        proc = subprocess.run([sys.executable, str(ENGINE), "--root", str(self.tmp), *args],
                              input=(stdin or "").encode("utf-8"), capture_output=True, env=full_env, timeout=120)
        out = proc.stdout.decode("utf-8", errors="replace")
        err = proc.stderr.decode("utf-8", errors="replace")
        return proc.returncode, out + err, out, err

    def hook(self, event: str, payload: dict, host: str = "claude", script: Path | None = None):
        script = script or ENGINE
        args = [sys.executable, str(script)]
        if script == ENGINE:
            args += ["--root", str(self.tmp), "hook", event, "--host", host]
        env = {k: v for k, v in os.environ.items() if k != "CLAUDE_PROJECT_DIR"}  # never act on the host project
        proc = subprocess.run(args, input=json.dumps(payload).encode("utf-8"), capture_output=True,
                              cwd=self.tmp, timeout=120, env=env)
        return proc.returncode, proc.stdout.decode("utf-8", "replace"), proc.stderr.decode("utf-8", "replace")

    def json_file(self, rel: str) -> dict:
        return json.loads((self.tmp / rel).read_text(encoding="utf-8"))

    def seed_project(self):
        self.write("package.json", json.dumps({"name": "demo", "scripts": {"test": "node -e 0", "build": "node -e 0", "lint": "node -e 0"}}))
        self.write("src/math.ts", "export const add = (a: number, b: number) => a + b;\n")
        self.write("src/app.ts", "import { add } from './math';\nconsole.log(add(1, 2));\n")
        self.write("README.md", "demo\n")
        if self.use_git:
            self.git("add", "-A")
            self.git("commit", "-qm", "init")
        code, out, *_ = self.cli("init")
        self.assertEqual(code, 0, out)

    def lock(self, files="src/math.ts", verify="python -c \"print('ok')\"", profile="auto"):
        code, out, *_ = self.cli("contract", "--goal", "change math", "--files", files, "--verify", verify,
                                 "--profile", profile)
        self.assertEqual(code, 0, out)
        return out


# ---------------------------------------------------------------------------
# Brain
# ---------------------------------------------------------------------------

class TestBrain(VeratumTestCase):
    def test_init_creates_layout_and_detects_stack(self):
        self.seed_project()
        for rel in ("brain.json", "contract.json", "ledger.json", "config.json", "logs", ".gitignore"):
            self.assertTrue((self.tmp / ".veratum" / rel).exists(), rel)
        brain = self.json_file(".veratum/brain.json")
        self.assertIn("node", brain["stack"])
        self.assertEqual(brain["commands"]["test"], "npm test")
        self.assertEqual(brain["commands"]["build"], "npm run build")
        self.assertIn("src", brain["modules"])
        self.assertEqual(self.json_file(".veratum/ledger.json")["status"], "UNVERIFIED")

    def test_detects_python_go_rust_stacks(self):
        self.write("pyproject.toml", "[project]\nname='x'\n[tool.pytest.ini_options]\n")
        self.write("go.mod", "module example.com/demo\n")
        self.write("Cargo.toml", "[package]\nname='demo'\n")
        det = veratum_cli.detect_stack(self.tmp)
        self.assertTrue({"python", "go", "rust"}.issubset(det["stack"]))
        self.assertEqual(det["commands"]["test"], "python -m pytest -q")

    def test_remember_persists_across_processes_and_dedupes(self):
        self.seed_project()
        self.cli("remember", "Auth tokens are validated in src/auth.ts", "--kind", "architecture")
        self.cli("brain", "remember", "Never mock the DB in integration tests", "--kind", "pitfall")
        self.cli("remember", "auth tokens are validated in src/auth.ts")  # duplicate (case-insensitive)
        self.cli("brain", "set-cmd", "typecheck", "npx tsc --noEmit")
        brain = self.json_file(".veratum/brain.json")
        self.assertEqual(len(brain["insights"]), 2)
        self.assertEqual(brain["commands"]["typecheck"], "npx tsc --noEmit")
        code, out, *_ = self.cli("brain", "show")
        self.assertEqual(code, 0)
        self.assertIn("Never mock the DB", out)
        self.assertIn("Pitfalls", out)
        self.cli("brain", "forget", brain["insights"][0]["id"])
        self.assertEqual(len(self.json_file(".veratum/brain.json")["insights"]), 1)

    def test_verified_commands_are_learned(self):
        self.seed_project()
        self.lock()
        self.cli("verify", "python -c \"print('ok')\"")
        brain = self.json_file(".veratum/brain.json")
        self.assertIn("python -c \"print('ok')\"", brain["known_good_commands"])
        self.assertEqual(brain["stats"]["verify_passes"], 1)


# ---------------------------------------------------------------------------
# Contract & scope
# ---------------------------------------------------------------------------

class TestContractAndScope(VeratumTestCase):
    def test_contract_locks_scope_resets_ledger_and_runs_impact(self):
        self.seed_project()
        out = self.lock()
        self.assertIn("CONTRACT LOCKED", out)
        self.assertIn("src/app.ts", out)  # blast radius printed
        contract = self.json_file(".veratum/contract.json")
        self.assertEqual(contract["status"], "ACTIVE")
        self.assertEqual(contract["files"], ["src/math.ts"])
        self.assertEqual(contract["impact"]["src/math.ts"]["dependents"], ["src/app.ts"])
        self.assertEqual(self.json_file(".veratum/ledger.json")["status"], "IN_PROGRESS")

    def test_check_scope(self):
        self.seed_project()
        code, out, *_ = self.cli("check-scope", "src/math.ts")
        self.assertEqual(code, 1, "no contract must block edits")
        self.assertIn("No active Veratum contract", out)
        self.lock(files="src/math.ts,docs/,tests/*.py")
        self.assertEqual(self.cli("check-scope", "src/math.ts")[0], 0)
        self.assertEqual(self.cli("check-scope", str(self.tmp / "src" / "math.ts"))[0], 0)
        self.assertEqual(self.cli("check-scope", "docs/guide/intro.md")[0], 0)
        self.assertEqual(self.cli("check-scope", "tests/test_x.py")[0], 0)
        code, out, *_ = self.cli("check-scope", "src/app.ts")
        self.assertEqual(code, 1)
        self.assertIn("OUTSIDE the active contract", out)
        self.assertEqual(self.cli("check-scope", ".veratum/ledger.json")[0], 1, "evidence files are protected")
        self.cli("contract", "--extend", "src/app.ts")
        self.assertEqual(self.cli("check-scope", "src/app.ts")[0], 0)

    def test_trivial_bypass_and_advisory_mode(self):
        self.seed_project()
        self.assertEqual(self.cli("check-scope", "src/app.ts", env={"VERATUM_TRIVIAL": "1"})[0], 0)
        cfg = self.json_file(".veratum/config.json")
        cfg["enforcement"] = "advisory"
        (self.tmp / ".veratum" / "config.json").write_text(json.dumps(cfg), encoding="utf-8")
        self.assertEqual(self.cli("check-scope", "src/app.ts")[0], 0)

    def test_contract_requires_goal_and_files(self):
        self.seed_project()
        code, out, *_ = self.cli("contract", "--goal", "x")
        self.assertNotEqual(code, 0)
        self.assertIn("--files", out)


# ---------------------------------------------------------------------------
# Blast radius
# ---------------------------------------------------------------------------

class TestImpact(VeratumTestCase):
    use_git = False

    def impact(self, target: str) -> dict:
        ws = veratum_cli.Workspace(self.tmp)
        return veratum_cli.CodeIndex(ws).blast_radius(target, depth=2)

    def test_javascript_typescript(self):
        self.write("src/lib/auth.ts", "export function login() {}\n")
        self.write("src/api/login.ts", "import { login } from '../lib/auth';\n")
        self.write("src/api/esm.ts", "export * from '../lib/auth.js';\n")
        self.write("src/pages/home.tsx", "import { login } from '@/lib/auth';\n")
        self.write("src/legacy.js", "const a = require('./lib/auth');\n")
        self.write("src/lazy.ts", "const m = await import('./lib/auth');\n")
        self.write("src/lib/auth.test.ts", "import { login } from './auth';\n")
        self.write("src/other.ts", "import x from './lib/authz';\n")
        self.write("src/server.ts", "import { handler } from './api/login';\n")
        rep = self.impact("src/lib/auth.ts")
        self.assertEqual(sorted(rep["direct"]), ["src/api/esm.ts", "src/api/login.ts", "src/lazy.ts",
                                                 "src/legacy.js", "src/lib/auth.test.ts", "src/pages/home.tsx"])
        self.assertIn("src/server.ts", rep["transitive"][0])  # depth 2
        self.assertIn("src/lib/auth.test.ts", rep["tests"])
        self.assertNotIn("src/other.ts", rep["all"])

    def test_js_index_resolution(self):
        self.write("src/utils/index.ts", "export const x = 1;\n")
        self.write("src/main.ts", "import { x } from './utils';\n")
        self.assertEqual(self.impact("src/utils/index.ts")["direct"], ["src/main.ts"])

    def test_python(self):
        self.write("app/__init__.py", "")
        self.write("app/services/__init__.py", "")
        self.write("app/services/billing.py", "def charge(): pass\n")
        self.write("app/api.py", "from app.services.billing import charge\n")
        self.write("app/services/worker.py", "from .billing import charge\n")
        self.write("app/cli.py", "from app.services import billing\n")
        self.write("app/other.py", "import app.services.billing as b\n")
        self.write("tests/test_billing.py", "from app.services.billing import charge\n")
        self.write("app/unrelated.py", "import json\nfrom app import api\n")
        rep = self.impact("app/services/billing.py")
        self.assertEqual(sorted(rep["direct"]), ["app/api.py", "app/cli.py", "app/other.py",
                                                 "app/services/worker.py", "tests/test_billing.py"])
        self.assertIn("tests/test_billing.py", rep["tests"])
        self.assertIn("app/unrelated.py", rep["transitive"][0])

    def test_go(self):
        self.write("go.mod", "module example.com/shop\n\ngo 1.22\n")
        self.write("internal/cart/cart.go", "package cart\n")
        self.write("cmd/api/main.go", 'package main\n\nimport (\n\t"fmt"\n\t"example.com/shop/internal/cart"\n)\n')
        self.write("internal/cart/cart_test.go", "package cart\n")
        rep = self.impact("internal/cart/cart.go")
        self.assertEqual(rep["direct"], ["cmd/api/main.go"])
        self.assertIn("internal/cart/cart_test.go", rep["tests"])

    def test_rust(self):
        self.write("Cargo.toml", "[package]\nname='demo'\n")
        self.write("src/lib.rs", "pub mod db;\n")
        self.write("src/db.rs", "pub fn connect() {}\n")
        self.write("src/api.rs", "use crate::db::connect;\n")
        self.write("src/api/handlers.rs", "use super::super::db;\n")
        rep = self.impact("src/db.rs")
        self.assertEqual(sorted(rep["direct"]), ["src/api.rs", "src/api/handlers.rs", "src/lib.rs"])

    def test_java(self):
        self.write("src/main/java/com/acme/billing/Invoice.java", "package com.acme.billing;\npublic class Invoice {}\n")
        self.write("src/main/java/com/acme/api/Controller.java", "package com.acme.api;\nimport com.acme.billing.Invoice;\n")
        self.write("src/main/java/com/acme/billing/Ledger.java", "package com.acme.billing;\nclass Ledger { Invoice i; }\n")
        self.write("src/main/java/com/acme/web/All.java", "package com.acme.web;\nimport com.acme.billing.*;\n")
        self.write("src/test/java/com/acme/billing/InvoiceTest.java", "package com.acme.billing;\nclass InvoiceTest { Invoice i; }\n")
        rep = self.impact("src/main/java/com/acme/billing/Invoice.java")
        self.assertEqual(sorted(rep["direct"]), [
            "src/main/java/com/acme/api/Controller.java", "src/main/java/com/acme/billing/Ledger.java",
            "src/main/java/com/acme/web/All.java", "src/test/java/com/acme/billing/InvoiceTest.java"])
        self.assertIn("src/test/java/com/acme/billing/InvoiceTest.java", rep["tests"])

    def test_symbols_usage_and_dynamic_refs(self):
        self.write("src/lib/auth.ts", "export function verifyToken() {}\nexport const refreshSession = 1;\nfunction internal() {}\n")
        self.write("src/api/a.ts", "import { verifyToken } from '../lib/auth';\nverifyToken();\n")
        self.write("src/api/b.ts", "import { refreshSession } from '../lib/auth';\n")
        self.write("src/plugins/loader.js", "const fn = registry['verifyToken'];\n")
        ws = veratum_cli.Workspace(self.tmp)
        rep = veratum_cli.CodeIndex(ws).blast_radius("src/lib/auth.ts", depth=2)
        self.assertEqual(rep["symbols"], ["verifyToken", "refreshSession"])
        self.assertEqual(rep["usage"]["src/api/a.ts"], ["verifyToken"])
        self.assertEqual([h["file"] for h in rep["dynamic_refs"]], ["src/plugins/loader.js"])
        only = veratum_cli.CodeIndex(ws).blast_radius("src/lib/auth.ts", symbol="refreshSession")
        self.assertEqual(only["direct"], ["src/api/b.ts"])

    def test_impact_cli_json(self):
        self.write("a.py", "x = 1\n")
        self.write("b.py", "import a\n")
        code, out, stdout, _ = self.cli("impact", "a.py", "--json")
        self.assertEqual(code, 0, out)
        self.assertEqual(json.loads(stdout)["direct"], ["b.py"])


class TestImpactEvidence(VeratumTestCase):
    """Every relationship carries file:line proof and an EXTRACTED / INFERRED label."""
    use_git = False

    def report(self, target: str, depth: int = 2, **kw) -> dict:
        ws = veratum_cli.Workspace(self.tmp)
        return veratum_cli.CodeIndex(ws).blast_radius(target, depth=depth, evidence=True, **kw)

    @staticmethod
    def edge(rep: dict, source: str, relation: str, target: str = None) -> dict:
        for e in rep["edges"]:
            if e["source"] == source and e["relation"] == relation and (target is None or e["target"] == target):
                return e
        raise AssertionError("no {} edge from {} in {}".format(relation, source, rep["edges"]))

    def test_default_report_is_unchanged(self):
        self.write("a.py", "def run(): pass\n")
        self.write("b.py", "import a\n")
        rep = veratum_cli.CodeIndex(veratum_cli.Workspace(self.tmp)).blast_radius("a.py")
        self.assertNotIn("edges", rep)
        self.assertNotIn("confidence", rep)

    def test_import_line_and_call_site(self):
        self.write("src/lib/auth.ts", "export function verifyToken() {}\nexport const refreshSession = 1;\n")
        self.write("src/api/a.ts", "// guard\n\nimport { verifyToken } from '../lib/auth';\nconst x = 1;\nverifyToken();\nconst y = verifyToken;\n")
        rep = self.report("src/lib/auth.ts")
        imp = self.edge(rep, "src/api/a.ts", "imports")
        self.assertEqual(imp["confidence"], "EXTRACTED")
        self.assertEqual(imp["evidence"][0]["line"], 3)
        self.assertIn("../lib/auth", imp["evidence"][0]["text"])
        call = self.edge(rep, "src/api/a.ts", "calls", "src/lib/auth.ts::verifyToken")
        self.assertEqual(call["confidence"], "INFERRED")
        self.assertEqual(call["evidence"][0]["line"], 5)  # the import line (3) is not a call site

    def test_python_parenthesised_import_is_not_a_reference(self):
        self.write("app/billing.py", "def charge(): pass\ndef refund(): pass\n")
        self.write("app/api.py", "from app.billing import (\n    charge,\n    refund,\n)\n\nrefund()\n")
        rep = self.report("app/billing.py")
        self.assertEqual(self.edge(rep, "app/api.py", "imports")["evidence"][0]["line"], 1)
        self.assertEqual(self.edge(rep, "app/api.py", "calls", "app/billing.py::refund")["evidence"][0]["line"], 6)

    def test_transitive_edge_names_its_parent(self):
        self.write("a.py", "x = 1\n")
        self.write("b.py", "import a\n")
        self.write("c.py", "\nimport b\n")
        rep = self.report("a.py", depth=2)
        e = self.edge(rep, "c.py", "imports", "b.py")
        self.assertEqual((e["depth"], e["confidence"], e["evidence"][0]["line"]), (2, "EXTRACTED", 2))

    def test_inferred_relationships_are_labelled(self):
        self.write("src/lib/auth.ts", "export function verifyToken() {}\n")
        self.write("src/lib/auth.test.ts", "import { verifyToken } from './auth';\n")
        self.write("tests/auth.spec.ts", "describe('auth', () => {});\n")
        self.write("src/plugins/loader.js", "\nconst fn = registry['verifyToken'];\n")
        rep = self.report("src/lib/auth.ts")
        self.assertEqual(self.edge(rep, "src/lib/auth.test.ts", "imports")["confidence"], "EXTRACTED")
        name_match = self.edge(rep, "tests/auth.spec.ts", "tests")
        self.assertEqual(name_match["confidence"], "INFERRED")
        self.assertIn("name matches", name_match["evidence"][0]["reason"])
        dyn = self.edge(rep, "src/plugins/loader.js", "mentions")
        self.assertEqual((dyn["confidence"], dyn["evidence"][0]["line"]), ("INFERRED", 2))
        counts = rep["confidence"]
        self.assertEqual(counts["EXTRACTED"] + counts["INFERRED"], len(rep["edges"]))

    def test_other_languages_locate_the_statement(self):
        self.write("go.mod", "module example.com/shop\n")
        self.write("internal/cart/cart.go", "package cart\n")
        self.write("cmd/main.go", 'package main\n\nimport (\n\t"fmt"\n\t"example.com/shop/internal/cart"\n)\n')
        self.assertEqual(self.edge(self.report("internal/cart/cart.go"), "cmd/main.go", "imports")["evidence"][0]["line"], 5)
        self.write("src/db.rs", "pub fn connect() {}\n")
        self.write("src/api.rs", "// h\nuse crate::db::connect;\n")
        self.assertEqual(self.edge(self.report("src/db.rs"), "src/api.rs", "imports")["evidence"][0]["line"], 2)
        self.write("src/main/java/com/acme/Invoice.java", "package com.acme;\npublic class Invoice {}\n")
        self.write("src/main/java/com/acme/api/Ctl.java", "package com.acme.api;\n\nimport com.acme.Invoice;\n")
        self.assertEqual(self.edge(self.report("src/main/java/com/acme/Invoice.java"),
                                   "src/main/java/com/acme/api/Ctl.java", "imports")["evidence"][0]["line"], 3)
        self.write("inc/util.h", "int f(void);\n")
        self.write("src/app.c", '#include <stdio.h>\n#include "util.h"\n')
        self.write("src/other.c", '#include "../inc/util.h"\n')
        rep = self.report("inc/util.h")
        self.assertEqual(self.edge(rep, "src/other.c", "imports")["evidence"][0]["line"], 1)

    def test_java_same_package_use_is_only_inferred(self):
        self.write("src/main/java/com/acme/Invoice.java", "package com.acme;\npublic class Invoice {}\n")
        self.write("src/main/java/com/acme/Ledger.java", "package com.acme;\n\nclass Ledger { Invoice i; }\n")
        e = self.edge(self.report("src/main/java/com/acme/Invoice.java"), "src/main/java/com/acme/Ledger.java", "imports")
        self.assertEqual((e["confidence"], e["evidence"][0]["line"]), ("INFERRED", 3))

    def test_cli_evidence_flag_and_json(self):
        self.write("a.py", "x = 1\n")
        self.write("b.py", "\nimport a\n")
        code, out, stdout, _ = self.cli("impact", "a.py", "--evidence")
        self.assertEqual(code, 0, out)
        self.assertIn("[EXTRACTED] b.py:2 imports → a.py", stdout)
        self.assertIn("import a", stdout)
        code, out, stdout, _ = self.cli("impact", "a.py")
        self.assertNotIn("EXTRACTED", stdout)
        code, out, stdout, _ = self.cli("impact", "a.py", "--json")
        self.assertEqual(json.loads(stdout)["edges"][0]["evidence"][0]["line"], 2)


# ---------------------------------------------------------------------------
# Log compaction
# ---------------------------------------------------------------------------

NOISY_FAILURE = (
    "\n".join("tests/test_mod_{0}.py::test_case_{0} PASSED".format(i) for i in range(400))
    + "\n\x1b[31mTraceback (most recent call last):\x1b[0m\n"
    + '  File "src/calc.py", line 42, in divide\n    return a / b\nZeroDivisionError: division by zero\n'
    + "FAILED tests/test_calc.py::test_divide - ZeroDivisionError: division by zero\n"
    + "=========== 1 failed, 400 passed in 3.21s ===========\n"
)


class TestCompaction(VeratumTestCase):
    use_git = False

    def test_compaction_keeps_signal_and_drops_noise(self):
        res = veratum_cli.compact_output(NOISY_FAILURE, max_lines=40)
        text = res["text"]
        self.assertLessEqual(len(text.splitlines()), 40)
        for needle in ('File "src/calc.py", line 42', "ZeroDivisionError: division by zero",
                       "FAILED tests/test_calc.py::test_divide", "1 failed, 400 passed"):
            self.assertIn(needle, text)
        self.assertNotIn("\x1b[", text)
        self.assertLess(text.count("PASSED"), 10)
        self.assertGreaterEqual(res["saved_pct"], 80)

    def test_short_output_is_untouched(self):
        res = veratum_cli.compact_output("error: x\nline 2\n")
        self.assertEqual(res["text"], "error: x\nline 2")
        self.assertEqual(res["saved_pct"], 0)

    def test_typescript_and_jest_errors(self):
        noise = "\n".join(" PASS  src/ok{}.test.ts".format(i) for i in range(200))
        raw = noise + "\nsrc/app.ts(12,5): error TS2322: Type 'string' is not assignable to type 'number'.\n" \
            " FAIL  src/math.test.ts\n  ● add › adds numbers\n    expect(received).toBe(expected)\n" \
            "    Expected: 3\n    Received: 4\n      at Object.<anonymous> (src/math.test.ts:5:20)\n" \
            "Tests:       1 failed, 200 passed, 201 total\n"
        text = veratum_cli.compact_output(raw)["text"]
        self.assertIn("error TS2322", text)
        self.assertIn("FAIL  src/math.test.ts", text)
        self.assertIn("src/math.test.ts:5:20", text)
        self.assertIn("Tests:       1 failed", text)

    def test_verify_failure_saves_full_log_and_prints_compacted_trace(self):
        self.seed_project()
        self.write("noisy.py", "import sys\nsys.stdout.write({!r})\nsys.exit(1)\n".format(NOISY_FAILURE))
        self.lock(verify="python noisy.py")
        code, out, *_ = self.cli("verify", "python noisy.py")
        self.assertEqual(code, 1)
        self.assertIn("COMPACTED ERROR TRACE", out)
        self.assertIn("ZeroDivisionError", out)
        self.assertLess(out.count("PASSED"), 10)
        full = (self.tmp / ".veratum" / "logs" / "last_run.log").read_text(encoding="utf-8")
        self.assertEqual(full.count("PASSED"), 400)
        ledger = self.json_file(".veratum/ledger.json")
        self.assertEqual(ledger["status"], "FAILED")
        self.assertEqual(ledger["exit_code"], 1)
        self.assertEqual(ledger["consecutive_failures"], 1)
        self.assertTrue(ledger["signature"])
        code, out, *_ = self.cli("verify", "--force", "python noisy.py")
        self.assertIn("Retry budget exhausted", out)


# ---------------------------------------------------------------------------
# Cryptographic completion gate
# ---------------------------------------------------------------------------

class TestGate(VeratumTestCase):
    VERIFY = "python -c \"print('ok')\""

    def edit_and_verify(self):
        self.seed_project()
        self.lock(verify=self.VERIFY)
        self.write("src/math.ts", "export const add = (a: number, b: number) => a + b + 0;\n")
        code, out, *_ = self.cli("verify", self.VERIFY)
        self.assertEqual(code, 0, out)

    def test_gate_blocks_without_contract_or_verification(self):
        self.seed_project()
        code, out, *_ = self.cli("gate")
        self.assertEqual(code, 1)
        self.assertIn("VERATUM COMPLETION GATE BLOCKED", out)
        self.assertIn("No active contract", out)
        self.lock()
        code, out, *_ = self.cli("gate")
        self.assertEqual(code, 1)
        self.assertIn("No passing verification", out)

    def test_gate_passes_with_fresh_evidence_and_closes_contract(self):
        self.edit_and_verify()
        ledger = self.json_file(".veratum/ledger.json")
        self.assertEqual(ledger["status"], "PASSED")
        self.assertRegex(ledger["tree_hash"], r"^[0-9a-f]{64}$")
        code, out, *_ = self.cli("gate")
        self.assertEqual(code, 0, out)
        self.assertIn("VERATUM EVIDENCE BLOCK", out)
        self.assertIn("src/math.ts", out)
        self.assertIn("src/app.ts", out)  # impact checked
        self.assertEqual(self.json_file(".veratum/contract.json")["status"], "COMPLETED")
        self.assertEqual(self.json_file(".veratum/brain.json")["task_history"][-1]["goal"], "change math")

    def test_post_verification_edit_is_blocked(self):
        """The Stale-Evidence vulnerability: verify passes, then a sneaky edit lands."""
        self.edit_and_verify()
        self.write("src/math.ts", "export const add = (a: number, b: number) => a - b;\n")
        code, out, *_ = self.cli("gate")
        self.assertEqual(code, 1)
        self.assertIn("POST-VERIFICATION EDIT DETECTED", out)
        self.assertIn("src/math.ts", out)
        # Reverting to the exact verified bytes restores the proof.
        self.write("src/math.ts", "export const add = (a: number, b: number) => a + b + 0;\n")
        self.assertEqual(self.cli("gate", "--dry-run")[0], 0)

    def test_single_byte_and_new_and_deleted_files_invalidate(self):
        self.edit_and_verify()
        self.write("src/math.ts", "export const add = (a: number, b: number) => a + b + 0; \n")
        self.assertEqual(self.cli("gate", "--dry-run")[0], 1)
        self.write("src/math.ts", "export const add = (a: number, b: number) => a + b + 0;\n")
        self.cli("contract", "--extend", "src/")
        self.cli("verify", self.VERIFY)
        self.write("src/new_untracked.ts", "export {}\n")
        self.assertEqual(self.cli("gate", "--dry-run")[0], 1)
        (self.tmp / "src" / "new_untracked.ts").unlink()
        self.assertEqual(self.cli("gate", "--dry-run")[0], 0)
        (self.tmp / "src" / "app.ts").unlink()
        self.assertEqual(self.cli("gate", "--dry-run")[0], 1)

    def test_staging_and_committing_do_not_invalidate(self):
        self.edit_and_verify()
        self.git("add", "-A")
        self.assertEqual(self.cli("gate", "--dry-run")[0], 0)
        self.git("commit", "-qm", "work")
        self.assertEqual(self.cli("gate", "--dry-run")[0], 0)

    def test_veratum_bookkeeping_does_not_invalidate(self):
        self.edit_and_verify()
        self.cli("remember", "math is pure")
        self.cli("checkpoint", "create")
        self.assertEqual(self.cli("gate", "--dry-run")[0], 0)

    def test_scope_drift_blocks(self):
        self.edit_and_verify()
        self.write("README.md", "changed outside scope\n")
        self.cli("verify", self.VERIFY)
        code, out, *_ = self.cli("gate")
        self.assertEqual(code, 1)
        self.assertIn("SCOPE DRIFT", out)
        self.assertIn("README.md", out)

    def test_wrong_verify_command_blocks(self):
        self.seed_project()
        self.lock(verify=self.VERIFY)
        self.write("src/math.ts", "export const add = 1;\n")
        self.cli("verify", "python -c \"pass\"")
        code, out, *_ = self.cli("gate")
        self.assertEqual(code, 1)
        self.assertIn("not the contracted verification", out)

    def test_status_reports_freshness(self):
        self.edit_and_verify()
        code, out, stdout, _ = self.cli("status", "--json")
        st = json.loads(stdout)
        self.assertTrue(st["evidence_fresh"])
        self.assertEqual(st["changed"], ["src/math.ts"])


class TestEvidenceIntegrity(VeratumTestCase):
    VERIFY = "python -c \"print('ok')\""

    def setUp(self):
        super().setUp()
        self.seed_project()
        self.lock(verify=self.VERIFY)
        self.write("src/math.ts", "export const add = 1;\n")
        self.assertEqual(self.cli("verify")[0], 0)

    def test_chain_is_intact_and_bound(self):
        code, out, *_ = self.cli("audit")
        self.assertEqual(code, 0, out)
        self.assertIn("bound to chained record", out)
        self.assertEqual(self.cli("gate", "--dry-run")[0], 0)

    def test_hand_forged_ledger_is_rejected(self):
        ledger = self.json_file(".veratum/ledger.json")
        # A FAILED run, then someone flips the ledger to PASSED by hand.
        ledger.update({"status": "PASSED", "exit_code": 0, "evidence_hash": "f" * 64})
        (self.tmp / ".veratum" / "ledger.json").write_text(json.dumps(ledger), encoding="utf-8")
        code, out, *_ = self.cli("gate")
        self.assertEqual(code, 1)
        self.assertIn("EVIDENCE INTEGRITY", out)

    def test_editing_the_chain_is_detected(self):
        log = self.tmp / ".veratum" / "logs" / "history.jsonl"
        lines = log.read_text(encoding="utf-8").splitlines()
        rec = json.loads(lines[0])
        rec["goal"] = "rewritten history"
        lines[0] = json.dumps(rec)
        log.write_text("\n".join(lines) + "\n", encoding="utf-8")
        code, out, *_ = self.cli("audit")
        self.assertEqual(code, 1)
        self.assertIn("modified", out)
        self.assertEqual(self.cli("gate")[0], 1)

    def test_ledger_fields_must_match_chain(self):
        ledger = self.json_file(".veratum/ledger.json")
        ledger["command"] = "true"
        (self.tmp / ".veratum" / "ledger.json").write_text(json.dumps(ledger), encoding="utf-8")
        code, out, *_ = self.cli("gate")
        self.assertEqual(code, 1)
        self.assertIn("EVIDENCE INTEGRITY", out)


class TestFailureGuards(VeratumTestCase):
    def test_duplicate_failure_and_same_failure_signature(self):
        self.seed_project()
        self.write("check.py", "import sys\nprint('Traceback (most recent call last):')\nprint('  File \"src/calc.py\", line 3, in f')\n"
                               "print('ValueError: bad input')\nsys.exit(1)\n")
        self.lock(files="src/,check.py", verify="python check.py", profile="balanced")
        self.assertEqual(self.cli("verify")[0], 1)
        code, out, *_ = self.cli("verify")
        self.assertEqual(code, 3, out)
        self.assertIn("DUPLICATE-FAILURE GUARD", out)
        self.write("src/math.ts", "export const add = 99;\n")  # code changed, cause untouched
        code, out, *_ = self.cli("verify")
        self.assertEqual(code, 1)
        self.assertIn("SAME FAILURE", out)
        self.assertIn("Retry budget exhausted", out)


class TestRiskProfiles(VeratumTestCase):
    def test_auto_profile_selection(self):
        self.seed_project()
        self.write("src/auth/session.ts", "export const s = 1;\n")
        out = self.lock(files="src/auth/session.ts")
        self.assertIn("Profile: highstakes", out)
        self.assertIn("checkpoint REQUIRED", out)
        out = self.lock(files="README.md")
        self.assertIn("Profile: eco", out)
        out = self.lock(files="src/math.ts,src/app.ts")
        self.assertIn("Profile: balanced", out)

    def test_highstakes_requires_checkpoint_and_single_retry(self):
        self.seed_project()
        self.write("db/migrations/001_add_email.sql", "ALTER TABLE users ADD email text;\n")
        self.lock(files="db/migrations/001_add_email.sql", verify="python -c \"import sys; sys.exit(1)\"")
        code, out, *_ = self.cli("check-scope", "db/migrations/001_add_email.sql")
        self.assertEqual(code, 1)
        self.assertIn("requires a shadow checkpoint", out)
        self.cli("checkpoint", "create")
        self.assertEqual(self.cli("check-scope", "db/migrations/001_add_email.sql")[0], 0)
        code, out, *_ = self.cli("verify")
        self.assertIn("attempt 1 of 1", out)
        self.assertIn("Retry budget exhausted", out)


class TestShellAnalyzer(unittest.TestCase):
    def a(self, cmd):
        return veratum_cli.analyze_shell(cmd, "/repo")

    def test_levels(self):
        cases = {
            "git status && ls -la | grep foo": "read",
            "npm test -- --watch=false": "exec",
            "curl -s https://example.com": "network",
            "echo hi > out.txt": "write",
            "pnpm add zod": "install",
            "git reset --hard HEAD~1": "destructive",
            "rm -rf build/": "destructive",
            "git push --force origin main": "destructive",
            "find . -name '*.tmp' -delete": "destructive",
            "bash -c 'git clean -fdx'": "destructive",
        }
        for cmd, level in cases.items():
            self.assertEqual(self.a(cmd)["level"], level, cmd)

    def test_write_targets(self):
        self.assertEqual(self.a("echo x >> logs/a.txt 2>&1")["writes"], ["/repo/logs/a.txt"])
        self.assertEqual(self.a("sed -i 's/a/b/g' src/x.py src/y.py")["writes"], ["/repo/src/x.py", "/repo/src/y.py"])
        self.assertEqual(self.a("cd pkg && touch new.ts")["writes"], ["/repo/pkg/new.ts"])
        self.assertEqual(self.a("cp a.txt 'my dir/b.txt'")["writes"], ["/repo/my dir/b.txt"])
        self.assertEqual(self.a("npm install left-pad")["writes"], ["/repo/package.json"])
        self.assertEqual(self.a("cat a.txt | tee -a b.txt > /dev/null")["writes"], ["/repo/b.txt"])
        self.assertEqual(self.a("cat src/a.py")["reads"], ["/repo/src/a.py"])
        self.assertEqual(self.a("python -c \"open('x','w').write('1')\"")["level"], "write")


class TestGateWithoutGit(TestGate):
    """The same guarantees hold in non-git workspaces via SHA-256 file walking."""
    use_git = False

    def test_staging_and_committing_do_not_invalidate(self):
        self.skipTest("git-only behaviour")


# ---------------------------------------------------------------------------
# Shadow checkpoints
# ---------------------------------------------------------------------------

class TestCheckpoint(VeratumTestCase):
    def test_checkpoint_and_rollback_restore_everything(self):
        self.seed_project()
        self.write("notes/untracked.txt", "keep me\n")
        self.lock(files="src/,notes/")
        before = veratum_cli.tree_hash(veratum_cli.snapshot(veratum_cli.Workspace(self.tmp)))
        code, out, *_ = self.cli("checkpoint", "create", "--label", "before refactor")
        self.assertEqual(code, 0, out)
        self.assertEqual(veratum_cli.tree_hash(veratum_cli.snapshot(veratum_cli.Workspace(self.tmp))), before,
                         "creating a checkpoint must not touch the worktree")
        # Wreck the workspace.
        self.write("src/math.ts", "BROKEN\n")
        (self.tmp / "src" / "app.ts").unlink()
        self.write("src/garbage.ts", "junk\n")
        self.write("notes/untracked.txt", "overwritten\n")
        code, out, *_ = self.cli("rollback")
        self.assertEqual(code, 0, out)
        self.assertIn("src/garbage.ts", out)
        self.assertEqual((self.tmp / "src" / "math.ts").read_text(), "export const add = (a: number, b: number) => a + b;\n")
        self.assertTrue((self.tmp / "src" / "app.ts").exists())
        self.assertFalse((self.tmp / "src" / "garbage.ts").exists())
        self.assertEqual((self.tmp / "notes" / "untracked.txt").read_text(), "keep me\n")
        self.assertEqual(veratum_cli.tree_hash(veratum_cli.snapshot(veratum_cli.Workspace(self.tmp))), before)
        self.assertTrue((self.tmp / ".veratum" / "brain.json").exists(), "rollback must never touch .veratum")
        # The pre-rollback state is itself recoverable.
        safety = [c for c in self.json_file(".veratum/state.json")["checkpoints"] if "pre-rollback" in c["label"]][-1]
        self.cli("rollback", safety["id"])
        self.assertEqual((self.tmp / "src" / "math.ts").read_text(), "BROKEN\n")
        self.assertTrue((self.tmp / "src" / "garbage.ts").exists())

    def test_co_change_history(self):
        self.write("src/price.ts", "export const p = 1;\n")
        self.write("src/price.test.ts", "test\n")
        self.write("docs/pricing.md", "a\n")
        self.git("add", "-A"); self.git("commit", "-qm", "c1")
        for i in range(3):
            self.write("src/price.ts", "export const p = {};\n".format(i + 2))
            self.write("src/price.test.ts", "test {}\n".format(i))
            self.git("add", "-A"); self.git("commit", "-qm", "c{}".format(i + 2))
        rep = veratum_cli.CodeIndex(veratum_cli.Workspace(self.tmp)).blast_radius("src/price.ts")
        self.assertEqual(rep["co_changed"][0]["file"], "src/price.test.ts")
        self.assertIn("src/price.test.ts", rep["tests"])

    def test_checkpoint_ref_is_hidden_and_list_works(self):
        self.seed_project()
        self.cli("checkpoint", "create", "--label", "x")
        refs = self.git("for-each-ref", "refs/veratum/")
        self.assertIn("refs/veratum/checkpoints/cp-", refs)
        self.assertEqual(self.git("stash", "list").strip(), "", "checkpoints must not pollute git stash")
        self.assertEqual(self.git("branch", "--list").count("\n"), 1)
        code, out, *_ = self.cli("checkpoint", "list")
        self.assertIn("cp-", out)

    def test_checkpoint_without_head_commit(self):
        self.write("a.txt", "1\n")
        self.cli("init")
        self.assertEqual(self.cli("checkpoint", "create")[0], 0)
        self.write("a.txt", "2\n")
        self.assertEqual(self.cli("rollback")[0], 0)
        self.assertEqual((self.tmp / "a.txt").read_text(), "1\n")


# ---------------------------------------------------------------------------
# IDE hooks
# ---------------------------------------------------------------------------

class TestHooks(VeratumTestCase):
    VERIFY = "python -c \"print('ok')\""

    def claude_edit(self, path: str, event: str = "PreToolUse") -> dict:
        return {"session_id": "s1", "hook_event_name": event, "cwd": str(self.tmp), "tool_name": "Edit",
                "tool_input": {"file_path": str(self.tmp / path), "old_string": "a", "new_string": "b"}}

    def read_file(self, path: str):
        payload = {"session_id": "s1", "hook_event_name": "PostToolUse", "cwd": str(self.tmp), "tool_name": "Read",
                   "tool_input": {"file_path": str(self.tmp / path)}}
        self.assertEqual(self.hook("post-tool", payload)[0], 0)

    def bash(self, cmd: str) -> dict:
        return {"session_id": "s1", "hook_event_name": "PreToolUse", "cwd": str(self.tmp), "tool_name": "Bash",
                "tool_input": {"command": cmd}}

    def test_read_before_write_and_stale_read(self):
        self.seed_project()
        self.lock(files="src/math.ts,src/app.ts", verify=self.VERIFY, profile="balanced")
        code, _, err = self.hook("pre-tool", self.claude_edit("src/math.ts"))
        self.assertEqual(code, 2)
        self.assertIn("READ-BEFORE-WRITE", err)
        self.read_file("src/math.ts")
        self.assertEqual(self.hook("pre-tool", self.claude_edit("src/math.ts"))[0], 0)
        # The agent's own edit keeps its view fresh …
        self.write("src/math.ts", "export const add = 41;\n")
        self.hook("post-tool", self.claude_edit("src/math.ts", "PostToolUse"))
        self.assertEqual(self.hook("pre-tool", self.claude_edit("src/math.ts"))[0], 0)
        # … but a change made behind its back (formatter, other process) makes the read stale.
        self.write("src/math.ts", "export const add = 42; // changed elsewhere\n")
        code, _, err = self.hook("pre-tool", self.claude_edit("src/math.ts"))
        self.assertEqual(code, 2)
        self.assertIn("STALE READ", err)
        # `cat` through the shell also counts as reading.
        self.hook("post-tool", dict(self.bash("cat src/math.ts"), hook_event_name="PostToolUse"))
        self.assertEqual(self.hook("pre-tool", self.claude_edit("src/math.ts"))[0], 0)
        # New files need no prior read.
        self.cli("contract", "--extend", "src/new.ts")
        self.assertEqual(self.hook("pre-tool", self.claude_edit("src/new.ts"))[0], 0)

    def test_shell_guard_blocks_out_of_scope_writes_before_they_run(self):
        self.seed_project()
        self.lock(files="src/math.ts", profile="eco")
        for cmd in ("echo hi > README.md", "sed -i 's/a/b/' README.md", "cp src/math.ts docs/copy.ts",
                    "cd src && echo x > app.ts", "bash -c \"echo x >> README.md\"", "npm install left-pad"):
            code, _, err = self.hook("pre-tool", self.bash(cmd))
            self.assertEqual(code, 2, cmd)
            self.assertIn("SCOPE GUARD", err, cmd)
        for cmd in ("echo hi > src/math.ts", "cat README.md | grep demo", "git status && git diff",
                    "echo log > node_modules/x.log", "npm test", "python -c \"print(1)\" 2>&1 | tail -5"):
            self.write(".gitignore", "node_modules/\n")
            self.assertEqual(self.hook("pre-tool", self.bash(cmd))[0], 0, cmd)

    def test_plan_mode_action_lock(self):
        self.seed_project()
        code, out, *_ = self.cli("contract", "--goal", "plan the refactor", "--files", "src/", "--mode", "plan")
        self.assertEqual(code, 0, out)
        self.assertIn("ACTION LOCK", out)
        self.read_file("src/math.ts")
        code, _, err = self.hook("pre-tool", self.claude_edit("src/math.ts"))
        self.assertEqual(code, 2)
        self.assertIn("ACTION LOCK", err)
        self.assertEqual(self.hook("pre-tool", self.bash("echo x > src/math.ts"))[0], 2)
        self.assertEqual(self.hook("pre-tool", self.bash("git log --oneline"))[0], 0)
        stop = {"hook_event_name": "Stop", "stop_hook_active": False}
        self.assertEqual(self.hook("stop", stop)[0], 0)
        self.assertEqual(self.json_file(".veratum/contract.json")["status"], "ACTIVE", "plan contracts survive turns")
        self.cli("contract", "--mode", "implement")
        self.assertEqual(self.hook("pre-tool", self.claude_edit("src/math.ts"))[0], 0)

    def test_claude_pre_tool_blocks_without_contract_and_out_of_scope(self):
        self.seed_project()
        code, _, err = self.hook("pre-tool", self.claude_edit("src/math.ts"))
        self.assertEqual(code, 2)
        self.assertIn("No active Veratum contract", err)
        self.lock()
        self.read_file("src/math.ts")
        self.assertEqual(self.hook("pre-tool", self.claude_edit("src/math.ts"))[0], 0)
        code, _, err = self.hook("pre-tool", self.claude_edit("src/app.ts"))
        self.assertEqual(code, 2)
        self.assertIn("OUTSIDE the active contract", err)
        # MultiEdit-style and non-edit tools
        self.assertEqual(self.hook("pre-tool", {"hook_event_name": "PreToolUse", "tool_name": "Read",
                                                "tool_input": {"file_path": str(self.tmp / "src/app.ts")}})[0], 0)

    def test_tamper_and_destructive_git_guards(self):
        self.seed_project()
        self.lock()
        bash = lambda cmd: {"hook_event_name": "PreToolUse", "tool_name": "Bash", "tool_input": {"command": cmd}}  # noqa: E731
        code, _, err = self.hook("pre-tool", bash("echo '{\"status\":\"PASSED\"}' > .veratum/ledger.json"))
        self.assertEqual(code, 2)
        self.assertIn("TAMPER", err)
        self.assertEqual(self.hook("pre-tool", bash("cat .veratum/ledger.json"))[0], 0)
        code, _, err = self.hook("pre-tool", bash("git reset --hard HEAD"))
        self.assertEqual(code, 2)
        self.assertIn("checkpoint", err)
        self.cli("checkpoint", "create")
        self.assertEqual(self.hook("pre-tool", bash("git reset --hard HEAD"))[0], 0)

    def test_post_tool_invalidates_ledger_after_verification(self):
        self.seed_project()
        self.lock(verify=self.VERIFY)
        self.write("src/math.ts", "export const add = 2;\n")
        self.cli("verify", self.VERIFY)
        self.assertEqual(self.json_file(".veratum/ledger.json")["status"], "PASSED")
        self.write("src/math.ts", "export const add = 3;\n")
        code, _, err = self.hook("post-tool", self.claude_edit("src/math.ts", "PostToolUse"))
        self.assertEqual(code, 2)
        self.assertIn("invalidated", err)
        ledger = self.json_file(".veratum/ledger.json")
        self.assertEqual(ledger["status"], "STALE")
        self.assertIn("src/math.ts", ledger["stale_reason"])
        self.assertIn("src/math.ts", self.json_file(".veratum/contract.json")["touched"])

    def test_post_tool_reports_shell_scope_drift_once(self):
        self.seed_project()
        self.lock()
        self.write("README.md", "sed -i changed this\n")
        payload = {"hook_event_name": "PostToolUse", "tool_name": "Bash", "tool_input": {"command": "sed -i s/a/b/ README.md"}}
        code, _, err = self.hook("post-tool", payload)
        self.assertEqual(code, 2)
        self.assertIn("SCOPE DRIFT", err)
        self.assertEqual(self.hook("post-tool", payload)[0], 0, "drift is reported once, not on every command")

    def test_claude_stop_gate(self):
        self.seed_project()
        stop = {"hook_event_name": "Stop", "stop_hook_active": False, "cwd": str(self.tmp)}
        self.assertEqual(self.hook("stop", stop)[0], 0, "no contract → nothing to gate")
        self.lock(verify=self.VERIFY)
        self.assertEqual(self.hook("stop", stop)[0], 0, "contract but no changes yet → allow")
        self.write("src/math.ts", "export const add = 5;\n")
        code, _, err = self.hook("stop", stop)
        self.assertEqual(code, 2)
        self.assertIn("VERATUM COMPLETION GATE BLOCKED", err)
        self.cli("verify", self.VERIFY)
        code, out, _ = self.hook("stop", stop)
        self.assertEqual(code, 0)
        self.assertIn("EVIDENCE BLOCK", out)
        self.assertEqual(self.json_file(".veratum/contract.json")["status"], "COMPLETED")

    def test_stop_gate_circuit_breaker(self):
        self.seed_project()
        self.lock(verify=self.VERIFY)
        self.write("src/math.ts", "export const add = 6;\n")
        stop = {"hook_event_name": "Stop", "stop_hook_active": True}
        codes = [self.hook("stop", stop)[0] for _ in range(4)]
        self.assertEqual(codes, [2, 2, 2, 0])
        self.assertIn("gate_overridden", self.json_file(".veratum/ledger.json"))

    def test_antigravity_protocol_via_plugin_scripts(self):
        self.seed_project()
        engine_dir = self.tmp / ".veratum" / "engine"
        engine_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy(ENGINE, engine_dir / "veratum_cli.py")
        hooks = REPO / "adapters" / "antigravity" / "hooks"
        payload = {"toolCall": {"name": "write_to_file", "args": {"TargetFile": str(self.tmp / "src/app.ts")}},
                   "workspacePaths": [str(self.tmp)], "conversationId": "c1"}
        code, out, _ = self.hook("", payload, script=hooks / "pre_edit.py")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["decision"], "deny")
        self.lock(files="src/app.ts", verify=self.VERIFY)
        code, out, _ = self.hook("", payload, script=hooks / "pre_edit.py")
        self.assertEqual(json.loads(out)["decision"], "allow")
        self.write("src/app.ts", "console.log(1);\n")
        code, out, _ = self.hook("", {"workspacePaths": [str(self.tmp)]}, script=hooks / "completion_gate.py")
        self.assertEqual(json.loads(out)["decision"], "continue")
        self.cli("verify", self.VERIFY)
        code, out, _ = self.hook("", {"workspacePaths": [str(self.tmp)]}, script=hooks / "completion_gate.py")
        self.assertEqual(json.loads(out)["decision"], "allow")

    def test_cursor_protocol(self):
        self.seed_project()
        self.lock(verify=self.VERIFY)
        self.write("src/math.ts", "export const add = 7;\n")
        code, out, _ = self.hook("stop", {"workspace_roots": [str(self.tmp)], "status": "completed"}, host="cursor")
        self.assertEqual(code, 0)
        self.assertIn("followup_message", json.loads(out))

    def test_session_start_injects_brain(self):
        self.seed_project()
        self.cli("remember", "Use pnpm, never npm", "--kind", "pitfall")
        code, out, _ = self.hook("session-start", {"hook_event_name": "SessionStart", "source": "startup"})
        self.assertEqual(code, 0)
        self.assertIn("[VERATUM BRAIN]", out)
        self.assertIn("Use pnpm, never npm", out)

    def test_auto_update_checker(self):
        self.seed_project()
        ws = veratum_cli.Workspace(self.tmp)
        # Test simulated newer version fetch
        res = veratum_cli.check_auto_update(ws, force=True, fetcher=lambda: "v2.0.0")
        self.assertTrue(res["update_available"])
        self.assertEqual(res["latest_version"], "2.0.0")
        self.assertTrue(res["last_success"])
        self.assertIn("update_command", res)
        ctx = veratum_cli.brain_context(ws)
        self.assertIn("[VERATUM UPDATE AVAILABLE]", ctx)
        self.assertIn("v2.0.0", ctx)
        self.assertIn(res["update_command"], ctx)

        # Test simulated offline failure: must not raise and must apply 6h backoff
        fail_calls = [0]
        def failing_fetcher():
            fail_calls[0] += 1
            raise OSError("No route to host")

        fail_res = veratum_cli.check_auto_update(ws, force=True, fetcher=failing_fetcher)
        self.assertFalse(fail_res["last_success"])
        self.assertEqual(fail_calls[0], 1)
        # Previous version remains preserved
        self.assertEqual(fail_res["latest_version"], "2.0.0")
        self.assertTrue(fail_res["update_available"])

        # Second call within 6 hours must return cached failure without calling fetcher again
        cached_res = veratum_cli.check_auto_update(ws, force=False, fetcher=failing_fetcher)
        self.assertEqual(fail_calls[0], 1, "Must not retry when within failure backoff window")
        self.assertFalse(cached_res["last_success"])

    def test_engine_and_skills_in_sync(self):
        """Pre-commit sync assertion: skills/veratum/scripts/ must match engine/ byte-for-byte."""
        engine_dir = REPO / "engine"
        skills_dir = REPO / "skills" / "veratum" / "scripts"
        self.assertTrue(engine_dir.is_dir(), "engine/ must exist")
        self.assertTrue(skills_dir.is_dir(), "skills/veratum/scripts/ must exist")
        for src in engine_dir.iterdir():
            if src.is_file() and src.suffix == ".py":
                skill_file = skills_dir / src.name
                self.assertTrue(skill_file.is_file(), "Missing mirrored file {}".format(skill_file))
                src_text = src.read_text(encoding="utf-8").replace("\r\n", "\n")
                skill_text = skill_file.read_text(encoding="utf-8").replace("\r\n", "\n")
                self.assertEqual(src_text, skill_text,
                                 "skills/veratum/scripts/{} is out of sync with engine/{}. Run `npm run build`.".format(src.name, src.name))

    def test_hooks_are_inert_without_veratum(self):
        code, out, err = self.hook("pre-tool", {"hook_event_name": "PreToolUse", "tool_name": "Write",
                                                "tool_input": {"file_path": str(self.tmp / "x.txt")}})
        self.assertEqual(code, 0, err)


# ---------------------------------------------------------------------------
# MCP server
# ---------------------------------------------------------------------------

class TestMcpServer(VeratumTestCase):
    def rpc(self, messages: list) -> list:
        payload = "".join(json.dumps(m) + "\n" for m in messages)
        proc = subprocess.run([sys.executable, str(MCP), "--root", str(self.tmp)], input=payload.encode("utf-8"),
                              capture_output=True, timeout=120)
        self.assertEqual(proc.returncode, 0, proc.stderr.decode("utf-8", "replace"))
        return [json.loads(line) for line in proc.stdout.decode("utf-8").splitlines() if line.strip()]

    def call(self, i: int, name: str, args: dict) -> dict:
        return {"jsonrpc": "2.0", "id": i, "method": "tools/call", "params": {"name": name, "arguments": args}}

    def test_handshake_and_tool_listing(self):
        self.seed_project()
        replies = self.rpc([
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}}},
            {"jsonrpc": "2.0", "method": "notifications/initialized"},
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
            {"jsonrpc": "2.0", "id": 3, "method": "nope"},
            {"jsonrpc": "2.0", "id": 4, "method": "ping"},
        ])
        self.assertEqual([r["id"] for r in replies], [1, 2, 3, 4], "notifications must not get a reply")
        self.assertEqual(replies[0]["result"]["protocolVersion"], "2025-06-18")
        self.assertEqual(replies[0]["result"]["serverInfo"]["name"], "veratum")
        names = {t["name"] for t in replies[1]["result"]["tools"]}
        self.assertTrue({"veratum_get_brain", "veratum_lock_contract", "veratum_verify", "veratum_check_gate",
                         "veratum_impact", "veratum_checkpoint", "veratum_check_scope", "veratum_remember"}.issubset(names))
        self.assertEqual(replies[2]["error"]["code"], -32601)

    def test_full_protocol_over_mcp(self):
        self.seed_project()
        verify = "python -c \"print('ok')\""
        replies = self.rpc([
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2024-11-05"}},
            self.call(2, "veratum_get_brain", {}),
            self.call(3, "veratum_lock_contract", {"goal": "mcp change", "files": ["src/math.ts"], "verify": verify}),
            self.call(4, "veratum_check_gate", {}),
        ])
        self.assertIn("[VERATUM BRAIN]", replies[1]["result"]["content"][0]["text"])
        self.assertIn("src/app.ts", replies[2]["result"]["content"][0]["text"])
        self.assertTrue(replies[3]["result"]["isError"])
        self.assertIn("BLOCKED", replies[3]["result"]["content"][0]["text"])
        self.write("src/math.ts", "export const add = 9;\n")
        replies = self.rpc([
            self.call(5, "veratum_check_scope", {"file": "src/app.ts"}),
            self.call(6, "veratum_verify", {}),
            self.call(7, "veratum_check_gate", {}),
        ])
        self.assertTrue(replies[0]["result"]["isError"])
        self.assertFalse(replies[1]["result"]["isError"], replies[1])
        self.assertFalse(replies[2]["result"]["isError"], replies[2])
        self.assertIn("EVIDENCE BLOCK", replies[2]["result"]["content"][0]["text"])

    def test_parse_error(self):
        proc = subprocess.run([sys.executable, str(MCP), "--root", str(self.tmp)], input=b"{not json\n",
                              capture_output=True, timeout=60)
        self.assertEqual(json.loads(proc.stdout.decode())["error"]["code"], -32700)


# ---------------------------------------------------------------------------
# Node installer
# ---------------------------------------------------------------------------

IDE_ENV_VARS = ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "CURSOR_TRACE_ID", "CURSOR_AGENT",
                "ANTIGRAVITY_AGENT", "ANTIGRAVITY", "OPENCODE", "OPENCODE_BIN_PATH", "CLAUDE_PROJECT_DIR")


@unittest.skipUnless(HAS_NODE, "node not available")
class TestInstaller(VeratumTestCase):
    def node(self, *args):
        env = {k: v for k, v in os.environ.items() if k not in IDE_ENV_VARS}
        proc = subprocess.run(["node", str(REPO / "bin" / "veratum.js"), *args], cwd=self.tmp,
                              capture_output=True, timeout=180, env=env)
        return proc.returncode, proc.stdout.decode("utf-8", "replace") + proc.stderr.decode("utf-8", "replace")

    def test_init_without_ide_fails_with_per_ide_commands(self):
        code, out = self.node("init")
        self.assertEqual(code, 1)
        self.assertIn("npx github:yadavmandeep/Veratum init --ide cursor", out)
        self.assertFalse((self.tmp / ".cursor").exists())

    def test_init_autodetects_ide_from_project(self):
        (self.tmp / ".cursor").mkdir()
        code, out = self.node("init")
        self.assertEqual(code, 0, out)
        self.assertTrue((self.tmp / ".cursor" / "rules" / "veratum.mdc").exists())
        self.assertFalse((self.tmp / "CLAUDE.md").exists(), "only the detected IDE is installed")
        self.assertEqual(self.json_file(".veratum/config.json")["installed_adapters"], ["cursor"])

    def test_uninstall_keeps_user_content(self):
        self.write("CLAUDE.md", "# Mine\n")
        self.write(".claude/settings.json", json.dumps({"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "echo mine"}]}]}}))
        self.assertEqual(self.node("init", "--ide", "claude-code", "--ide", "cursor")[0], 0)
        code, out = self.node("uninstall", "--ide", "cursor")
        self.assertEqual(code, 0, out)
        self.assertFalse((self.tmp / ".cursor").exists())
        self.assertIn("veratum:start", (self.tmp / "CLAUDE.md").read_text(encoding="utf-8"))
        self.assertEqual(self.json_file(".veratum/config.json")["installed_adapters"], ["claude-code"])
        code, out = self.node("uninstall", "--all", "--purge")
        self.assertEqual(code, 0, out)
        self.assertFalse((self.tmp / ".veratum").exists())
        self.assertEqual((self.tmp / "CLAUDE.md").read_text(encoding="utf-8").strip(), "# Mine")
        self.assertEqual(self.json_file(".claude/settings.json"),
                         {"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "echo mine"}]}]}})
        self.assertNotIn("veratum", (self.tmp / ".gitignore").read_text(encoding="utf-8") if (self.tmp / ".gitignore").exists() else "")

    def test_npx_config_command(self):
        self.assertEqual(self.node("init", "--ide", "claude-code")[0], 0)
        code, out = self.node("config", "graph_auto", "off")
        self.assertEqual(code, 0, out)
        self.assertEqual(self.json_file(".veratum/config.json")["graph_auto"], "off")
        code, out = self.node("config", "enforcement", "off")
        self.assertNotEqual(code, 0)
        self.assertEqual(self.json_file(".veratum/config.json")["enforcement"], "strict")

    def test_slash_command_installed_and_removed_per_ide(self):
        patterns = {"claude-code": ".claude/commands/{}.md", "cursor": ".cursor/commands/{}.md",
                    "opencode": ".opencode/command/{}.md", "copilot": ".github/prompts/{}.prompt.md",
                    "windsurf": ".windsurf/workflows/{}.md", "antigravity": ".agents/workflows/{}.md"}
        names = ("veratum",)  # ONE command with one grammar: /veratum <area> <action> [arguments]
        files = {(ide, name): pat.format(name) for ide, pat in patterns.items() for name in names}
        self.write(".claude/commands/mine.md", "my own command\n")
        code, out = self.node("init", "--all")
        self.assertEqual(code, 0, out)
        self.assertIn("/veratum graph build", out)  # the install summary teaches the short commands
        self.assertIn("/veratum graph query", out)
        self.assertIn("/veratum status", out)
        self.assertNotIn(".veratum/engine/veratum_cli.py doctor", out)
        self.assertEqual(sorted(p.name for p in (self.tmp / ".claude/commands").iterdir()), ["mine.md", "veratum.md"])
        for (ide, name), rel in files.items():
            text = (self.tmp / rel).read_text(encoding="utf-8")
            for sub in ("graph build", "graph query", "graph export", "impact <file>", "config"):
                self.assertIn(sub, text, (ide, sub))
            self.assertNotIn("{{ARGS}}", text, (ide, name))
        claude_graph = (self.tmp / files[("claude-code", "veratum")]).read_text(encoding="utf-8")
        self.assertIn("$ARGUMENTS", claude_graph)
        self.assertTrue(claude_graph.startswith("---\n"))
        self.assertIn("argument-hint", claude_graph)
        self.assertFalse((self.tmp / ".clinerules").is_dir())  # Cline keeps its single rules file
        self.write("app.py", "def login(user):\n    return user\n")
        code, out = self.node("graph", "query", "login")  # the `python .veratum/engine/veratum_cli.py graph ...` form the README shows
        self.assertEqual(code, 0, out)
        self.assertIn("NODE login (function)", out)
        self.assertEqual(self.node("update")[0], 0)  # idempotent
        self.assertEqual(self.node("uninstall", "--all")[0], 0)
        for rel in files.values():
            self.assertFalse((self.tmp / rel).exists(), rel)
        self.assertEqual((self.tmp / ".claude/commands/mine.md").read_text(encoding="utf-8"), "my own command\n")

    def test_init_installs_all_adapters_idempotently(self):
        self.write("CLAUDE.md", "# My project rules\nKeep me.\n")
        self.write(".claude/settings.json", json.dumps({"hooks": {"Stop": [{"hooks": [{"type": "command", "command": "echo mine"}]}]}}))
        self.write(".gitignore", "node_modules/\n")
        code, out = self.node("init", "--all")
        self.assertEqual(code, 0, out)
        code, out = self.node("update")  # second run must not duplicate anything
        self.assertEqual(code, 0, out)
        for rel in [".veratum/engine/veratum_cli.py", ".veratum/engine/veratum_graph.py",
                    ".veratum/engine/veratum_export.py", ".veratum/engine/mcp_server.py", ".veratum/brain.json",
                    ".agents/skills/veratum/SKILL.md", ".agents/plugins/veratum/hooks/pre_edit.py",
                    ".cursor/rules/veratum.mdc", ".cursor/mcp.json", ".cursor/hooks.json", ".windsurfrules",
                    ".clinerules", ".github/copilot-instructions.md", ".vscode/mcp.json", "AGENTS.md",
                    "opencode.json", ".opencode/plugin/veratum.js"]:
            self.assertTrue((self.tmp / rel).exists(), rel)
        claude_md = (self.tmp / "CLAUDE.md").read_text(encoding="utf-8")
        self.assertIn("Keep me.", claude_md)
        self.assertEqual(claude_md.count("veratum:start"), 1)
        settings = self.json_file(".claude/settings.json")
        self.assertEqual(len(settings["hooks"]["Stop"]), 2, "user hook kept + one veratum hook")
        self.assertIn("echo mine", json.dumps(settings["hooks"]["Stop"]))
        mine = [e["matcher"] for e in settings["hooks"]["PreToolUse"] if "veratum_cli.py" in json.dumps(e)]
        self.assertEqual(sorted(mine), ["Edit|Write|MultiEdit|NotebookEdit|Bash", "Glob|Grep"], "one entry per matcher, no duplicates")
        gitignore = (self.tmp / ".gitignore").read_text(encoding="utf-8")
        self.assertIn("node_modules/", gitignore)
        self.assertIn(".veratum/ledger.json", gitignore)
        self.assertNotIn(".veratum/brain.json", gitignore)
        self.assertEqual(gitignore.count(">>> veratum"), 1)
        self.assertIn("veratum", self.json_file(".cursor/mcp.json")["mcpServers"])
        cfg = self.json_file(".veratum/config.json")
        self.assertEqual(len(cfg["installed_adapters"]), 7)
        code, out = self.node("doctor")
        self.assertEqual(code, 0, out)
        self.assertIn("Health: 100%", out)

    def test_init_subset_of_ides(self):
        code, out = self.node("init", "--ides", "claude,cursor")
        self.assertEqual(code, 0, out)
        self.assertTrue((self.tmp / ".cursor" / "rules" / "veratum.mdc").exists())
        self.assertFalse((self.tmp / ".windsurfrules").exists())
        self.assertEqual(self.json_file(".veratum/config.json")["installed_adapters"], ["claude-code", "cursor"])

    def test_skills_sh_bundle_bootstraps_without_npm(self):
        """Simulates `npx skills add … --agent antigravity`: the skill folder alone is enough."""
        shutil.copytree(REPO / "skills" / "veratum", self.tmp / ".agents" / "skills" / "veratum")
        self.write("pyproject.toml", "[project]\nname='x'\n")
        script = self.tmp / ".agents" / "skills" / "veratum" / "scripts" / "veratum_cli.py"
        proc = subprocess.run([sys.executable, str(script), "init"], cwd=self.tmp, capture_output=True, timeout=120)
        self.assertEqual(proc.returncode, 0, proc.stderr.decode("utf-8", "replace"))
        self.assertTrue((self.tmp / ".veratum" / "engine" / "veratum_cli.py").is_file())
        self.assertTrue((self.tmp / ".veratum" / "engine" / "mcp_server.py").is_file())
        self.assertIn("python", self.json_file(".veratum/brain.json")["stack"])
        proc = subprocess.run([sys.executable, ".veratum/engine/veratum_cli.py", "doctor"], cwd=self.tmp, capture_output=True, timeout=120)
        self.assertEqual(proc.returncode, 0, proc.stdout.decode("utf-8", "replace"))
        self.assertIn("Health: 100%", proc.stdout.decode("utf-8", "replace"))

    def test_adapters_in_sync_with_core_skill(self):
        proc = subprocess.run(["node", str(REPO / "bin" / "veratum.js"), "build", "--check"], cwd=REPO, capture_output=True)
        self.assertEqual(proc.returncode, 0, proc.stdout.decode() + proc.stderr.decode())


class TestSkillPack(unittest.TestCase):
    """Every skill must be discoverable by the skills.sh CLI and follow the Agent Skills format."""

    def frontmatter(self, path: Path) -> dict:
        text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
        self.assertTrue(text.startswith("---\n"), path)
        block = text.split("---\n", 2)[1]
        data = {}
        for line in block.splitlines():
            key, _, value = line.partition(":")
            data[key.strip()] = value.strip()
        return data

    def test_pack_layout_and_frontmatter(self):
        self.assertFalse((REPO / "SKILL.md").exists(), "a root SKILL.md would hide skills/ from the skills CLI")
        self.assertFalse((REPO / "core" / "SKILL.md").exists(), "core/SKILL.md would shadow skills/veratum in the skills CLI")
        self.assertTrue((REPO / "core" / "SKILL.template.md").exists(), "core/SKILL.template.md must exist")
        skills = sorted(p.parent.name for p in (REPO / "skills").glob("*/SKILL.md"))
        self.assertEqual(skills, ["veratum", "veratum-debug", "veratum-highstakes", "veratum-python",
                                  "veratum-refactor", "veratum-review", "veratum-typescript"])
        for name in skills:
            fm = self.frontmatter(REPO / "skills" / name / "SKILL.md")
            self.assertEqual(fm.get("name"), name)
            self.assertRegex(name, r"^[a-z0-9]+(-[a-z0-9]+)*$")
            self.assertLessEqual(len(name), 64)
            self.assertTrue(0 < len(fm.get("description", "")) <= 1024, name)

    def test_core_skill_bundles_engine(self):
        for name in veratum_cli.ENGINE_FILES:
            bundled = (REPO / "skills" / "veratum" / "scripts" / name).read_bytes().replace(b"\r\n", b"\n")
            source = (REPO / "engine" / name).read_bytes().replace(b"\r\n", b"\n")
            self.assertEqual(bundled, source, "run `node bin/veratum.js build`")


if __name__ == "__main__":
    unittest.main(verbosity=2)
