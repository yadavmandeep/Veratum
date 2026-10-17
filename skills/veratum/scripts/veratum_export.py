#!/usr/bin/env python3
"""
Veratum graph exports: self-contained HTML, SVG, Obsidian vault and Neo4j Cypher script. Stdlib only.
Loaded on demand by `graph export` (see veratum_graph.run_command).
"""
from __future__ import annotations

import os
import posixpath
import re
from pathlib import Path

from veratum_graph import _graph_degrees, _graph_label, graph_report


def to_posix(p: str) -> str:
    return p.replace("\\", "/")


def _err(message: str):
    import veratum_graph
    return veratum_graph.VeratumError(message)


# -- exports: html / svg / obsidian / cypher ------------------------------------------------------
_GRAPH_PALETTE = ["#4e79a7", "#f28e2b", "#e15759", "#76b7b2", "#59a14f", "#edc948", "#b07aa1", "#ff9da7", "#9c755f", "#bab0ac"]


def _graph_pick(graph: dict, max_nodes: int) -> tuple:
    deg = _graph_degrees(graph)
    chosen = {nid for nid, _ in sorted(deg.items(), key=lambda kv: (-kv[1], kv[0]))[:max_nodes]}
    nodes = [n for n in graph["nodes"] if n["id"] in chosen]
    links = [e for e in graph["edges"] if e["relation"] != "contains" and e["source"] in chosen and e["target"] in chosen]
    return nodes, links


def _graph_layout(ids: list, links: list, width: float = 1200.0, height: float = 800.0, iters: int = 40) -> dict:
    """Deterministic Fruchterman-Reingold layout (no randomness: start on a circle in sorted order)."""
    import math
    n = len(ids)
    if not n:
        return {}
    k = math.sqrt(width * height / n) * 0.8
    pos = {nid: [width / 2 + math.cos(2 * math.pi * i / n) * width * 0.4,
                 height / 2 + math.sin(2 * math.pi * i / n) * height * 0.4] for i, nid in enumerate(ids)}
    temp = width / 10
    for _ in range(iters):
        disp = {nid: [0.0, 0.0] for nid in ids}
        for i in range(n):
            a = ids[i]
            for j in range(i + 1, n):
                b = ids[j]
                dx, dy = pos[a][0] - pos[b][0], pos[a][1] - pos[b][1]
                d = math.sqrt(dx * dx + dy * dy) or 0.01
                f = k * k / d / d
                disp[a][0] += dx * f; disp[a][1] += dy * f
                disp[b][0] -= dx * f; disp[b][1] -= dy * f
        for e in links:
            a, b = e["source"], e["target"]
            dx, dy = pos[a][0] - pos[b][0], pos[a][1] - pos[b][1]
            d = math.sqrt(dx * dx + dy * dy) or 0.01
            f = d / k
            disp[a][0] -= dx * f; disp[a][1] -= dy * f
            disp[b][0] += dx * f; disp[b][1] += dy * f
        for nid in ids:
            dx, dy = disp[nid]
            d = math.sqrt(dx * dx + dy * dy) or 0.01
            step = min(d, temp)
            pos[nid][0] = min(width - 20, max(20, pos[nid][0] + dx / d * step))
            pos[nid][1] = min(height - 20, max(20, pos[nid][1] + dy / d * step))
        temp *= 0.92
    return pos


def graph_export_svg(graph: dict, max_nodes: int = 200) -> str:
    import html as _html
    nodes, links = _graph_pick(graph, max_nodes)
    ids = sorted(n["id"] for n in nodes)
    pos = _graph_layout(ids, links)
    by_id = {n["id"]: n for n in nodes}
    deg = _graph_degrees(graph)
    out = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1200 800" width="100%" font-family="sans-serif" font-size="10">',
           '<rect width="1200" height="800" fill="#ffffff"/>']
    for e in links:
        (x1, y1), (x2, y2) = pos[e["source"]], pos[e["target"]]
        style = {"EXTRACTED": 'stroke="#888" stroke-width="1"', "INFERRED": 'stroke="#aaa" stroke-dasharray="4 3"',
                 "AMBIGUOUS": 'stroke="#e15759" stroke-dasharray="1 3"'}[e["confidence"]]
        out.append('<line class="edge" x1="{:.0f}" y1="{:.0f}" x2="{:.0f}" y2="{:.0f}" {}><title>{}</title></line>'.format(
            x1, y1, x2, y2, style, _html.escape("{} [{}] {}:{}".format(e["relation"], e["confidence"], e["source_file"], e["source_location"]))))
    for nid in ids:
        n, (x, y) = by_id[nid], pos[nid]
        r = 4 + min(10, deg.get(nid, 0) ** 0.5 * 2)
        color = _GRAPH_PALETTE[(n.get("community") or 0) % len(_GRAPH_PALETTE)]
        out.append('<g class="node" data-label="{}"><circle cx="{:.0f}" cy="{:.0f}" r="{:.1f}" fill="{}"/>'
                   '<text x="{:.0f}" y="{:.0f}">{}</text><title>{}</title></g>'.format(
                       _html.escape(n["label"].lower()), x, y, r, color, x + r + 2, y + 3, _html.escape(_graph_label(n["label"])),
                       _html.escape("{} ({}) {}:{}".format(_graph_label(n["label"]), n["kind"], n["source_file"], n["source_location"]))))
    out.append("</svg>")
    return "\n".join(out)


def graph_export_html(graph: dict, max_nodes: int = 200) -> str:
    """Self-contained page: inline SVG + a tiny search box. No CDN, no external requests."""
    import html as _html
    st = graph["stats"]
    return ("<!doctype html><meta charset=\"utf-8\"><title>Veratum graph</title>"
            "<style>body{{font-family:sans-serif;margin:12px}}input{{padding:4px;width:260px}}.dim{{opacity:.12}}</style>"
            "<h3>Veratum graph — {} files, {} nodes, {} edges</h3>"
            "<p>Solid = EXTRACTED, dashed = INFERRED, red dotted = AMBIGUOUS. Colour = community. Showing the {} most connected nodes.</p>"
            "<input id=q placeholder=\"filter by name\">{}"
            "<script>document.getElementById('q').oninput=function(e){{var t=e.target.value.toLowerCase();"
            "document.querySelectorAll('.node').forEach(function(n){{n.classList.toggle('dim',t&&n.dataset.label.indexOf(t)<0)}})}}</script>"
            ).format(st["files"], st["nodes"], st["edges"], max_nodes, graph_export_svg(graph, max_nodes))


def graph_export_obsidian(graph: dict, out: Path) -> int:
    """One note per file/doc/asset with [[wiki links]] to the files it depends on and that depend on it."""
    out.mkdir(parents=True, exist_ok=True)
    nodes = {n["id"]: n for n in graph["nodes"]}
    holder = {n["source_file"]: n["id"] for n in graph["nodes"] if n["kind"] in ("file", "doc", "asset")}

    def safe(rel):
        return re.sub(r"[^\w.\-]", "_", rel.replace("/", "__"))

    def link(rel):
        return "[[{}|{}]]".format(safe(rel), re.sub(r"[\[\]|]", "", posixpath.basename(rel)))

    outgoing: dict = {}
    incoming: dict = {}
    for e in graph["edges"]:
        if e["relation"] == "contains":
            continue
        a, b = nodes[e["source"]]["source_file"], nodes[e["target"]]["source_file"]
        if a != b:
            outgoing.setdefault(a, {})[(b, e["relation"], e["confidence"])] = e["source_location"]
            incoming.setdefault(b, {})[(a, e["relation"], e["confidence"])] = e["source_location"]
    contains: dict = {}
    for n in graph["nodes"]:
        if n["kind"] not in ("file", "doc", "asset"):
            contains.setdefault(n["source_file"], []).append(n)
    for rel, nid in holder.items():
        n = nodes[nid]
        lines = ["# {}".format(_graph_label(n["label"])), "", "`{}` · {} · community {}".format(rel, n["kind"], n.get("community")), ""]
        if contains.get(rel):
            lines.append("## Contains")
            lines += ["- `{}` ({}) {}".format(_graph_label(s["label"]), s["kind"], s["source_location"]) for s in contains[rel][:100]]
            lines.append("")
        for title, table in (("Links to", outgoing), ("Linked from", incoming)):
            if table.get(rel):
                lines.append("## " + title)
                lines += ["- {} — {} [{}] {}".format(link(o), r, c, loc) for (o, r, c), loc in sorted(table[rel].items())[:100]]
                lines.append("")
        (out / (safe(rel) + ".md")).write_text("\n".join(lines), encoding="utf-8", newline="\n")
    comm = ["# Communities", ""] + ["- #{} `{}` — {} nodes, cohesion {}: {}".format(
        c["id"], c["name"], c["size"], c["cohesion"], " ".join(link(f) for f in c["files"][:12])) for c in graph["communities"] if c["size"] > 1]
    (out / "_Communities.md").write_text("\n".join(comm) + "\n", encoding="utf-8", newline="\n")
    (out / "_Report.md").write_text(graph_report(graph), encoding="utf-8", newline="\n")
    return len(holder)


def graph_export_cypher(graph: dict) -> str:
    """Neo4j import script (run with cypher-shell). No driver or network needed."""
    def q(v):
        return "'" + re.sub(r"[\x00-\x1f]", " ", str(v)).replace("\\", "\\\\").replace("'", "\\'") + "'"

    lines = ["// Veratum graph export — import with: cypher-shell < graph.cypher",
             "CREATE INDEX veratum_node_id IF NOT EXISTS FOR (n:Node) ON (n.id);"]
    for n in graph["nodes"]:
        lines.append("CREATE (:Node {{id: {}, label: {}, kind: {}, file: {}, loc: {}, community: {}}});".format(
            q(n["id"]), q(n["label"]), q(n["kind"]), q(n["source_file"]), q(n["source_location"]), int(n.get("community", -1))))
    for e in graph["edges"]:
        rel = re.sub(r"[^A-Z_]", "", e["relation"].upper()) or "RELATED_TO"
        lines.append("MATCH (a:Node {{id: {}}}), (b:Node {{id: {}}}) CREATE (a)-[:{} {{confidence: {}, score: {}, file: {}, loc: {}}}]->(b);".format(
            q(e["source"]), q(e["target"]), rel, q(e["confidence"]), float(e.get("confidence_score", 1.0)),
            q(e["source_file"]), q(e["source_location"])))
    return "\n".join(lines) + "\n"


def graph_export(ws, graph: dict, fmt: str, out: str | None, max_nodes: int = 200) -> list:
    base = ws.rel(out) if out else ".veratum/graph/export"
    if base is None:
        raise _err("--out must be inside the workspace.")
    root = ws.root / base
    written = []
    for kind in (["html", "svg", "obsidian", "cypher"] if fmt == "all" else [fmt]):
        if kind == "html":
            path = root / "graph.html"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(graph_export_html(graph, max_nodes), encoding="utf-8", newline="\n")
        elif kind == "svg":
            path = root / "graph.svg"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(graph_export_svg(graph, max_nodes), encoding="utf-8", newline="\n")
        elif kind == "cypher":
            path = root / "graph.cypher"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(graph_export_cypher(graph), encoding="utf-8", newline="\n")
        else:
            path = root / "obsidian"
            graph_export_obsidian(graph, path)
        written.append(to_posix(os.path.relpath(str(path), str(ws.root))))
    return written
