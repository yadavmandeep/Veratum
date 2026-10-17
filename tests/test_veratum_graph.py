"""Tests for the Veratum knowledge graph (graph build / query / path / explain / report)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import unittest

from test_veratum_engine import HAS_NODE, REPO, VeratumTestCase, veratum_cli  # also puts engine/ on sys.path

import veratum_export  # noqa: E402

veratum_graph = veratum_cli._graph_module()


class TestModuleSplit(unittest.TestCase):
    def test_graph_shares_the_cli_types(self):
        self.assertIs(veratum_graph.VeratumError, veratum_cli.VeratumError)
        self.assertIs(veratum_graph.CodeIndex, veratum_cli.CodeIndex)
        self.assertIs(veratum_cli._graph_module(), veratum_graph)  # bound once, reused

    def test_every_bound_name_exists_in_the_cli(self):
        for name in veratum_graph._CORE_NAMES:
            self.assertTrue(hasattr(veratum_cli, name), name)

    def test_cli_no_longer_carries_graph_code(self):
        for name in ("graph_build", "graph_query", "graph_louvain", "graph_export_html", "graph_watch"):
            self.assertFalse(hasattr(veratum_cli, name), name)

    def test_engine_files_are_all_listed(self):
        self.assertEqual(set(veratum_cli.ENGINE_FILES),
                         {"veratum_cli.py", "veratum_graph.py", "veratum_export.py", "mcp_server.py"})

    def test_missing_graph_module_gives_a_clear_error(self):
        import builtins
        real = builtins.__import__

        def blocked(name, *a, **k):
            if name == "veratum_graph":
                raise ImportError(name)
            return real(name, *a, **k)

        builtins.__import__ = blocked
        try:
            with self.assertRaises(veratum_cli.VeratumError) as ctx:
                veratum_cli._graph_module()
        finally:
            builtins.__import__ = real
        self.assertIn("npx github:yadavmandeep/Veratum update", str(ctx.exception))


class GraphCase(VeratumTestCase):
    use_git = False

    def project(self):
        self.write("app/billing.py", "def charge(amount):\n    return audit(amount)\n\n\ndef audit(x):\n    return x\n")
        self.write("app/api.py", "from app.billing import charge\n\n\ndef checkout(cart):\n    return charge(cart)\n")
        self.write("app/cli.py", "from app.api import checkout\n\n\ndef main():\n    checkout(1)\n")
        self.write("web/ui.ts", "import { fmt } from './fmt';\nexport function render() {\n  return fmt(1);\n}\n")
        self.write("web/fmt.ts", "export function fmt(n: number) { return String(n); }\n")
        self.write("lonely.py", "VALUE = 1\n")

    def build(self, *extra):
        code, out, stdout, _ = self.cli("graph", "build", *extra)
        self.assertEqual(code, 0, out)
        return stdout

    def graph(self):
        return json.loads((self.tmp / ".veratum/graph/graph.json").read_text(encoding="utf-8"))

    def edge(self, g, src, rel, dst):
        ids = {n["id"]: n for n in g["nodes"]}
        for e in g["edges"]:
            if e["relation"] == rel and ids[e["source"]]["label"] == src and ids[e["target"]]["label"] == dst:
                return e
        raise AssertionError("missing {} {} {}".format(src, rel, dst))


class TestGraphBuild(GraphCase):
    def test_outputs_and_schema(self):
        self.project()
        self.build()
        for name in ("graph.json", "GRAPH_REPORT.md", "cache.json"):
            self.assertTrue((self.tmp / ".veratum/graph" / name).exists(), name)
        g = self.graph()
        self.assertEqual(veratum_graph.validate_graph(g), [])
        self.assertEqual(g["stats"]["files"], 6)

    def test_every_edge_is_grounded(self):
        self.project()
        self.build()
        for e in self.graph()["edges"]:
            self.assertTrue(e["source_file"] and e["source_location"].startswith("L"), e)
            self.assertIn(e["confidence"], ("EXTRACTED", "INFERRED", "AMBIGUOUS"))

    def test_import_edge_is_extracted_with_line(self):
        self.project()
        self.build()
        e = self.edge(self.graph(), "api.py", "imports", "billing.py")
        self.assertEqual((e["confidence"], e["source_location"]), ("EXTRACTED", "L1"))

    def test_call_edges_are_inferred_with_basis(self):
        self.project()
        self.build()
        g = self.graph()
        cross = self.edge(g, "checkout", "calls", "charge")
        self.assertEqual((cross["confidence"], cross["basis"], cross["source_location"]), ("INFERRED", "import-resolved", "L5"))
        same = self.edge(g, "charge", "calls", "audit")
        self.assertEqual(same["basis"], "same-file")
        ts = self.edge(g, "render", "calls", "fmt")
        self.assertEqual(ts["basis"], "import-resolved")

    def test_ambiguous_when_several_candidates(self):
        self.write("a/store.py", "def persist_record(x):\n    return x\n")
        self.write("b/store.py", "def persist_record(x):\n    return x\n")
        self.write("c/use.py", "def run():\n    persist_record(1)\n")
        self.build()
        amb = [e for e in self.graph()["edges"] if e["confidence"] == "AMBIGUOUS"]
        self.assertEqual(len(amb), 2)
        self.assertIn("review", (self.tmp / ".veratum/graph/GRAPH_REPORT.md").read_text(encoding="utf-8"))

    def test_incremental_cache_reuses_unchanged_files(self):
        self.project()
        self.build()
        self.write("lonely.py", "VALUE = 2\n")
        self.build()
        st = self.graph()["stats"]
        self.assertEqual((st["extracted_now"], st["from_cache"]), (1, 5))
        self.build("--full")
        self.assertEqual(self.graph()["stats"]["from_cache"], 0)

    def test_status_reports_stale_files(self):
        self.project()
        self.build()
        self.assertEqual(veratum_graph.graph_status(veratum_cli.Workspace(self.tmp))["stale_files"], [])
        self.write("app/cli.py", "def main():\n    pass\n")
        self.assertEqual(veratum_graph.graph_status(veratum_cli.Workspace(self.tmp))["stale_files"], ["app/cli.py"])

    def test_communities_group_connected_files(self):
        self.project()
        self.build()
        g = self.graph()
        by_id = {n["id"]: n["community"] for n in g["nodes"]}
        self.assertEqual(by_id["file:web/ui.ts"], by_id["file:web/fmt.ts"])
        self.assertEqual(by_id["file:app/api.py"], by_id["sym:app/api.py::checkout"])  # symbols follow their file
        # disconnected components can never share a community
        self.assertNotEqual(by_id["file:app/api.py"], by_id["file:web/ui.ts"])
        self.assertTrue(any(c["size"] == 1 for c in g["communities"]))  # lonely.py


class TestLouvain(unittest.TestCase):
    @staticmethod
    def adj(edges):
        out = {}
        for a, b, w in edges:
            out.setdefault(a, {})[b] = out.setdefault(a, {}).get(b, 0) + w
            out.setdefault(b, {})[a] = out.setdefault(b, {}).get(a, 0) + w
        return out

    def test_two_cliques_joined_by_a_bridge(self):
        left = [("a%d" % i, "a%d" % j, 1) for i in range(4) for j in range(i + 1, 4)]
        right = [("b%d" % i, "b%d" % j, 1) for i in range(4) for j in range(i + 1, 4)]
        part = veratum_graph.graph_louvain(self.adj(left + right + [("a0", "b0", 1)]))
        self.assertEqual(len({part["a%d" % i] for i in range(4)}), 1)
        self.assertEqual(len({part["b%d" % i] for i in range(4)}), 1)
        self.assertNotEqual(part["a0"], part["b0"])

    def test_deterministic_and_handles_empty(self):
        edges = [("x", "y", 1), ("y", "z", 1), ("z", "x", 1), ("p", "q", 1)]
        self.assertEqual(veratum_graph.graph_louvain(self.adj(edges)), veratum_graph.graph_louvain(self.adj(edges)))
        self.assertEqual(veratum_graph.graph_louvain({}), {})

    def test_oversized_community_is_split_by_cluster(self):
        nodes = {"n%d" % i: {"source_file": "f%d.py" % (i // 6)} for i in range(24)}
        edges = []
        for g in range(4):  # four dense groups chained together
            ids = ["n%d" % (g * 6 + k) for k in range(6)]
            edges += [{"source": a, "target": b, "relation": "imports"} for i, a in enumerate(ids) for b in ids[i + 1:]]
            if g:
                edges.append({"source": ids[0], "target": "n%d" % ((g - 1) * 6), "relation": "imports"})
        out = veratum_graph._graph_cluster(nodes, edges)
        self.assertGreaterEqual(len(out["list"]), 4)
        self.assertEqual(sum(c["size"] for c in out["list"]), 24)


class TestGraphBuildMore(GraphCase):
    def test_deterministic(self):
        self.project()
        self.build()
        first = self.graph()
        first.pop("built_at")
        self.build("--full")
        second = self.graph()
        second.pop("built_at")
        for g in (first, second):
            g["stats"].pop("extracted_now"), g["stats"].pop("from_cache")
        self.assertEqual(first, second)

    def test_syntax_error_file_falls_back(self):
        self.write("broken.py", "def ok(:\n    pass\ndef still_found():\n    pass\n")
        self.build()
        labels = {n["label"] for n in self.graph()["nodes"]}
        self.assertIn("still_found", labels)

    def test_graph_outside_fingerprint(self):
        self.project()
        before = veratum_cli.snapshot(veratum_cli.Workspace(self.tmp))
        self.build()
        after = veratum_cli.snapshot(veratum_cli.Workspace(self.tmp))
        self.assertEqual(veratum_cli.tree_hash(before), veratum_cli.tree_hash(after))


class TestGraphQuery(GraphCase):
    def setUp(self):
        super().setUp()
        self.project()
        self.build()

    def test_query_returns_grounded_subgraph(self):
        code, out, stdout, _ = self.cli("graph", "query", "charge")
        self.assertEqual(code, 0, out)
        self.assertIn("NODE charge (function) [src=app/billing.py loc=L1", stdout)
        self.assertIn("--calls [INFERRED import-resolved]-->", stdout)

    def test_query_respects_budget(self):
        code, out, stdout, _ = self.cli("graph", "query", "app", "--budget", "50", "--depth", "3")
        self.assertEqual(code, 0, out)
        self.assertLessEqual(len(stdout), 50 * 4 + 120)
        self.assertIn("truncated", stdout)

    def test_query_without_match(self):
        _, _, stdout, _ = self.cli("graph", "query", "zzzznothing")
        self.assertIn("No graph nodes match", stdout)

    def test_path_between_nodes(self):
        code, out, stdout, _ = self.cli("graph", "path", "main", "charge")
        self.assertEqual(code, 0, out)
        self.assertIn("main --calls", stdout)
        self.assertIn("charge", stdout.splitlines()[-1])
        _, _, none, _ = self.cli("graph", "path", "main", "fmt")
        self.assertIn("No path", none)

    def test_explain_lists_neighbours(self):
        _, _, stdout, _ = self.cli("graph", "explain", "charge")
        self.assertIn("<-- calls [INFERRED] checkout", stdout)
        self.assertIn("--> calls [INFERRED] audit", stdout)

    def test_report_sections(self):
        _, _, stdout, _ = self.cli("graph", "report")
        for header in ("## God nodes", "## Communities", "## Surprising connections", "## Ambiguous edges"):
            self.assertIn(header, stdout)

    def test_benchmark_and_missing_graph(self):
        _, _, stdout, _ = self.cli("graph", "benchmark", "charge", "--json")
        self.assertGreater(json.loads(stdout)["corpus_tokens"], 0)
        (self.tmp / ".veratum/graph/graph.json").unlink()
        code, out, stdout, _ = self.cli("graph", "query", "charge")  # auto mode rebuilds a missing graph
        self.assertEqual(code, 0, out)
        self.assertIn("NODE charge", stdout)
        (self.tmp / ".veratum/graph/graph.json").unlink()
        (self.tmp / ".veratum/config.json").write_text('{"graph_auto": "off"}', encoding="utf-8")
        code, out, _, _ = self.cli("graph", "query", "charge")
        self.assertNotEqual(code, 0)
        self.assertIn("graph build", out)

    def test_labels_are_sanitized(self):
        self.assertNotIn("\x1b", veratum_graph._graph_label("a\x1b[31mb\nc"))
        self.assertEqual(len(veratum_graph._graph_label("x" * 999)), 256)

    def test_invalid_graph_rejected(self):
        p = self.tmp / ".veratum/graph/graph.json"
        g = json.loads(p.read_text(encoding="utf-8"))
        g["edges"][0]["target"] = "ghost"
        p.write_text(json.dumps(g), encoding="utf-8")
        code, out, _, _ = self.cli("graph", "query", "charge")
        self.assertNotEqual(code, 0)
        self.assertIn("invalid", out)


class TestGraphDocsAndSemantic(GraphCase):
    def setUp(self):
        super().setUp()
        self.project()
        self.write("README.md", "# Shop\n\nSee [billing](app/billing.py) and `checkout()`.\n\n## Money\n\nUses `charge` and `audit`.\n\n```\n`ignored_in_fence`\n```\n")
        self.write("docs/spec.pdf", "%PDF-1.4 fake")
        self.build()

    def test_markdown_nodes_links_and_mentions(self):
        g = self.graph()
        labels = {n["label"] for n in g["nodes"] if n["kind"] == "section"}
        self.assertEqual(labels, {"Shop", "Money"})
        link = self.edge(g, "Shop", "references", "billing.py")
        self.assertEqual((link["confidence"], link["source_location"]), ("EXTRACTED", "L3"))
        mention = self.edge(g, "Shop", "mentions", "checkout")
        self.assertEqual((mention["confidence"], mention["basis"]), ("INFERRED", "doc-mention"))
        self.assertFalse(any("ignored_in_fence" in n["label"] for n in g["nodes"]))

    def test_assets_listed_as_pending_semantic(self):
        _, _, stdout, _ = self.cli("graph", "semantic", "list", "--json")
        pending = json.loads(stdout)
        self.assertIn("docs/spec.pdf", pending)
        self.assertEqual(self.graph()["stats"]["assets"], 1)

    def test_semantic_add_merges_and_is_never_extracted(self):
        payload = {"source_file": "docs/spec.pdf",
                   "nodes": [{"label": "Refund policy", "kind": "concept"}, {"label": "Invoice rules"}],
                   "edges": [{"source": "Refund policy", "target": "charge", "relation": "Governs!", "confidence": "EXTRACTED"},
                             {"source": "Refund policy", "target": "ghost-node", "relation": "x"}]}
        code, out, stdout, _ = self.cli("graph", "semantic", "add", "--data", json.dumps(payload))
        self.assertEqual(code, 0, out)
        g = self.graph()
        e = self.edge(g, "Refund policy", "governs", "charge")
        self.assertEqual((e["confidence"], e["basis"]), ("INFERRED", "semantic"))  # EXTRACTED is not accepted from LLM notes
        self.assertEqual(g["stats"]["semantic_files"], 1)
        self.assertEqual(g["stats"]["semantic_dropped_edges"], 1)
        _, _, stdout, _ = self.cli("graph", "semantic", "list", "--json")
        self.assertNotIn("docs/spec.pdf", json.loads(stdout))

    def test_semantic_rejects_outside_paths_and_goes_stale(self):
        code, out, _, _ = self.cli("graph", "semantic", "add", "--data", json.dumps({"source_file": "../evil.txt", "nodes": []}))
        self.assertNotEqual(code, 0)
        self.cli("graph", "semantic", "add", "--data", json.dumps({"source_file": "docs/spec.pdf", "nodes": [{"label": "Old"}]}))
        self.write("docs/spec.pdf", "%PDF-1.4 changed")
        self.build()
        self.assertEqual(self.graph()["stats"]["semantic_stale"], 1)
        self.assertNotIn("Old", {n["label"] for n in self.graph()["nodes"]})


class TestGraphExports(GraphCase):
    def setUp(self):
        super().setUp()
        self.project()
        self.build()

    def test_export_all_formats(self):
        code, out, stdout, _ = self.cli("graph", "export")
        self.assertEqual(code, 0, out)
        base = self.tmp / ".veratum/graph/export"
        html_text = (base / "graph.html").read_text(encoding="utf-8")
        self.assertIn("<svg", html_text)
        self.assertNotIn("http://cdn", html_text)
        self.assertNotIn("src=\"http", html_text)  # self-contained: no external requests
        self.assertIn("<line", (base / "graph.svg").read_text(encoding="utf-8"))
        cypher = (base / "graph.cypher").read_text(encoding="utf-8")
        self.assertIn("CREATE (:Node", cypher)
        self.assertIn("-[:IMPORTS {confidence: 'EXTRACTED'", cypher)
        note = (base / "obsidian" / "app__api.py.md").read_text(encoding="utf-8")
        self.assertIn("[[app__billing.py|billing.py]]", note)
        self.assertTrue((base / "obsidian" / "_Communities.md").exists())

    def test_export_escapes_hostile_labels(self):
        g = self.graph()
        g["nodes"][0]["label"] = "<script>alert(1)</script>'; DROP"
        self.assertNotIn("<script>alert", veratum_export.graph_export_svg(g))
        self.assertIn("\\'", veratum_export.graph_export_cypher(g))

    def test_export_out_must_stay_inside_workspace(self):
        code, out, _, _ = self.cli("graph", "export", "--format", "svg", "--out", "../outside")
        self.assertNotEqual(code, 0)
        code, out, stdout, _ = self.cli("graph", "export", "--format", "svg", "--out", "build/vis")
        self.assertEqual(code, 0, out)
        self.assertTrue((self.tmp / "build/vis/graph.svg").exists())

    def test_layout_is_deterministic(self):
        ids = ["a", "b", "c"]
        links = [{"source": "a", "target": "b"}, {"source": "b", "target": "c"}]
        self.assertEqual(veratum_export._graph_layout(ids, links), veratum_export._graph_layout(ids, links))


class TestGraphWatchAndAuto(GraphCase):
    def test_watch_rebuilds_after_an_edit(self):
        self.project()
        self.build()
        ws = veratum_cli.Workspace(self.tmp)
        calls = []

        def fake_sleep(_):
            calls.append(1)
            if len(calls) == 1:
                self.write("app/new_module.py", "def fresh_thing():\n    pass\n")

        said = []
        n = veratum_graph.graph_watch(ws, interval=0, debounce=0, cycles=3, sleep=fake_sleep, say=said.append)
        self.assertEqual(n, 1)
        self.assertIn("fresh_thing", {x["label"] for x in self.graph()["nodes"]})
        self.assertIn("rebuilt", said[0])

    def test_session_start_builds_then_refreshes(self):
        self.project()
        veratum_cli.initialize(veratum_cli.Workspace(self.tmp), quiet=True)
        env = {"VERATUM_ROOT": str(self.tmp)}
        code, out, stdout, _ = self.cli("hook", "session-start", stdin="{}", env=env)
        self.assertEqual(code, 0, out)
        self.assertTrue((self.tmp / ".veratum/graph/graph.json").exists())  # built automatically
        self.assertIn("Knowledge graph:", stdout)
        self.write("lonely.py", "VALUE = 3\n")
        self.cli("hook", "session-start", stdin="{}", env=env)
        self.assertEqual(self.graph()["stats"]["extracted_now"], 1)  # refreshed incrementally

    def test_auto_off_never_builds(self):
        self.project()
        veratum_cli.initialize(veratum_cli.Workspace(self.tmp), quiet=True)
        (self.tmp / ".veratum/config.json").write_text('{"graph_auto": "off"}', encoding="utf-8")
        self.cli("hook", "session-start", stdin="{}", env={"VERATUM_ROOT": str(self.tmp)})
        self.assertFalse((self.tmp / ".veratum/graph/graph.json").exists())

    def test_query_refreshes_stale_graph(self):
        self.project()
        self.build()
        self.write("app/extra.py", "def brand_new_function():\n    pass\n")
        _, _, stdout, _ = self.cli("graph", "query", "brand_new_function")
        self.assertIn("NODE brand_new_function", stdout)


class TestConfigCommand(GraphCase):
    def setUp(self):
        super().setUp()
        self.project()
        veratum_cli.initialize(veratum_cli.Workspace(self.tmp), quiet=True)

    def stored(self):
        return json.loads((self.tmp / ".veratum/config.json").read_text(encoding="utf-8"))

    def test_set_off_persists_and_stops_auto_build(self):
        code, out, stdout, _ = self.cli("config", "graph_auto", "off")
        self.assertEqual(code, 0, out)
        self.assertIn("graph_auto = off  (was auto)", stdout)
        self.assertEqual(self.stored()["graph_auto"], "off")
        self.cli("hook", "session-start", stdin="{}", env={"VERATUM_ROOT": str(self.tmp)})
        self.assertFalse((self.tmp / ".veratum/graph/graph.json").exists())
        self.cli("config", "graph_auto", "auto")
        self.cli("hook", "session-start", stdin="{}", env={"VERATUM_ROOT": str(self.tmp)})
        self.assertTrue((self.tmp / ".veratum/graph/graph.json").exists())

    def test_read_and_list(self):
        _, _, stdout, _ = self.cli("config", "graph_auto")
        self.assertEqual(stdout.strip(), "auto")
        _, _, stdout, _ = self.cli("config")
        self.assertIn("graph_auto", stdout)
        self.assertIn("python .veratum/engine/veratum_cli.py config <name> <value>", stdout)

    def test_aliases_and_numbers(self):
        self.cli("config", "graph_auto", "no")
        self.assertEqual(self.stored()["graph_auto"], "off")
        self.cli("config", "graph_auto", "on")
        self.assertEqual(self.stored()["graph_auto"], "auto")
        self.assertEqual(self.cli("config", "compact_max_lines", "60")[0], 0)
        self.assertEqual(self.stored()["compact_max_lines"], 60)

    def test_bad_values_are_rejected_and_nothing_changes(self):
        before = self.stored()
        for args in (("graph_auto", "maybe"), ("compact_max_lines", "abc"), ("compact_max_lines", "9999"), ("nope", "1")):
            code, out, _, _ = self.cli("config", *args)
            self.assertNotEqual(code, 0, args)
        self.assertEqual(self.stored(), before)
        _, out, _, _ = self.cli("config", "graph_auto", "maybe")
        self.assertIn("auto, refresh, off", out)

    def test_enforcement_settings_cannot_be_changed_by_command(self):
        before = self.stored()
        for key, value in (("enforcement", "off"), ("trivial_bypass", "true"), ("read_before_write", "false"),
                           ("protected_paths", "x")):
            code, out, _, _ = self.cli("config", key, value)
            self.assertNotEqual(code, 0, key)
            self.assertIn("Edit .veratum/config.json yourself", out)
        self.assertEqual(self.stored(), before)


class TestGraphHint(GraphCase):
    """Grep/Glob reminder: hosts that can add context get it, at most twice per task, and never once the graph was used."""

    def setUp(self):
        super().setUp()
        self.project()
        veratum_cli.initialize(veratum_cli.Workspace(self.tmp), quiet=True)
        self.build()

    def search(self, tool="Grep", host="claude"):
        payload = {"tool_name": tool, "tool_input": {"pattern": "login"}, "cwd": str(self.tmp)}
        if host == "antigravity":
            payload = {"toolCall": {"name": tool, "args": {}}, "workspacePaths": [str(self.tmp)]}
        code, out, err = self.hook("pre-tool", payload, host=host)
        self.assertEqual(code, 0, err)
        return json.loads(out) if out.strip() else {}

    def claude_hint(self):
        return self.search().get("hookSpecificOutput", {}).get("additionalContext", "")

    def test_claude_gets_additional_context(self):
        out = self.search("Grep")
        self.assertEqual(out["hookSpecificOutput"]["hookEventName"], "PreToolUse")
        self.assertIn('graph query "', out["hookSpecificOutput"]["additionalContext"])
        self.assertNotIn("permissionDecision", out["hookSpecificOutput"])  # never auto-approves the search
        self.assertTrue(self.search("Glob"))

    def test_at_most_twice_per_task(self):
        self.assertTrue(self.claude_hint())
        self.assertTrue(self.claude_hint())
        self.assertEqual(self.claude_hint(), "")

    def test_using_the_graph_silences_it_and_a_new_task_resets(self):
        self.assertTrue(self.claude_hint())
        self.cli("graph", "query", "charge")
        self.assertEqual(self.claude_hint(), "")
        self.cli("contract", "--goal", "new task", "--files", "app/api.py", "--verify", "true", "--no-impact")
        self.assertTrue(self.claude_hint())  # different task id -> reminded again

    def test_quiet_without_graph_or_when_off_or_other_tools(self):
        self.assertEqual(self.search("Read"), {})
        self.assertEqual(self.search("Edit"), {})
        self.cli("config", "graph_auto", "off")
        self.assertEqual(self.claude_hint(), "")
        self.cli("config", "graph_auto", "auto")
        (self.tmp / ".veratum/graph/graph.json").unlink()
        self.assertEqual(self.claude_hint(), "")

    def test_antigravity_and_cursor_formats(self):
        out = self.search("grep_search", host="antigravity")
        self.assertEqual(out["decision"], "allow")
        self.assertIn("graph query", out["reason"])
        code, out, err = self.hook("pre-tool", {"tool_name": "Grep", "tool_input": {}}, host="cursor")
        self.assertEqual(json.loads(out), {"permission": "allow"})  # no channel in Cursor: allowed, nothing added

    def test_state_file_is_not_touched_by_other_events(self):
        self.assertEqual(self.search("Bash"), {})
        state = json.loads((self.tmp / ".veratum/state.json").read_text(encoding="utf-8")) if (self.tmp / ".veratum/state.json").exists() else {}
        self.assertNotIn("graph_hint", state)


@unittest.skipUnless(HAS_NODE, "node not available")
class TestHintWiring(GraphCase):
    def test_claude_template_registers_glob_grep_once(self):
        template = json.loads((REPO / "adapters/claude-code/settings.template.json").read_text(encoding="utf-8"))
        matchers = [e["matcher"] for e in template["hooks"]["PreToolUse"]]
        self.assertEqual(matchers.count("Glob|Grep"), 1)
        env = {k: v for k, v in os.environ.items() if k != "CLAUDE_PROJECT_DIR"}
        run = lambda *a: subprocess.run(["node", str(REPO / "bin/veratum.js"), *a], cwd=self.tmp, capture_output=True, env=env, timeout=180)
        self.assertEqual(run("init", "--ide", "claude-code").returncode, 0)
        self.assertEqual(run("update").returncode, 0)  # idempotent
        pre = json.loads((self.tmp / ".claude/settings.json").read_text(encoding="utf-8"))["hooks"]["PreToolUse"]
        self.assertEqual([e["matcher"] for e in pre].count("Glob|Grep"), 1)
        self.assertEqual(run("uninstall", "--all").returncode, 0)
        left = (self.tmp / ".claude/settings.json")
        self.assertFalse(left.exists() and "Glob|Grep" in left.read_text(encoding="utf-8"))

    def test_opencode_plugin_appends_the_hint_to_search_results(self):
        self.project()
        veratum_cli.initialize(veratum_cli.Workspace(self.tmp), quiet=True)
        self.assertEqual(self.cli("graph", "build")[0], 0)
        plugin = self.tmp / "veratum_plugin.mjs"
        plugin.write_text((REPO / "adapters/opencode/veratum.js").read_text(encoding="utf-8"), encoding="utf-8")
        runner = self.tmp / "run_plugin.mjs"
        runner.write_text(
            'import { VeratumPlugin } from "./veratum_plugin.mjs";\n'
            'const hooks = await VeratumPlugin({ directory: process.cwd() });\n'
            'const grep = { output: "3 matches" }; await hooks["tool.execute.after"]({ tool: "grep" }, grep);\n'
            'const read = { output: "file text" }; await hooks["tool.execute.after"]({ tool: "read" }, read);\n'
            'console.log(JSON.stringify({ grep: grep.output, read: read.output }));\n', encoding="utf-8")
        env = {k: v for k, v in os.environ.items() if k != "CLAUDE_PROJECT_DIR"}
        env["VERATUM_PYTHON"] = sys.executable
        proc = subprocess.run(["node", str(runner)], cwd=self.tmp, capture_output=True, env=env, timeout=120)
        self.assertEqual(proc.returncode, 0, proc.stderr.decode("utf-8", "replace"))
        out = json.loads(proc.stdout.decode("utf-8").strip().splitlines()[-1])
        self.assertTrue(out["grep"].startswith("3 matches"))
        self.assertIn("graph query", out["grep"])
        self.assertEqual(out["read"], "file text")


class TestGraphStaysOutOfGit(VeratumTestCase):
    use_git = True

    def ignored(self, rel):
        return subprocess.run(["git", "check-ignore", "-q", rel], cwd=self.tmp).returncode == 0

    def test_generated_graph_logs_and_state_are_ignored_but_brain_is_not(self):
        self.write("app.py", "def login():\n    pass\n")
        self.assertEqual(self.cli("graph", "build")[0], 0)
        (self.tmp / ".veratum/logs").mkdir(exist_ok=True)
        (self.tmp / ".veratum/logs/last_run.log").write_text("x", encoding="utf-8")
        for rel in (".veratum/graph/graph.json", ".veratum/graph/GRAPH_REPORT.md", ".veratum/graph/cache.json",
                    ".veratum/graph/export/graph.html", ".veratum/logs/last_run.log", ".veratum/ledger.json"):
            self.assertTrue(self.ignored(rel), rel)
        self.assertFalse(self.ignored(".veratum/brain.json"))  # memory stays shareable unless the user ignores it

    def test_older_installs_get_graph_added(self):
        self.write("app.py", "x = 1\n")
        self.cli("init")
        gi = self.tmp / ".veratum/.gitignore"
        gi.write_text("logs/\nledger.json\n", encoding="utf-8")  # what an install from before the graph looked like
        self.cli("init")
        self.assertIn("graph/", gi.read_text(encoding="utf-8").splitlines())
        self.cli("init")  # idempotent: no duplicate line
        self.assertEqual(gi.read_text(encoding="utf-8").splitlines().count("graph/"), 1)


if __name__ == "__main__":
    unittest.main()
