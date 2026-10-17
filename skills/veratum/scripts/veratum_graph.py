#!/usr/bin/env python3
"""
Veratum knowledge graph (build -> cluster -> analyze -> report -> query), stdlib only.

Loaded on demand by veratum_cli.py (`graph` command, session-start refresh). It uses the CLI's helpers
(Workspace, CodeIndex, read_json, ...) through `bind()`, so there is one copy of each class and one
VeratumError type whether the CLI runs as a script or is imported.
"""
from __future__ import annotations

import json
import os
import posixpath
import re
import time
from pathlib import Path

# Helpers owned by veratum_cli.py, injected by bind().
_CORE_NAMES = (
    "CONF_EXTRACTED", "CONF_INFERRED", "CodeIndex", "VeratumError", "Workspace", "_IMPORT_LINE_PREFIXES",
    "_print_json", "_read_text", "_sha256_file", "graph_hint_used", "now_iso", "read_json", "write_json",
)


def bind(core) -> None:
    g = globals()
    for name in _CORE_NAMES:
        g[name] = getattr(core, name)


# Knowledge graph (Graphify-style: build -> cluster -> analyze -> report -> query)
#
# Stdlib-only re-implementation of the pipeline documented in Graphify's ARCHITECTURE.md
# (detect -> extract -> build -> cluster -> analyze -> report) with Veratum's own parsers.
# Output lives in .veratum/graph/: graph.json, GRAPH_REPORT.md, cache.json.
# ---------------------------------------------------------------------------

GRAPH_SCHEMA = "veratum.graph/v1"
_GRAPH_KEYWORDS = {"if", "for", "while", "switch", "catch", "return", "function", "new", "sizeof", "typeof", "else",
                   "elif", "with", "assert", "print", "super", "this", "self", "match", "case", "defer", "await",
                   "yield", "not", "and", "or", "in", "is", "lambda", "except", "raise", "del", "use", "import"}
_GRAPH_DEF_PATTERNS = {
    "js": [(r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\*?\s+([A-Za-z_$][\w$]*)", "function"),
           (r"^\s*(?:export\s+)?(?:default\s+)?(?:abstract\s+)?class\s+([A-Za-z_$][\w$]*)", "class"),
           (r"^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[\w$]+)\s*(?::[^=]+)?=>", "function"),
           (r"^\s*(?:export\s+)?(?:interface|type|enum)\s+([A-Za-z_$][\w$]*)", "type")],
    "py": [(r"^\s*(?:async\s+)?def\s+([A-Za-z_]\w*)", "function"), (r"^\s*class\s+([A-Za-z_]\w*)", "class")],
    "go": [(r"^func\s+(?:\([^)]*\)\s*)?([A-Za-z_]\w*)", "function"), (r"^type\s+([A-Za-z_]\w*)", "type")],
    "rs": [(r"^\s*(?:pub(?:\([^)]*\))?\s+)?(?:async\s+)?(?:unsafe\s+)?fn\s+([A-Za-z_]\w*)", "function"),
           (r"^\s*(?:pub(?:\([^)]*\))?\s+)?(?:struct|enum|trait)\s+([A-Za-z_]\w*)", "type")],
    "java": [(r"^\s*(?:public\s+|private\s+|protected\s+|static\s+|final\s+|abstract\s+|sealed\s+)*(?:class|interface|enum|record)\s+(\w+)", "class"),
             (r"^\s*(?:public|private|protected)\s+(?:static\s+|final\s+|synchronized\s+|abstract\s+)*[\w<>\[\],.?]+\s+(\w+)\s*\(", "method")],
    "c": [(r"^[A-Za-z_][\w \t\*]*?\b([A-Za-z_]\w*)\s*\([^;{]*\)\s*\{", "function")],
}
_GRAPH_CALL_RE = re.compile(r"(?<![\w$.])([A-Za-z_$][\w$]*)\s*\(|\.([A-Za-z_$][\w$]*)\s*\(")


def _graph_label(value) -> str:
    """Strip control characters and cap length (graph content is untrusted when rendered)."""
    return re.sub(r"[\x00-\x1f\x7f]", " ", str(value))[:256]


def _extract_python_ast(text: str):
    import ast
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return None
    defs: list = []
    calls: list = []

    def visit(node, scope, owner):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                is_class = isinstance(child, ast.ClassDef)
                qual = ".".join([s[0] for s in scope] + [child.name])
                kind = "class" if is_class else ("method" if scope and scope[-1][1] else "function")
                defs.append({"name": child.name, "qual": qual, "kind": kind, "line": child.lineno,
                             "end": getattr(child, "end_lineno", child.lineno)})
                visit(child, scope + [(child.name, is_class)], qual)
                continue
            if isinstance(child, ast.Call):
                fn = child.func
                name = fn.id if isinstance(fn, ast.Name) else fn.attr if isinstance(fn, ast.Attribute) else None
                if name and name not in _GRAPH_KEYWORDS:
                    calls.append({"name": name, "line": child.lineno, "owner": owner})
            visit(child, scope, owner)

    visit(tree, [], "")
    return {"defs": defs, "calls": calls}


def _extract_generic(text: str, lang: str) -> dict:
    lines = text.splitlines()
    defs: list = []
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if not stripped or stripped.startswith(("//", "#", "*", "/*")):
            continue
        for pat, kind in _GRAPH_DEF_PATTERNS.get(lang, []):
            m = re.match(pat, line)
            if m and m.group(1) not in _GRAPH_KEYWORDS:
                defs.append({"name": m.group(1), "qual": m.group(1), "kind": kind, "line": i, "end": len(lines)})
                break
    for a, b in zip(defs, defs[1:]):
        a["end"] = max(a["line"], b["line"] - 1)
    def_lines = {d["line"]: d for d in defs}
    calls: list = []
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if i in def_lines or not stripped or stripped.startswith(("//", "#", "*", "/*") + _IMPORT_LINE_PREFIXES):
            continue
        owner = ""
        for d in defs:
            if d["line"] <= i <= d["end"]:
                owner = d["qual"]
        for m in _GRAPH_CALL_RE.finditer(line):
            name = m.group(1) or m.group(2)
            if name and name not in _GRAPH_KEYWORDS:
                calls.append({"name": name, "line": i, "owner": owner})
        if len(calls) > 4000:
            break
    return {"defs": defs, "calls": calls}


def graph_extract_file(text: str, lang: str) -> dict:
    result = _extract_python_ast(text) if lang == "py" else None
    return result or _extract_generic(text, lang)


def _import_tokens(data: dict) -> set:
    raw: list = []
    raw += data.get("specs", []) + data.get("imports", []) + data.get("uses", []) + data.get("mods", [])
    raw += data.get("includes", [])
    for module, names in data.get("stmts", []):
        raw.append(module)
        raw += names
    return {t.lower() for r in raw for t in re.split(r"[/.:\\\-@~#*{}\s,]+", str(r)) if t}


def graph_build(ws: Workspace, full: bool = False, max_files: int = 5000) -> dict:
    """Build/refresh .veratum/graph/. Per-file extraction is cached by content hash (incremental)."""
    gdir = ws.dir / "graph"
    index = CodeIndex(ws, max_files=max_files)
    old = read_json(gdir / "cache.json", {}) or {}
    cache = {} if full or old.get("schema") != GRAPH_SCHEMA else old.get("files", {})
    extracted: dict = {}
    fresh = reused = 0
    for rel in index.files:
        path = ws.root / rel
        try:
            sha = _sha256_file(path)
        except OSError:
            continue
        hit = cache.get(rel)
        if hit and hit.get("sha") == sha:
            data = hit["data"]
            reused += 1
        else:
            data = graph_extract_file(_read_text(path), index.lang(rel))
            fresh += 1
        extracted[rel] = {"sha": sha, "data": data}

    nodes: dict = {}
    edges: list = []
    defs_by_name: dict = {}
    owner_id: dict = {}
    for rel, entry in extracted.items():
        fid = "file:" + rel
        nodes[fid] = {"id": fid, "label": posixpath.basename(rel), "kind": "file", "source_file": rel,
                      "source_location": "L1", "language": index.lang(rel)}
        for d in entry["data"]["defs"]:
            sid = "sym:{}::{}".format(rel, d["qual"])
            if sid in nodes:
                sid += "@{}".format(d["line"])
            nodes[sid] = {"id": sid, "label": d["name"], "kind": d["kind"], "source_file": rel,
                          "source_location": "L{}".format(d["line"]), "language": index.lang(rel)}
            owner_id[(rel, d["qual"])] = sid
            defs_by_name.setdefault(d["name"], []).append((sid, rel))
            edges.append({"source": fid, "target": sid, "relation": "contains", "confidence": CONF_EXTRACTED,
                          "confidence_score": 1.0, "source_file": rel, "source_location": "L{}".format(d["line"])})

    # file -> file imports (EXTRACTED, with the import line as evidence); token prefilter avoids n^2 matching
    by_token: dict = {}
    for rel in extracted:
        stem = posixpath.splitext(posixpath.basename(rel))[0].lower()
        by_token.setdefault(stem, []).append(rel)
        parent = posixpath.basename(posixpath.dirname(rel)).lower()
        if parent:
            by_token.setdefault(parent, []).append(rel)
    imported: dict = {}
    for rel in extracted:
        tokens = _import_tokens(index.parsed(rel))
        cands = {t for tok in tokens for t in by_token.get(tok, [])}
        for target in sorted(cands):
            if target != rel and index.depends_on(rel, target):
                ev, conf = index.import_evidence(rel, target, limit=1)
                line = ev[0]["line"] if ev else 1
                edges.append({"source": "file:" + rel, "target": "file:" + target, "relation": "imports",
                              "confidence": conf, "confidence_score": 1.0 if conf == CONF_EXTRACTED else 0.7,
                              "source_file": rel, "source_location": "L{}".format(line)})
                imported.setdefault(rel, set()).add(target)

    # call edges: name-resolved, tiered confidence (never EXTRACTED: names are not types)
    seen_calls: set = set()
    for rel, entry in extracted.items():
        for call in entry["data"]["calls"]:
            name = call["name"]
            cands = defs_by_name.get(name)
            if not cands:
                continue
            caller = owner_id.get((rel, call["owner"])) if call["owner"] else None
            caller = caller or "file:" + rel
            common = len(name) < 5 or name.lower() in CodeIndex._COMMON_WORDS
            same = [c for c in cands if c[1] == rel]
            via_import = [c for c in cands if c[1] in imported.get(rel, ())]
            if same:
                chosen, conf, score, basis = same[:3], CONF_INFERRED, 0.8, "same-file"
            elif via_import:
                chosen, conf, score, basis = via_import[:3], CONF_INFERRED, 0.85, "import-resolved"
            elif len(cands) == 1 and not common:
                chosen, conf, score, basis = cands, CONF_INFERRED, 0.55, "unique-name"
            elif 2 <= len(cands) <= 3 and not common:
                chosen, conf, score, basis = cands, "AMBIGUOUS", 0.3, "multiple-candidates"
            else:
                continue
            for tid, _ in chosen:
                if tid == caller or (caller, tid) in seen_calls:
                    continue
                seen_calls.add((caller, tid))
                edges.append({"source": caller, "target": tid, "relation": "calls", "confidence": conf,
                              "confidence_score": score, "basis": basis, "source_file": rel,
                              "source_location": "L{}".format(call["line"])})

    doc_stats = _graph_add_docs(ws, index, nodes, edges, defs_by_name)
    doc_stats.update(_graph_merge_semantic(ws, nodes, edges))
    communities = _graph_cluster(nodes, edges)
    for nid, node in nodes.items():
        node["community"] = communities["of"].get(nid, -1)
    graph = {"schema": GRAPH_SCHEMA, "built_at": now_iso(),
             "stats": {"files": len(extracted), "nodes": len(nodes), "edges": len(edges),
                       "extracted_now": fresh, "from_cache": reused, "truncated": len(index.files) >= max_files,
                       **doc_stats},
             "communities": communities["list"], "nodes": list(nodes.values()), "edges": edges}
    write_json(gdir / "graph.json", graph)
    write_json(gdir / "cache.json", {"schema": GRAPH_SCHEMA, "files": extracted})
    (gdir / "GRAPH_REPORT.md").write_text(graph_report(graph), encoding="utf-8", newline="\n")
    return graph


_GRAPH_MAX_COMMUNITY_FRACTION = 0.25  # communities above 25% of the graph (min 10 nodes) get a second, finer pass
_GRAPH_MIN_SPLIT = 10


def _louvain_pass(nodes: list, adj: dict, resolution: float = 1.0) -> tuple:
    """Phase 1 of Louvain: greedy local moving by modularity gain. Deterministic (sorted visit order)."""
    m2 = sum(sum(nb.values()) for nb in adj.values())
    comm = {n: n for n in nodes}
    if m2 == 0:
        return comm, False
    deg = {n: sum(adj[n].values()) for n in nodes}
    tot = dict(deg)
    improved = False
    for _ in range(50):
        moved = False
        for n in nodes:
            home = comm[n]
            w_to: dict = {}
            for nb, w in adj[n].items():
                if nb != n:
                    w_to[comm[nb]] = w_to.get(comm[nb], 0) + w
            tot[home] -= deg[n]
            best, best_gain = home, w_to.get(home, 0) - resolution * tot[home] * deg[n] / m2
            for c in sorted(w_to):
                gain = w_to[c] - resolution * tot[c] * deg[n] / m2
                if gain > best_gain + 1e-12:
                    best, best_gain = c, gain
            tot[best] += deg[n]
            if best != home:
                comm[n], moved, improved = best, True, True
        if not moved:
            break
    return comm, improved


def graph_louvain(adj: dict, resolution: float = 1.0) -> dict:
    """Louvain community detection (modularity optimisation + graph aggregation), stdlib only.
    `adj` is a symmetric weighted adjacency {node: {neighbour: weight}}. Returns {node: community label}."""
    nodes = sorted(adj)
    membership = {n: n for n in nodes}
    cur_nodes, cur_adj = nodes, adj
    for _ in range(10):
        part, improved = _louvain_pass(cur_nodes, cur_adj, resolution)
        if not improved:
            break
        membership = {o: part[s] for o, s in membership.items()}
        groups = sorted(set(part.values()))
        new_adj: dict = {g: {} for g in groups}
        for u, nbs in cur_adj.items():
            for v, w in nbs.items():
                gu, gv = part[u], part[v]
                new_adj[gu][gv] = new_adj[gu].get(gv, 0) + w
        if len(groups) == len(cur_nodes):
            break
        cur_nodes, cur_adj = groups, new_adj
    return membership


def _graph_cluster(nodes: dict, edges: list) -> dict:
    """Louvain over all nodes (contains/imports 1.0, other relations 0.5); isolates are single-node communities;
    oversized communities are re-clustered at a higher resolution (Graphify's cluster.py does the same with Leiden/Louvain)."""
    adj: dict = {nid: {} for nid in nodes}
    for e in edges:
        a, b = e["source"], e["target"]
        if a == b or a not in adj or b not in adj:
            continue
        w = 1.0 if e["relation"] in ("contains", "imports") else 0.5
        adj[a][b] = adj[a].get(b, 0) + w
        adj[b][a] = adj[b].get(a, 0) + w
    connected = {n: nb for n, nb in adj.items() if nb}
    raw: dict = {}
    for n, c in graph_louvain(connected).items():
        raw.setdefault(c, []).append(n)
    groups = [sorted(g) for g in raw.values()] + [[n] for n in sorted(adj) if not adj[n]]
    limit = max(_GRAPH_MIN_SPLIT, int(len(nodes) * _GRAPH_MAX_COMMUNITY_FRACTION))
    final: list = []
    for members in groups:
        if len(members) > limit:
            ms = set(members)
            sub = {n: {nb: w for nb, w in adj[n].items() if nb in ms} for n in members}
            parts: dict = {}
            for n, c in graph_louvain(sub, resolution=2.0).items():
                parts.setdefault(c, []).append(n)
            final.extend(sorted(p) for p in parts.values())
        else:
            final.append(members)
    final.sort(key=lambda g: (-len(g), g[0]))
    out, of = [], {}
    for cid, members in enumerate(final):
        ms = set(members)
        for n in members:
            of[n] = cid
        inner = sum(1 for n in members for nb in adj[n] if nb in ms) / 2
        possible = len(members) * (len(members) - 1) / 2
        files = sorted({nodes[n]["source_file"] for n in members})
        dirs: dict = {}
        for f in files:
            d = posixpath.dirname(f) or "."
            dirs[d] = dirs.get(d, 0) + 1
        out.append({"id": cid, "name": sorted(dirs.items(), key=lambda kv: (-kv[1], kv[0]))[0][0],
                    "size": len(members), "file_count": len(files),
                    "cohesion": round(inner / possible, 2) if possible else 1.0, "files": files[:50]})
    return {"list": out, "of": of}


def _graph_degrees(graph: dict) -> dict:
    deg: dict = {}
    for e in graph["edges"]:
        if e["relation"] != "contains":
            deg[e["source"]] = deg.get(e["source"], 0) + 1
            deg[e["target"]] = deg.get(e["target"], 0) + 1
    return deg


def graph_report(graph: dict) -> str:
    nodes = {n["id"]: n for n in graph["nodes"]}
    deg = _graph_degrees(graph)
    st = graph["stats"]
    conf: dict = {}
    for e in graph["edges"]:
        conf[e["confidence"]] = conf.get(e["confidence"], 0) + 1
    lines = ["# Veratum graph report", "",
             "Built {}. {} files, {} nodes, {} edges ({} extracted this run, {} from cache).".format(
                 graph["built_at"], st["files"], st["nodes"], st["edges"], st["extracted_now"], st["from_cache"]),
             "Edge confidence: " + ", ".join("{} {}".format(k, v) for k, v in sorted(conf.items())) +
             ". EXTRACTED = statement in source; INFERRED = name resolution; AMBIGUOUS = several candidates (review).", ""]
    if st.get("truncated"):
        lines += ["> Warning: file limit reached; the graph is partial. Re-run with a higher `--max-files`.", ""]
    if st.get("docs") or st.get("assets"):
        lines += ["Docs: {} text doc(s), {} asset(s) (PDF/images); semantic notes merged for {} file(s).".format(
            st.get("docs", 0), st.get("assets", 0), st.get("semantic_files", 0)), ""]
    if st.get("pending_semantic"):
        lines += ["> {} doc/asset file(s) have no semantic extraction yet (e.g. {}). The agent can read them and run "
                  "`graph semantic add`; see `graph semantic list`.".format(
                      len(st["pending_semantic"]), ", ".join(st["pending_semantic"][:3])), ""]
    lines.append("## God nodes (most connected)")
    god = sorted(((d, i) for i, d in deg.items()), key=lambda t: (-t[0], t[1]))[:10]
    for d, nid in god:
        n = nodes[nid]
        lines.append("- `{}` ({}) — {} edges — {}:{}".format(_graph_label(n["label"]), n["kind"], d,
                                                           n["source_file"], n["source_location"]))
    lines += ["", "## Communities"]
    for c in graph["communities"]:
        if c["size"] >= 2:
            lines.append("- #{} `{}` — {} nodes in {} file(s), cohesion {}: {}".format(
                c["id"], c["name"], c["size"], c["file_count"], c["cohesion"],
                ", ".join(c["files"][:6]) + (" …" if c["file_count"] > 6 else "")))
    singles = sum(1 for c in graph["communities"] if c["size"] == 1)
    lines += ["- {} isolated node(s) with no links".format(singles), "", "## Surprising connections"]
    scored = []
    for e in graph["edges"]:
        if e["relation"] == "contains":
            continue
        a, b = nodes[e["source"]], nodes[e["target"]]
        if a["community"] == b["community"]:
            continue
        s = {"EXTRACTED": 0, "INFERRED": 1, "AMBIGUOUS": 1.5}.get(e["confidence"], 0)
        s += 1 if posixpath.dirname(a["source_file"]).split("/")[0] != posixpath.dirname(b["source_file"]).split("/")[0] else 0
        s += 1 if a.get("language") != b.get("language") else 0
        scored.append((s, e["source"], e["target"], e))
    for s, _, _, e in sorted(scored, key=lambda t: (-t[0], t[1], t[2]))[:8]:
        lines.append("- `{}` --{} [{}]--> `{}` ({}:{})".format(
            _graph_label(nodes[e["source"]]["label"]), e["relation"], e["confidence"],
            _graph_label(nodes[e["target"]]["label"]), e["source_file"], e["source_location"]))
    if not scored:
        lines.append("- none (no cross-community links)")
    lines += ["", "## Ambiguous edges (review)"]
    amb = [e for e in graph["edges"] if e["confidence"] == "AMBIGUOUS"][:10]
    for e in amb:
        lines.append("- `{}` → `{}` ({}:{})".format(_graph_label(nodes[e["source"]]["label"]),
                                                    _graph_label(nodes[e["target"]]["label"]),
                                                    e["source_file"], e["source_location"]))
    return "\n".join(lines + ([] if amb else ["- none"]) + [""])


def validate_graph(graph: dict) -> list:
    problems = []
    if graph.get("schema") != GRAPH_SCHEMA:
        problems.append("unknown schema")
    ids = set()
    for n in graph.get("nodes", []):
        if not all(k in n for k in ("id", "label", "source_file")):
            problems.append("node missing id/label/source_file")
            break
        ids.add(n["id"])
    for e in graph.get("edges", []):
        if e.get("source") not in ids or e.get("target") not in ids:
            problems.append("edge references unknown node")
            break
        if e.get("confidence") not in (CONF_EXTRACTED, CONF_INFERRED, "AMBIGUOUS"):
            problems.append("edge has invalid confidence")
            break
    return problems


def graph_load(ws: Workspace) -> dict:
    graph = read_json(ws.dir / "graph" / "graph.json", None)
    if not graph:
        raise VeratumError("No graph yet. Run: veratum_cli.py graph build")
    problems = validate_graph(graph)
    if problems:
        raise VeratumError("graph.json is invalid ({}). Re-run `graph build --full`.".format(problems[0]))
    return graph


def _graph_adjacency(graph: dict) -> dict:
    adj: dict = {}
    for i, e in enumerate(graph["edges"]):
        adj.setdefault(e["source"], []).append((e["target"], i))
        adj.setdefault(e["target"], []).append((e["source"], i))
    return adj


def graph_find(graph: dict, text: str) -> list:
    term = text.lower().strip()
    exact = [n["id"] for n in graph["nodes"] if term in (n["id"].lower(), n["label"].lower())]
    return exact or [n["id"] for n in graph["nodes"] if term in n["label"].lower() or term == n["source_file"].lower()]


def graph_query(graph: dict, question: str, mode: str = "bfs", depth: int = 2, budget: int = 2000) -> str:
    words = [w.lower() for w in re.split(r"\W+|(?<=[a-z])(?=[A-Z])", question) if w and len(w) > 2]
    deg = _graph_degrees(graph)
    scored = []
    for n in graph["nodes"]:
        label, src = n["label"].lower(), n["source_file"].lower()
        s = sum(1 for w in words if w in label) + sum(0.5 for w in words if w in src)
        if s > 0:
            scored.append((-s, -deg.get(n["id"], 0), n["id"]))
    seeds = [nid for _, _, nid in sorted(scored)[:3]]
    if not seeds:
        return "No graph nodes match '{}'.".format(_graph_label(question))
    adj = _graph_adjacency(graph)
    nodes = {n["id"]: n for n in graph["nodes"]}
    seen, order, used = set(seeds), list(seeds), set()
    frontier = list(seeds)
    for _ in range(max(1, min(depth, 6))):
        nxt = []
        for cur in (frontier if mode == "bfs" else frontier[-1:]):
            for nb, ei in sorted(adj.get(cur, []), key=lambda t: (-deg.get(t[0], 0), t[0])):
                used.add(ei)
                if nb not in seen:
                    seen.add(nb)
                    order.append(nb)
                    nxt.append(nb)
        frontier = nxt
        if not frontier:
            break
    out = []
    for nid in sorted(order, key=lambda i: (-deg.get(i, 0), i)):
        n = nodes[nid]
        out.append("NODE {} ({}) [src={} loc={} community={}]".format(
            _graph_label(n["label"]), n["kind"], n["source_file"], n["source_location"], n.get("community")))
    for ei in sorted(used):
        e = graph["edges"][ei]
        if e["source"] in seen and e["target"] in seen:
            out.append("EDGE {} --{} [{}]--> {}  ({}:{})".format(
                _graph_label(nodes[e["source"]]["label"]), e["relation"],
                e["confidence"] + (" " + e["basis"] if e.get("basis") else ""),
                _graph_label(nodes[e["target"]]["label"]), e["source_file"], e["source_location"]))
    text = "\n".join(out)
    limit = budget * 4  # ~4 chars per token
    return text if len(text) <= limit else text[:limit] + "\n… (truncated to ~{} tokens)".format(budget)


def graph_path(graph: dict, start: str, goal: str) -> str:
    a, b = graph_find(graph, start), graph_find(graph, goal)
    if not a or not b:
        return "No node matches '{}'.".format(_graph_label(start if not a else goal))
    adj = _graph_adjacency(graph)
    nodes = {n["id"]: n for n in graph["nodes"]}
    prev: dict = {a[0]: None}
    queue = [a[0]]
    while queue:
        cur = queue.pop(0)
        if cur == b[0]:
            break
        for nb, ei in adj.get(cur, []):
            if nb not in prev:
                prev[nb] = (cur, ei)
                queue.append(nb)
    if b[0] not in prev:
        return "No path between {} and {}.".format(_graph_label(start), _graph_label(goal))
    steps, cur = [], b[0]
    while prev[cur]:
        p, ei = prev[cur]
        e = graph["edges"][ei]
        steps.append("{} --{} [{}]--> {} ({}:{})".format(
            _graph_label(nodes[e["source"]]["label"]), e["relation"], e["confidence"],
            _graph_label(nodes[e["target"]]["label"]), e["source_file"], e["source_location"]))
        cur = p
    return "\n".join(reversed(steps))


def graph_explain(graph: dict, name: str) -> str:
    hits = graph_find(graph, name)
    if not hits:
        return "No node matches '{}'.".format(_graph_label(name))
    nodes = {n["id"]: n for n in graph["nodes"]}
    n = nodes[hits[0]]
    lines = ["{} ({}) {}:{} community={}".format(_graph_label(n["label"]), n["kind"], n["source_file"],
                                                 n["source_location"], n.get("community"))]
    for e in graph["edges"]:
        if hits[0] in (e["source"], e["target"]):
            other = e["target"] if e["source"] == hits[0] else e["source"]
            arrow = "-->" if e["source"] == hits[0] else "<--"
            lines.append("  {} {} [{}] {} ({}:{})".format(arrow, e["relation"], e["confidence"],
                                                         _graph_label(nodes[other]["label"]), e["source_file"],
                                                         e["source_location"]))
    return "\n".join(lines[:60])


def graph_benchmark(ws: Workspace, graph: dict, question: str) -> dict:
    corpus = sum(len(_read_text(ws.root / f)) for f in {n["source_file"] for n in graph["nodes"]}) // 4
    answer = len(graph_query(graph, question, depth=3)) // 4
    return {"question": question, "corpus_tokens": corpus, "query_tokens": answer,
            "reduction": round(corpus / answer, 1) if answer else None}


def graph_status(ws: Workspace) -> dict:
    cache = (read_json(ws.dir / "graph" / "cache.json", {}) or {}).get("files", {})
    if not cache or not (ws.dir / "graph" / "graph.json").exists():
        return {"built": False, "stale_files": []}
    files = CodeIndex(ws).files
    stale = [f for f in files if f not in cache or cache[f].get("sha") != _sha256_file(ws.root / f)]
    stale += [f for f in cache if f not in set(files)]
    return {"built": True, "stale_files": sorted(set(stale))}


# -- documents, assets and agent-supplied semantic extraction ---------------------------------
_DOC_EXTS = (".md", ".mdx", ".rst", ".txt")
_ASSET_EXTS = (".pdf", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".docx", ".xlsx")
_MD_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_MD_LINK_RE = re.compile(r"\[[^\]\n]*\]\(([^)\s#?]+)[^)]*\)")
_BACKTICK_RE = re.compile(r"`([A-Za-z_][\w.]*)(?:\(\))?`")


def _graph_add_docs(ws: Workspace, index: "CodeIndex", nodes: dict, edges: list, defs_by_name: dict) -> dict:
    """Markdown/text docs become nodes: headings (EXTRACTED), relative links (EXTRACTED), `code` mentions (INFERRED).
    Binary assets (PDF/images) become nodes the agent can enrich through `graph semantic add`."""
    from urllib.parse import unquote
    files = index._list_files(500, exts=_DOC_EXTS + _ASSET_EXTS)
    by_rel = {n["source_file"]: nid for nid, n in nodes.items() if n["kind"] == "file"}
    docs = assets = 0
    for rel in files:
        is_doc = os.path.splitext(rel)[1].lower() in _DOC_EXTS
        nid = ("doc:" if is_doc else "asset:") + rel
        nodes[nid] = {"id": nid, "label": posixpath.basename(rel), "kind": "doc" if is_doc else "asset",
                      "source_file": rel, "source_location": "L1",
                      "language": "markdown" if is_doc else os.path.splitext(rel)[1].lstrip(".").lower()}
        by_rel[rel] = nid
        docs, assets = docs + is_doc, assets + (not is_doc)
    for rel in files:
        if not rel.lower().endswith(_DOC_EXTS):
            continue
        doc_id, current, fenced = by_rel[rel], by_rel[rel], False
        for i, line in enumerate(_read_text(ws.root / rel).splitlines(), 1):
            if line.lstrip().startswith("```"):
                fenced = not fenced
                continue
            if fenced:
                continue
            m = _MD_HEADING_RE.match(line)
            if m:
                current = "sec:{}::{}".format(rel, i)
                nodes[current] = {"id": current, "label": _graph_label(m.group(2)), "kind": "section",
                                  "source_file": rel, "source_location": "L{}".format(i), "language": "markdown"}
                edges.append({"source": doc_id, "target": current, "relation": "contains", "confidence": CONF_EXTRACTED,
                              "confidence_score": 1.0, "source_file": rel, "source_location": "L{}".format(i)})
            for link in _MD_LINK_RE.findall(line):
                if "://" in link or link.startswith(("mailto:", "/")):
                    continue
                target = by_rel.get(posixpath.normpath(posixpath.join(posixpath.dirname(rel), unquote(link))))
                if target and target != doc_id:
                    edges.append({"source": current, "target": target, "relation": "references",
                                  "confidence": CONF_EXTRACTED, "confidence_score": 1.0, "source_file": rel,
                                  "source_location": "L{}".format(i)})
            for name in dict.fromkeys(_BACKTICK_RE.findall(line)):
                bare = name.split(".")[-1]
                cands = defs_by_name.get(bare, [])
                if len(bare) >= 5 and bare.lower() not in CodeIndex._COMMON_WORDS and 1 <= len(cands) <= 3:
                    for tid, _ in cands:
                        edges.append({"source": current, "target": tid, "relation": "mentions",
                                      "confidence": CONF_INFERRED if len(cands) == 1 else "AMBIGUOUS",
                                      "confidence_score": 0.6 if len(cands) == 1 else 0.3, "basis": "doc-mention",
                                      "source_file": rel, "source_location": "L{}".format(i)})
    pending = [f for f, _ in graph_semantic_pending(ws, files)]
    return {"docs": docs, "assets": assets, "pending_semantic": pending[:50]}


def _semantic_path(ws: Workspace) -> Path:
    return ws.dir / "graph" / "semantic.json"


def graph_semantic_pending(ws: Workspace, files: list | None = None) -> list:
    """Docs/assets with no (or outdated) semantic extraction: [(rel, sha)]. The host agent reads each and submits notes."""
    files = files if files is not None else CodeIndex(ws)._list_files(500, exts=_DOC_EXTS + _ASSET_EXTS)
    done = (read_json(_semantic_path(ws), {}) or {}).get("files", {})
    out = []
    for rel in files:
        try:
            sha = _sha256_file(ws.root / rel)
        except OSError:
            continue
        if done.get(rel, {}).get("sha") != sha:
            out.append((rel, sha))
    return out


def graph_semantic_add(ws: Workspace, payload) -> dict:
    """Store concept nodes/edges an agent extracted from a doc/PDF/image. Treated as untrusted data:
    labels sanitized, sizes capped, and edges can only ever be INFERRED or AMBIGUOUS (never EXTRACTED)."""
    items = payload if isinstance(payload, list) else [payload]
    store = read_json(_semantic_path(ws), {}) or {}
    store.setdefault("schema", GRAPH_SCHEMA)
    store.setdefault("files", {})
    added_nodes = added_edges = 0
    for item in items:
        if not isinstance(item, dict):
            raise VeratumError("semantic payload must be an object or a list of objects.")
        rel = ws.rel(str(item.get("source_file", "")))
        if not rel or not (ws.root / rel).is_file():
            raise VeratumError("semantic: source_file '{}' is not a file inside the workspace.".format(item.get("source_file")))
        nodes = []
        for n in (item.get("nodes") or [])[:200]:
            label = _graph_label(n.get("label", "") if isinstance(n, dict) else n).strip()
            if label:
                nodes.append({"label": label, "kind": re.sub(r"[^a-z_]", "", str((n or {}).get("kind", "concept")).lower())[:32] or "concept"
                              if isinstance(n, dict) else "concept",
                              "source_location": _graph_label((n or {}).get("source_location", "")) if isinstance(n, dict) else ""})
        edges = []
        for e in (item.get("edges") or [])[:400]:
            if isinstance(e, dict) and e.get("source") and e.get("target"):
                edges.append({"source": _graph_label(e["source"]).strip(), "target": _graph_label(e["target"]).strip(),
                              "relation": re.sub(r"[^a-z_]", "", str(e.get("relation", "related_to")).lower())[:32] or "related_to",
                              "confidence": "AMBIGUOUS" if str(e.get("confidence", "")).upper() == "AMBIGUOUS" else CONF_INFERRED,
                              "evidence": _graph_label(e.get("evidence", ""))[:200]})
        store["files"][rel] = {"sha": _sha256_file(ws.root / rel), "added_at": now_iso(), "nodes": nodes, "edges": edges}
        added_nodes, added_edges = added_nodes + len(nodes), added_edges + len(edges)
    write_json(_semantic_path(ws), store)
    return {"files": len(items), "nodes": added_nodes, "edges": added_edges}


def _graph_merge_semantic(ws: Workspace, nodes: dict, edges: list) -> dict:
    store = (read_json(_semantic_path(ws), {}) or {}).get("files", {})
    merged = stale = dropped = 0
    labels: dict = {}
    for nid, n in nodes.items():
        labels.setdefault(n["label"].lower(), []).append(nid)
    for rel, entry in sorted(store.items()):
        path = ws.root / rel
        try:
            current = _sha256_file(path)
        except OSError:
            stale += 1
            continue
        if current != entry.get("sha"):
            stale += 1
            continue
        merged += 1
        owner = next((nid for nid in (("doc:" + rel), ("asset:" + rel), ("file:" + rel)) if nid in nodes), None)
        local: dict = {}
        for n in entry.get("nodes", []):
            sid = "sem:{}::{}".format(rel, n["label"])
            nodes[sid] = {"id": sid, "label": n["label"], "kind": n.get("kind", "concept"), "source_file": rel,
                          "source_location": n.get("source_location") or "L1", "language": "semantic"}
            local[n["label"].lower()] = sid
            if owner:
                edges.append({"source": owner, "target": sid, "relation": "describes", "confidence": CONF_INFERRED,
                              "confidence_score": 0.6, "basis": "semantic", "source_file": rel,
                              "source_location": nodes[sid]["source_location"]})
        for e in entry.get("edges", []):
            ends = []
            for key in ("source", "target"):
                label = e[key].lower()
                found = local.get(label) or (labels.get(label, [None])[0] if len(labels.get(label, [])) == 1 else None)
                ends.append(found)
            if None in ends or ends[0] == ends[1]:
                dropped += 1
                continue
            edges.append({"source": ends[0], "target": ends[1], "relation": e["relation"], "confidence": e["confidence"],
                          "confidence_score": 0.6 if e["confidence"] == CONF_INFERRED else 0.3, "basis": "semantic",
                          "evidence": e.get("evidence", ""), "source_file": rel, "source_location": "L1"})
    return {"semantic_files": merged, "semantic_stale": stale, "semantic_dropped_edges": dropped}


# -- watch + auto-refresh -----------------------------------------------------------------------
def graph_watch(ws: Workspace, interval: float = 2.0, debounce: float = 3.0, cycles: int | None = None,
                sleep=time.sleep, say=print) -> int:
    """Poll for source/doc changes; rebuild (incrementally) once edits settle. Returns the number of rebuilds."""
    def signature():
        index = CodeIndex(ws)
        files = index.files + index._list_files(500, exts=_DOC_EXTS)
        sig = {}
        for rel in files:
            try:
                st = (ws.root / rel).stat()
                sig[rel] = (st.st_mtime_ns, st.st_size)
            except OSError:
                pass
        return sig

    last, rebuilds, tick = signature(), 0, 0
    while cycles is None or tick < cycles:
        sleep(interval)
        tick += 1
        now = signature()
        if now == last:
            continue
        sleep(debounce)  # let a burst of saves finish
        now = signature()
        g = graph_build(ws)
        rebuilds += 1
        last = now
        say("🕸️  [VERATUM GRAPH] rebuilt: {} nodes · {} edges ({} re-extracted)".format(
            g["stats"]["nodes"], g["stats"]["edges"], g["stats"]["extracted_now"]))
    return rebuilds


def graph_auto_refresh(ws: Workspace) -> str:
    """Session-start / pre-query hook: build when missing (small repos) and refresh when stale. Returns a status note."""
    mode = str(ws.config().get("graph_auto", "auto"))
    if mode == "off":
        return ""
    try:
        status = graph_status(ws)
        if not status["built"]:
            if mode != "auto" or len(CodeIndex(ws).files) > 1500:
                return ""
            g = graph_build(ws)
            return "built ({} nodes, {} edges)".format(g["stats"]["nodes"], g["stats"]["edges"])
        if status["stale_files"]:
            g = graph_build(ws)
            return "refreshed ({} changed file(s))".format(g["stats"]["extracted_now"])
    except (OSError, VeratumError, ValueError):
        return ""
    return ""




def run_command(ws, args) -> int:
    """`graph <action>` CLI entry point (argument parsing lives in veratum_cli.build_parser)."""
    import veratum_export
    text = " ".join(args.text).strip()
    if args.action == "build":
        g = graph_build(ws, full=args.full, max_files=max(1, args.max_files))
        if args.json:
            _print_json(g["stats"])
        else:
            st = g["stats"]
            print("🕸️  [VERATUM GRAPH] {} files · {} nodes · {} edges ({} extracted now, {} cached) → .veratum/graph/".format(
                st["files"], st["nodes"], st["edges"], st["extracted_now"], st["from_cache"]))
            print("   Report: .veratum/graph/GRAPH_REPORT.md   Query: `graph query \"<question>\"`")
        return 0
    if args.action == "status":
        st = graph_status(ws)
        _print_json(st) if args.json else print(
            "🕸️  graph: " + ("not built" if not st["built"] else "up to date" if not st["stale_files"]
                              else "{} stale file(s): {}".format(len(st["stale_files"]), ", ".join(st["stale_files"][:8]))))
        return 0
    if args.action == "watch":
        print("🕸️  [VERATUM GRAPH] watching for changes (Ctrl-C to stop)…")
        try:
            graph_watch(ws, interval=max(0.1, args.interval), debounce=max(0.0, args.debounce), cycles=args.cycles)
        except KeyboardInterrupt:
            print("stopped.")
        return 0
    if args.action == "semantic":
        sub = args.text[0] if args.text else "list"
        if sub == "list":
            pending = graph_semantic_pending(ws)
            if args.json:
                _print_json([rel for rel, _ in pending])
            else:
                print("🕸️  {} doc/asset file(s) without semantic notes{}".format(len(pending), ":" if pending else "."))
                for rel, _ in pending[:50]:
                    print("   - " + rel)
                if pending:
                    print('   Read each, then: graph semantic add --data \'{"source_file":"<file>","nodes":[{"label":"..."}],'
                          '"edges":[{"source":"..","target":"..","relation":"..."}]}\'')
            return 0
        if sub == "add":
            raw = args.data if args.data else Path(args.text[1]).read_text(encoding="utf-8") if len(args.text) > 1 else ""
            try:
                payload = json.loads(raw)
            except ValueError:
                raise VeratumError("graph semantic add needs JSON (--data '{...}' or a .json file).")
            res = graph_semantic_add(ws, payload)
            graph_build(ws)
            print("🕸️  semantic notes stored: {} file(s), {} node(s), {} edge(s); graph rebuilt.".format(
                res["files"], res["nodes"], res["edges"]))
            return 0
        raise VeratumError("graph semantic: use `list` or `add`.")
    if args.action != "export":
        graph_auto_refresh(ws)
    graph = graph_load(ws)
    if args.action in ("query", "path", "explain"):
        graph_hint_used(ws)  # the agent is using the graph: stop the "use the graph" reminders for this task
    if args.action == "export":
        for path in veratum_export.graph_export(ws, graph, args.format, args.out, max(10, args.max_nodes)):
            print("🕸️  exported → " + path)
    elif args.action == "report":
        print(graph_report(graph))
    elif args.action == "query":
        if not text:
            raise VeratumError("graph query needs a question.")
        print(graph_query(graph, text, mode=args.mode, depth=args.depth, budget=args.budget))
    elif args.action == "path":
        if len(args.text) != 2:
            raise VeratumError("graph path needs exactly two node names.")
        print(graph_path(graph, args.text[0], args.text[1]))
    elif args.action == "explain":
        if not text:
            raise VeratumError("graph explain needs a node name.")
        print(graph_explain(graph, text))
    else:
        res = graph_benchmark(ws, graph, text or "main")
        _print_json(res) if args.json else print(
            "📉 corpus ≈{} tokens vs query subgraph ≈{} tokens ({}× smaller)".format(
                res["corpus_tokens"], res["query_tokens"], res["reduction"]))
    return 0
