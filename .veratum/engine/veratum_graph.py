#!/usr/bin/env python3
"""
Veratum knowledge graph (build -> cluster -> analyze -> report -> query), stdlib only.

Loaded on demand by veratum_cli.py (`graph` command, session-start refresh). It uses the CLI's helpers
(Workspace, CodeIndex, read_json, ...) through `bind()`, so there is one copy of each class and one
VeratumError type whether the CLI runs as a script or is imported.
"""
from __future__ import annotations

import bisect
import json
import os
import posixpath
import re
import sys
import time
import uuid
from pathlib import Path

# Helpers owned by veratum_cli.py, injected by bind().
_CORE_NAMES = (
    "CONF_EXTRACTED", "CONF_INFERRED", "CodeIndex", "VeratumError", "Workspace", "_IMPORT_LINE_PREFIXES",
    "_print_json", "_read_text", "_sha256_file", "graph_hint_used", "now_iso", "read_json", "write_json",
    "to_posix", "norm_case",
)


def to_posix(p: str) -> str:
    return str(p).replace("\\", "/")


def norm_case(p: str) -> str:
    return str(p).lower() if os.name == "nt" else str(p)


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
                   "yield", "not", "and", "or", "in", "is", "lambda", "except", "raise", "del", "use", "import",
                   "echo", "local", "export", "let", "var", "const"}
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
    "c_sharp": [(r"^\s*(?:public\s+|private\s+|protected\s+|internal\s+|static\s+|sealed\s+|abstract\s+)*(?:class|interface|struct|enum|record)\s+(\w+)", "class"),
                (r"^\s*(?:public|private|protected|internal)\s+(?:static\s+|virtual\s+|override\s+|async\s+)*[\w<>\[\],.?]+\s+(\w+)\s*\(", "method")],
    "ruby": [(r"^\s*(?:class|module)\s+([A-Za-z_]\w*)", "class"), (r"^\s*def\s+([A-Za-z_]\w*)", "function")],
    "php": [(r"^\s*(?:abstract\s+|final\s+)?(?:class|interface|trait|enum)\s+(\w+)", "class"),
            (r"^\s*(?:public\s+|protected\s+|private\s+|static\s+)*function\s+(\w+)\s*\(", "function")],
    "bash": [(r"^\s*(?:function\s+)?([A-Za-z_]\w*)\s*\(\s*\)\s*\{", "function")],
    "lua": [(r"^\s*(?:local\s+)?function\s+([A-Za-z_][\w.]*)", "function")],
    "scala": [(r"^\s*(?:class|object|trait)\s+(\w+)", "class"), (r"^\s*def\s+(\w+)", "function")],
    "kotlin": [(r"^\s*(?:open\s+|data\s+|sealed\s+|abstract\s+)?(?:class|interface|object)\s+(\w+)", "class"),
               (r"^\s*(?:override\s+)?fun\s+(\w+)", "function")],
    "swift": [(r"^\s*(?:public\s+|private\s+|internal\s+)?(?:class|struct|protocol|enum)\s+(\w+)", "class"),
              (r"^\s*(?:public\s+|private\s+|internal\s+)?func\s+(\w+)", "function")],
    "elixir": [(r"^\s*defmodule\s+([A-Za-z_][\w.]*)", "class"), (r"^\s*defp?\s+([A-Za-z_]\w*)", "function")],
    "sql": [
        (r"(?i)^\s*(?:create\s+(?:or\s+replace\s+)?package(?:\s+body)?)\s+(\w+)", "class"),
        (r"(?i)^\s*(?:create\s+(?:or\s+replace\s+)?(?:procedure|function)|procedure|function)\s+(\w+)", "function"),
        (r"(?i)^\s*(?:create\s+(?:or\s+replace\s+)?trigger)\s+(\w+)", "function"),
    ],
}
_LANG_FALLBACK_MAP = {
    "ts": "js", "tsx": "js", "jsx": "js", "jsp": "js", "tag": "js", "vue": "js", "svelte": "js",
    "cpp": "c", "cc": "c", "cxx": "c", "h": "c", "hpp": "c", "hh": "c",
    "groovy": "java", "kt": "kotlin", "cs": "c_sharp", "rb": "ruby", "sh": "bash",
    "ex": "elixir", "jl": "julia", "ps1": "powershell", "python": "py", "rust": "rs", "golang": "go",
}
_GRAPH_CALL_RE = re.compile(r"(?<![\w$.])([A-Za-z_$][\w$]*)\s*\(|\.([A-Za-z_$][\w$]*)\s*\(")

_TS_LANG_SPECS = {
    "py": ("tree_sitter_python", "language"),
    "python": ("tree_sitter_python", "language"),
    "js": ("tree_sitter_javascript", "language"),
    "javascript": ("tree_sitter_javascript", "language"),
    "ts": ("tree_sitter_typescript", "language_typescript"),
    "typescript": ("tree_sitter_typescript", "language_typescript"),
    "tsx": ("tree_sitter_typescript", "language_tsx"),
    "jsx": ("tree_sitter_javascript", "language"),
    "go": ("tree_sitter_go", "language"),
    "rs": ("tree_sitter_rust", "language"),
    "rust": ("tree_sitter_rust", "language"),
    "java": ("tree_sitter_java", "language"),
    "c": ("tree_sitter_c", "language"),
    "cpp": ("tree_sitter_cpp", "language"),
    "cc": ("tree_sitter_cpp", "language"),
    "c_sharp": ("tree_sitter_c_sharp", "language"),
    "cs": ("tree_sitter_c_sharp", "language"),
    "rb": ("tree_sitter_ruby", "language"),
    "ruby": ("tree_sitter_ruby", "language"),
    "php": ("tree_sitter_php", "language_php"),
    "sh": ("tree_sitter_bash", "language"),
    "bash": ("tree_sitter_bash", "language"),
    "lua": ("tree_sitter_lua", "language"),
    "scala": ("tree_sitter_scala", "language"),
    "kt": ("tree_sitter_kotlin", "language"),
    "kotlin": ("tree_sitter_kotlin", "language"),
    "swift": ("tree_sitter_swift", "language"),
    "elixir": ("tree_sitter_elixir", "language"),
    "ex": ("tree_sitter_elixir", "language"),
    "groovy": ("tree_sitter_groovy", "language"),
    "julia": ("tree_sitter_julia", "language"),
    "jl": ("tree_sitter_julia", "language"),
    "powershell": ("tree_sitter_powershell", "language"),
    "ps1": ("tree_sitter_powershell", "language"),
    "objc": ("tree_sitter_objc", "language"),
    "zig": ("tree_sitter_zig", "language"),
    "json": ("tree_sitter_json", "language"),
}

_TREE_SITTER_PARSERS: dict = {}
_TREE_SITTER_FAILED_LANGS: set = set()

_CLASS_NODE_TYPES = {
    "class_definition", "class_declaration", "class_specifier", "class",
    "interface_declaration", "interface_definition",
    "trait_item", "trait_definition",
    "struct_item", "struct_specifier", "struct_declaration", "struct_definition",
    "enum_declaration", "enum_item", "enum_specifier",
    "type_declaration", "type_alias_declaration", "type_item", "type_spec",
    "protocol_declaration", "record_declaration",
    "object_declaration", "object_definition",
    "module", "impl_item"
}

_FUNC_NODE_TYPES = {
    "function_definition", "function_declaration", "function_item", "function",
    "method_definition", "method_declaration", "method", "singleton_method",
    "constructor_declaration", "local_function", "function_statement", "method_signature"
}

_TYPE_KINDS = {
    "interface_declaration", "interface_definition", "trait_item", "trait_definition",
    "enum_declaration", "enum_item", "enum_specifier", "type_declaration",
    "type_alias_declaration", "type_item", "type_spec", "protocol_declaration"
}


def _get_tree_sitter_parser(lang: str):
    if lang in _TREE_SITTER_PARSERS:
        return _TREE_SITTER_PARSERS[lang]
    if lang in _TREE_SITTER_FAILED_LANGS:
        return None
    spec = _TS_LANG_SPECS.get(lang)
    if not spec:
        _TREE_SITTER_FAILED_LANGS.add(lang)
        return None
    mod_name, fn_name = spec
    try:
        import importlib
        import tree_sitter
        mod = importlib.import_module(mod_name)
        lang_fn = getattr(mod, fn_name, None) or getattr(mod, "language", None)
        if not lang_fn:
            _TREE_SITTER_FAILED_LANGS.add(lang)
            return None
        ts_lang = tree_sitter.Language(lang_fn())
        parser = tree_sitter.Parser(ts_lang)
        _TREE_SITTER_PARSERS[lang] = parser
        return parser
    except (ImportError, Exception):
        _TREE_SITTER_FAILED_LANGS.add(lang)
        return None


def _get_ts_call_name(node):
    if node.type == "command":
        named = [c for c in node.children if c.is_named]
        if named:
            raw = named[0].text.decode("utf-8", errors="ignore").strip()
            if raw and raw not in _GRAPH_KEYWORDS and re.match(r"^[A-Za-z_$][\w$]*$", raw):
                return raw
        return None

    target = (node.child_by_field_name("function") or
              node.child_by_field_name("name") or
              node.child_by_field_name("method"))
    if not target and node.children:
        named = [c for c in node.children if c.is_named]
        if named:
            target = named[0]
    if not target:
        return None

    if target.type in ("member_expression", "field_expression", "attribute", "scoped_identifier", "selector_expression"):
        prop = (target.child_by_field_name("property") or
                target.child_by_field_name("field") or
                target.child_by_field_name("name"))
        if prop:
            target = prop
        else:
            named = [c for c in target.children if c.is_named]
            if named:
                target = named[-1]

    raw = target.text.decode("utf-8", errors="ignore").strip()
    raw = raw.split(".")[-1].split("::")[-1].split("->")[-1]
    if raw and raw not in _GRAPH_KEYWORDS and re.match(r"^[A-Za-z_$][\w$]*$", raw):
        return raw
    return None


def _get_ts_def_name(node):
    name_node = node.child_by_field_name("name")
    if name_node:
        return name_node.text.decode("utf-8", errors="ignore").strip()
    if node.type == "impl_item":
        t = node.child_by_field_name("type")
        if t:
            return t.text.decode("utf-8", errors="ignore").strip()
    if node.type == "function_definition":
        decl = node.child_by_field_name("declarator")
        while decl and decl.type in ("function_declarator", "pointer_declarator", "reference_declarator"):
            inner = decl.child_by_field_name("declarator")
            if inner:
                decl = inner
            else:
                named = [c for c in decl.children if c.is_named]
                decl = named[0] if named else None
        if decl and decl.type in ("identifier", "field_identifier"):
            return decl.text.decode("utf-8", errors="ignore").strip()
    if node.type == "function_statement":
        for c in node.children:
            if c.type == "function_name":
                return c.text.decode("utf-8", errors="ignore").strip()
    if node.type == "variable_declarator":
        name_node = node.child_by_field_name("name")
        val = node.child_by_field_name("value")
        if name_node and val and val.type in ("arrow_function", "function_expression", "function"):
            return name_node.text.decode("utf-8", errors="ignore").strip()
    return None


def _get_go_receiver(node):
    rec = node.child_by_field_name("receiver")
    if not rec:
        return None
    for c in rec.children:
        if c.type == "parameter_declaration":
            for sc in c.children:
                if sc.type in ("type_identifier", "pointer_type"):
                    raw = sc.text.decode("utf-8", errors="ignore").strip().lstrip("*")
                    if raw:
                        return raw
    return None


def _extract_tree_sitter(text: str, lang: str):
    parser = _get_tree_sitter_parser(lang)
    if not parser:
        return None

    code_bytes = text.encode("utf-8")
    try:
        tree = parser.parse(code_bytes)
    except Exception:
        return None

    defs: list = []
    calls: list = []

    def visit(node, scope, owner):
        nonlocal defs, calls
        ntype = node.type

        if ntype == "variable_declarator":
            val = node.child_by_field_name("value")
            if val and val.type in ("arrow_function", "function_expression", "function"):
                name = _get_ts_def_name(node)
                if name:
                    qual = ".".join([s[0] for s in scope] + [name])
                    kind = "method" if scope and scope[-1][1] else "function"
                    defs.append({"name": name, "qual": qual, "kind": kind,
                                 "line": node.start_point[0] + 1, "end": node.end_point[0] + 1})
                    for c in val.children:
                        visit(c, scope + [(name, False)], qual)
                    return

        is_class = ntype in _CLASS_NODE_TYPES
        is_func = ntype in _FUNC_NODE_TYPES

        if is_class or is_func:
            name = _get_ts_def_name(node)
            if name:
                cur_scope = scope
                if ntype == "method_declaration":
                    rec = _get_go_receiver(node)
                    if rec:
                        cur_scope = [(rec, True)]
                qual = ".".join([s[0] for s in cur_scope] + [name])
                if is_class:
                    kind = "type" if ntype in _TYPE_KINDS else "class"
                else:
                    kind = "method" if cur_scope and cur_scope[-1][1] else "function"
                defs.append({"name": name, "qual": qual, "kind": kind,
                             "line": node.start_point[0] + 1, "end": node.end_point[0] + 1})
                new_scope = cur_scope + [(name, is_class)]
                new_owner = qual
                for c in node.children:
                    visit(c, new_scope, new_owner)
                return

        if "call" in ntype or "invocation" in ntype or ntype == "command":
            cname = _get_ts_call_name(node)
            if cname:
                calls.append({"name": cname, "line": node.start_point[0] + 1, "owner": owner})

        for c in node.children:
            visit(c, scope, owner)

    visit(tree.root_node, [], "")
    if getattr(tree.root_node, "has_error", False) and not defs:
        return None
    return {"defs": defs, "calls": calls}


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
    pats = _GRAPH_DEF_PATTERNS.get(lang) or _GRAPH_DEF_PATTERNS.get(_LANG_FALLBACK_MAP.get(lang, ""), [])
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if not stripped or stripped.startswith(("//", "#", "*", "/*")):
            continue
        for pat, kind in pats:
            m = re.match(pat, line)
            if m and m.group(1) not in _GRAPH_KEYWORDS:
                defs.append({"name": m.group(1), "qual": m.group(1), "kind": kind, "line": i, "end": len(lines)})
                break
    for a, b in zip(defs, defs[1:]):
        a["end"] = max(a["line"], b["line"] - 1)
    def_lines = {d["line"]: d for d in defs}
    starts = [d["line"] for d in defs]
    calls: list = []
    for i, line in enumerate(lines, 1):
        stripped = line.strip()
        if i in def_lines or not stripped or stripped.startswith(("//", "#", "*", "/*") + _IMPORT_LINE_PREFIXES):
            continue
        k = bisect.bisect_right(starts, i) - 1  # the definition whose range holds this line
        owner = defs[k]["qual"] if k >= 0 and i <= defs[k]["end"] else ""
        for m in _GRAPH_CALL_RE.finditer(line):
            name = m.group(1) or m.group(2)
            if name and name not in _GRAPH_KEYWORDS:
                calls.append({"name": name, "line": i, "owner": owner})
        if len(calls) > 4000:
            break
    return {"defs": defs, "calls": calls}


def graph_extract_file(text: str, lang: str) -> dict:
    result = _extract_tree_sitter(text, lang)
    if result is None:
        result = (_extract_python_ast(text) if lang in ("py", "python") else None) or _extract_generic(text, lang)
    seen: set = set()  # one call per (name, caller) is enough for the graph and keeps cache.json small
    unique = []
    for call in result["calls"]:
        key = (call["name"], call["owner"])
        if key not in seen:
            seen.add(key)
            unique.append(call)
    result["calls"] = unique
    return result


def _import_tokens(data: dict) -> set:
    raw: list = []
    raw += data.get("specs", []) + data.get("imports", []) + data.get("uses", []) + data.get("mods", [])
    raw += data.get("includes", [])
    for module, names in data.get("stmts", []):
        raw.append(module)
        raw += names
    return {t.lower() for r in raw for t in re.split(r"[/.:\\\-@~#*{}\s,]+", str(r)) if t}


def _dump_json(path: Path, data) -> None:
    """Compact, streamed JSON (no indent, no giant intermediate string): the graph can have millions of edges."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(data, fh, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, path)


def graph_build(ws: Workspace, full: bool = False, max_files: int = 0, max_file_kb: int = 5120, progress=None) -> dict:
    """Build/refresh .veratum/graph/. Per-file extraction is cached by content hash (incremental).
    max_files=0 means every file; max_file_kb skips huge (generated/minified) sources, 0 = no size limit."""
    gdir = ws.dir / "graph"
    index = CodeIndex(ws, max_files=max_files or None)
    old = read_json(gdir / "cache.json", {}) or {}
    cache = {} if full or old.get("schema") != GRAPH_SCHEMA else old.get("files", {})
    history_cache = {} if full or old.get("schema") != GRAPH_SCHEMA else old.get("history_cache", {})
    extracted: dict = {}
    fresh = reused = skipped_large = 0
    total = len(index.files)
    for n, rel in enumerate(index.files, 1):
        if progress and total > 5000 and n % 5000 == 0:
            progress("   … {}/{} files".format(n, total))
        path = ws.root / rel
        try:
            st = path.stat()
            if max_file_kb and st.st_size > max_file_kb * 1024:
                skipped_large += 1
                continue
            hit = cache.get(rel)
            if hit and hit.get("size") == st.st_size and hit.get("mtime") == st.st_mtime_ns:
                sha = hit["sha"]  # same size and mtime: skip re-hashing (this is what keeps updates fast on huge repos)
            else:
                sha = _sha256_file(path)
        except OSError:
            continue
        if hit and hit.get("sha") == sha:
            data = hit["data"]
            reused += 1
        else:
            data = graph_extract_file(_read_text(path), index.lang(rel))
            fresh += 1
        extracted[rel] = {"sha": sha, "size": st.st_size, "mtime": st.st_mtime_ns, "data": data}

    nodes: dict = {}
    edges: list = []
    defs_by_name: dict = {}
    defs_by_nf: dict = {}  # (name, file) -> [(node id, file)] : constant-time same-file / imported-file lookups
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
            defs_by_nf.setdefault((d["name"], rel), []).append((sid, rel))
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
    index._parsed.clear()  # parsed import data is not needed any more: free it before the call pass
    by_token.clear()

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
            same = defs_by_nf.get((name, rel), [])
            via_import = [c for f in imported.get(rel, ()) for c in defs_by_nf.get((name, f), [])]
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
    doc_stats.update(_graph_add_history(ws, nodes, edges, history_cache=history_cache))
    communities = _graph_cluster(nodes, edges)
    for nid, node in nodes.items():
        node["community"] = communities["of"].get(nid, -1)
    graph = {"schema": GRAPH_SCHEMA, "built_at": now_iso(),
             "stats": {"files": len(extracted), "nodes": len(nodes), "edges": len(edges),
                       "extracted_now": fresh, "from_cache": reused,
                       "truncated": bool(max_files) and len(index.files) >= max_files, "skipped_large": skipped_large,
                       **doc_stats},
             "communities": communities["list"], "nodes": list(nodes.values()), "edges": edges}
    rep_text = graph_report(graph)
    _dump_json(gdir / "graph.json", graph)
    _dump_json(gdir / "cache.json", {"schema": GRAPH_SCHEMA, "max_file_kb": max_file_kb, "files": extracted, "history_cache": history_cache})
    (gdir / "GRAPH_REPORT.md").write_text(rep_text, encoding="utf-8", newline="\n")

    # Date-wise snapshot folder (Graphify layout: .veratum/graph/YYYY-MM-DD/)
    today = (graph.get("built_at") or now_iso())[:10]
    date_dir = gdir / today
    date_dir.mkdir(parents=True, exist_ok=True)
    _dump_json(date_dir / "graph.json", graph)
    _dump_json(date_dir / "cache.json", {"schema": GRAPH_SCHEMA, "max_file_kb": max_file_kb, "files": extracted, "history_cache": history_cache})
    (date_dir / "GRAPH_REPORT.md").write_text(rep_text, encoding="utf-8", newline="\n")
    _auto_write_html_views(gdir, date_dir, graph)
    return graph


def _load_date_snapshots(gdir: Path) -> dict:
    snapshots = {}
    if not gdir.is_dir():
        return snapshots
    for item in sorted(gdir.iterdir()):
        if item.is_dir() and re.match(r"^\d{4}-\d{2}-\d{2}$", item.name):
            snap_file = item / "graph.json"
            if snap_file.is_file():
                try:
                    with open(snap_file, "r", encoding="utf-8") as f:
                        snapshots[item.name] = json.load(f)
                except Exception:
                    pass
    return snapshots


def _auto_write_html_views(gdir: Path, date_dir: Path, graph: dict) -> None:
    try:
        import veratum_export
        snapshots = _load_date_snapshots(gdir)
        html_text = veratum_export.graph_export_html(graph, max_nodes=5000, snapshots=snapshots)
        (gdir / "index.html").write_text(html_text, encoding="utf-8", newline="\n")
        (gdir / "graph.html").write_text(html_text, encoding="utf-8", newline="\n")
        (date_dir / "index.html").write_text(html_text, encoding="utf-8", newline="\n")
        (date_dir / "graph.html").write_text(html_text, encoding="utf-8", newline="\n")
        local_vis = gdir / "vis-network.min.js"
        if local_vis.is_file() and not (date_dir / "vis-network.min.js").is_file():
            try:
                (date_dir / "vis-network.min.js").write_bytes(local_vis.read_bytes())
            except Exception:
                pass
    except Exception:
        pass


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
        top_node_id = max(members, key=lambda n: (sum(adj[n].values()), nodes[n].get("label", "")))
        top_node = nodes[top_node_id]
        top_lbl = top_node.get("label", top_node_id)
        if top_node.get("kind") in ("function", "method") and not top_lbl.endswith("()"):
            comm_name = top_lbl + "()"
        else:
            comm_name = top_lbl
        out.append({"id": cid, "name": comm_name,
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
    doc = read_json(ws.dir / "graph" / "cache.json", {}) or {}
    cache, limit_kb = doc.get("files", {}), doc.get("max_file_kb", 5120)
    if not cache or not (ws.dir / "graph" / "graph.json").exists():
        return {"built": False, "stale_files": []}
    files = CodeIndex(ws, max_files=None).files
    present = set(files)
    stale = []
    for f in files:
        try:
            st = (ws.root / f).stat()
            if limit_kb and st.st_size > limit_kb * 1024:
                continue  # skipped as too large when the graph was built
            hit = cache.get(f)
            if not hit:
                stale.append(f)
            elif hit.get("size") != st.st_size or hit.get("mtime") != st.st_mtime_ns:
                if hit.get("sha") != _sha256_file(ws.root / f):  # touched but unchanged content is not stale
                    stale.append(f)
        except OSError:
            stale.append(f)
    stale += [f for f in cache if f not in present]
    return {"built": True, "stale_files": sorted(set(stale))}


# -- documents, assets and agent-supplied semantic extraction ---------------------------------
# Full Graphify format coverage: docs, papers, images, office, and audio/video
_DOC_EXTS = (".md", ".mdx", ".rst", ".txt", ".yml", ".yaml", ".html", ".htm", ".qmd", ".skill", ".org", ".adoc", ".tex")
_ASSET_EXTS = (
    # Papers & office docs
    ".pdf", ".docx", ".xlsx", ".pptx", ".odt", ".ods", ".odp",
    # Images
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp", ".ico", ".tiff",
    # Audio & video
    ".mp4", ".mov", ".ogg", ".webm", ".avi", ".m4a", ".wav", ".m4v", ".mkv", ".mp3"
)
_MD_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*#*\s*$")
_MD_LINK_RE = re.compile(r"\[[^\]\n]*\]\(([^)\s#?]+)[^)]*\)")
_BACKTICK_RE = re.compile(r"`([A-Za-z_][\w.]*)(?:\(\))?`")


_IMG_EMBED_RE = re.compile(r"""(?:!\[[^\]\n]*\]\(([^)\s#?]+)[^)]*\)|<img[^>]+src=["']([^"']+)["'])""")
_HTML_HEADING_RE = re.compile(r"""<h([1-6])[^>]*>(.*?)</h\1>""", re.I)
_HTML_LINK_RE = re.compile(r"""<a[^>]+href=["']([^"']+)["']""", re.I)


def _graph_add_docs(ws: Workspace, index: "CodeIndex", nodes: dict, edges: list, defs_by_name: dict) -> dict:
    """Markdown/text docs become nodes: headings (EXTRACTED), relative links (EXTRACTED), `code` mentions (INFERRED),
    image/media references (EXTRACTED).
    Assets (PDF/images/video/office) become first-class asset nodes linked to documents and ready for semantic enrichment."""
    from urllib.parse import unquote
    files = index._list_files(None, exts=_DOC_EXTS + _ASSET_EXTS)
    by_rel = {n["source_file"]: nid for nid, n in nodes.items() if n["kind"] == "file"}
    docs = assets = 0
    for rel in files:
        ext = os.path.splitext(rel)[1].lower()
        is_doc = ext in _DOC_EXTS
        nid = ("doc:" if is_doc else "asset:") + rel
        lang = "markdown" if ext in (".md", ".mdx") else (ext.lstrip(".") or "text")
        nodes[nid] = {"id": nid, "label": posixpath.basename(rel), "kind": "doc" if is_doc else "asset",
                      "source_file": rel, "source_location": "L1", "language": lang}
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
            # Markdown heading or HTML heading
            m = _MD_HEADING_RE.match(line)
            m_html = _HTML_HEADING_RE.search(line) if not m else None
            h_text = m.group(2) if m else (re.sub(r"<[^>]+>", "", m_html.group(2)).strip() if m_html else None)
            if h_text:
                current = "sec:{}::{}".format(rel, i)
                nodes[current] = {"id": current, "label": _graph_label(h_text), "kind": "section",
                                  "source_file": rel, "source_location": "L{}".format(i), "language": "markdown"}
                edges.append({"source": doc_id, "target": current, "relation": "contains", "confidence": CONF_EXTRACTED,
                              "confidence_score": 1.0, "source_file": rel, "source_location": "L{}".format(i)})

            # Image & media embeds: ![alt](path) or <img src="path">
            for match in _IMG_EMBED_RE.finditer(line):
                raw_src = match.group(1) or match.group(2)
                if not raw_src or "://" in raw_src or raw_src.startswith(("data:", "mailto:", "/")):
                    continue
                target = by_rel.get(posixpath.normpath(posixpath.join(posixpath.dirname(rel), unquote(raw_src))))
                if target and target != doc_id:
                    edges.append({"source": current, "target": target, "relation": "embeds",
                                  "confidence": CONF_EXTRACTED, "confidence_score": 1.0, "source_file": rel,
                                  "source_location": "L{}".format(i)})

            # Links: [text](path) or <a href="path">
            raw_links = _MD_LINK_RE.findall(line) + _HTML_LINK_RE.findall(line)
            for link in raw_links:
                if "://" in link or link.startswith(("mailto:", "/", "#")):
                    continue
                target = by_rel.get(posixpath.normpath(posixpath.join(posixpath.dirname(rel), unquote(link))))
                if target and target != doc_id:
                    edges.append({"source": current, "target": target, "relation": "references",
                                  "confidence": CONF_EXTRACTED, "confidence_score": 1.0, "source_file": rel,
                                  "source_location": "L{}".format(i)})

            # Code mentions: `foo`
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
    files = files if files is not None else CodeIndex(ws, max_files=None)._list_files(None, exts=_DOC_EXTS + _ASSET_EXTS)
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


# -- date-wise task & query history (Graphify-aligned) -----------------------------------
def record_task_history(ws: Workspace, task_data: dict) -> Path:
    """Store completed task/query in date-wise folder: .veratum/graph/<YYYY-MM-DD>/<id>.json and tasks.json."""
    completed_at = task_data.get("completed_at") or now_iso()
    date_str = str(completed_at)[:10]  # YYYY-MM-DD
    target_dir = ws.dir / "graph" / date_str
    target_dir.mkdir(parents=True, exist_ok=True)
    tid = task_data.get("id") or task_data.get("contract_id") or ("task-" + uuid.uuid4().hex[:8])
    clean_id = re.sub(r"[^\w\-.]", "_", str(tid))
    target_path = target_dir / "{}.json".format(clean_id)
    payload = dict(task_data)
    payload.setdefault("id", tid)
    payload.setdefault("date", date_str)
    payload.setdefault("completed_at", completed_at)
    if "files_changed" in payload and isinstance(payload["files_changed"], list):
        payload["files_changed"] = [str(f).replace("\\", "/").strip() for f in payload["files_changed"] if f]
    if "files" in payload and isinstance(payload["files"], list):
        payload["files"] = [str(f).replace("\\", "/").strip() for f in payload["files"] if f]
    write_json(target_path, payload)

    # Maintain tasks.json in date folder (aggregate array of tasks/queries)
    tasks_file = target_dir / "tasks.json"
    tasks_list = read_json(tasks_file, []) or []
    if not isinstance(tasks_list, list):
        tasks_list = []
    tasks_list = [t for t in tasks_list if isinstance(t, dict) and t.get("id") != tid] + [payload]
    write_json(tasks_file, tasks_list)
    return target_path


def _graph_add_history(ws: Workspace, nodes: dict, edges: list, history_cache: dict | None = None) -> dict:
    """Scan date-wise folders (.veratum/graph/<YYYY-MM-DD>/) and add all task nodes and edges.
    Reuses cached date folder parse results by folder mtime_ns for sub-50ms performance."""
    gdir = ws.dir / "graph"
    if not gdir.is_dir():
        return {"history_tasks": 0, "history_edges": 0}
    by_file = {to_posix(n["source_file"]): nid for nid, n in nodes.items() if n.get("kind") in ("file", "doc", "asset")}
    by_file_lower = {norm_case(to_posix(n["source_file"])): nid for nid, n in nodes.items() if n.get("kind") in ("file", "doc", "asset")}
    tasks_count = edges_count = 0
    date_dirs = []
    date_re = re.compile(r"^\d{4}-\d{2}-\d{2}$")
    try:
        for p in gdir.iterdir():
            if p.is_dir():
                if date_re.match(p.name):
                    date_dirs.append(p)
                elif p.name == "history":
                    for sub in p.iterdir():
                        if sub.is_dir() and date_re.match(sub.name):
                            date_dirs.append(sub)
    except OSError:
        return {"history_tasks": 0, "history_edges": 0}

    new_history_cache = dict(history_cache or {})
    seen_tasks = set()
    for date_entry in sorted(date_dirs, key=lambda d: d.name):
        date_str = date_entry.name
        try:
            folder_st = date_entry.stat()
            folder_mtime = folder_st.st_mtime_ns
        except OSError:
            folder_mtime = 0

        cached_folder = new_history_cache.get(date_str)
        if cached_folder and cached_folder.get("mtime_ns") == folder_mtime:
            # Fast-path: folder hasn't changed! Load from history_cache
            for tnode in cached_folder.get("nodes", []):
                nid = tnode["id"]
                if nid not in nodes:
                    nodes[nid] = dict(tnode)
                    tasks_count += 1
                    if nid.startswith("task:"):
                        seen_tasks.add(nid[5:])
            for tedge in cached_folder.get("edges", []):
                tgt = tedge["target"]
                sf = tedge.get("target_file")
                if tgt not in nodes and sf and (ws.root / sf).exists():
                    nodes[tgt] = {
                        "id": tgt, "label": posixpath.basename(sf), "kind": "file",
                        "source_file": sf, "source_location": "L1",
                        "language": sf.split(".")[-1] if "." in sf else "text",
                    }
                if tgt in nodes:
                    edges.append(dict(tedge))
                    edges_count += 1
            continue

        folder_nodes = []
        folder_edges = []
        try:
            files_in_date = sorted(date_entry.iterdir())
        except OSError:
            continue
        for child_file in files_in_date:
            if not child_file.is_file():
                continue
            fname = child_file.name
            # Skip snapshot files of the graph itself to avoid indexing full graph snapshot as a task
            if fname in ("graph.json", "cache.json", "GRAPH_REPORT.md", ".graphify_labels.json", "manifest.json", "cost.json", "index.html", "graph.html", "vis-network.min.js"):
                continue
            rel_path = ws.rel(str(child_file)) or str(child_file).replace("\\", "/")
            if child_file.suffix.lower() == ".json":
                try:
                    data = read_json(child_file, None)
                except Exception:
                    continue
                if not data:
                    continue
                items = data if isinstance(data, list) else [data]
                for idx, item in enumerate(items):
                    if not isinstance(item, dict):
                        continue
                    tid = item.get("id") or item.get("contract_id") or "{}_{}".format(child_file.stem, idx)
                    if tid in seen_tasks:
                        continue
                    seen_tasks.add(tid)
                    node_id = "task:" + str(tid)
                    if node_id in nodes:
                        continue
                    goal = item.get("goal") or item.get("query") or item.get("title") or str(tid)
                    completed_at = item.get("completed_at") or item.get("at") or date_str
                    tnode = {
                        "id": node_id,
                        "label": _graph_label(goal),
                        "kind": "task",
                        "source_file": rel_path,
                        "source_location": "L1",
                        "language": "task",
                        "date": date_str,
                        "completed_at": completed_at,
                    }
                    nodes[node_id] = tnode
                    folder_nodes.append(tnode)
                    tasks_count += 1
                    target_files = item.get("files_changed") or item.get("files") or item.get("touched") or []
                    for f in target_files:
                        if not isinstance(f, str) or not f.strip():
                            continue
                        clean_f = to_posix(f).strip()
                        file_id = by_file.get(clean_f) or by_file_lower.get(norm_case(clean_f)) or ("file:" + clean_f)
                        if file_id not in nodes and (ws.root / clean_f).exists():
                            nodes[file_id] = {
                                "id": file_id,
                                "label": posixpath.basename(clean_f),
                                "kind": "file",
                                "source_file": clean_f,
                                "source_location": "L1",
                                "language": clean_f.split(".")[-1] if "." in clean_f else "text",
                            }
                            by_file[clean_f] = file_id
                            by_file_lower[norm_case(clean_f)] = file_id
                        if file_id in nodes:
                            tedge = {
                                "source": node_id,
                                "target": file_id,
                                "relation": "modified",
                                "confidence": CONF_EXTRACTED,
                                "confidence_score": 1.0,
                                "source_file": rel_path,
                                "source_location": "L1",
                                "target_file": clean_f,
                            }
                            edges.append(tedge)
                            folder_edges.append(tedge)
                            edges_count += 1
            else:
                # Any other file inside the date folder (e.g. notes.txt): add as history node
                node_id = "histfile:" + rel_path
                if node_id not in nodes:
                    hnode = {
                        "id": node_id,
                        "label": child_file.name,
                        "kind": "history",
                        "source_file": rel_path,
                        "source_location": "L1",
                        "language": child_file.suffix.lstrip(".").lower() or "text",
                        "date": date_str,
                    }
                    nodes[node_id] = hnode
                    folder_nodes.append(hnode)
                    tasks_count += 1

        new_history_cache[date_str] = {
            "mtime_ns": folder_mtime,
            "nodes": folder_nodes,
            "edges": folder_edges,
        }

    if history_cache is not None:
        history_cache.clear()
        history_cache.update(new_history_cache)
    return {"history_tasks": tasks_count, "history_edges": edges_count}


def graph_update_task(ws: Workspace, task_data: dict, files_changed: list | None = None) -> dict:
    """Sub-50ms incremental graph update when a task completes.
    Updates only changed files and connects the new task node and modified edges in graph.json and date snapshots.
    Falls back to graph_build(ws) if graph.json does not exist.
    """
    gdir = ws.dir / "graph"
    graph_file = gdir / "graph.json"
    cache_file = gdir / "cache.json"
    if not graph_file.is_file() or not cache_file.is_file():
        return graph_build(ws)

    graph = read_json(graph_file, None)
    if not isinstance(graph, dict) or "nodes" not in graph or "edges" not in graph:
        return graph_build(ws)

    cache = read_json(cache_file, {}) or {}
    cached_files = cache.get("files", {})
    history_cache = cache.get("history_cache", {})

    nodes = {n["id"]: n for n in graph.get("nodes", [])}
    edges = list(graph.get("edges", []))
    by_file = {to_posix(n.get("source_file", "")): nid for nid, n in nodes.items() if n.get("kind") in ("file", "doc", "asset")}
    by_file_lower = {norm_case(to_posix(n.get("source_file", ""))): nid for nid, n in nodes.items() if n.get("kind") in ("file", "doc", "asset")}

    # Clean & normalize changed files
    raw_files = list(files_changed or task_data.get("files_changed") or task_data.get("files") or [])
    files_to_update = [to_posix(f).strip() for f in raw_files if f]

    index = CodeIndex(ws)
    for rel in files_to_update:
        path = ws.root / rel
        fid = "file:" + rel
        if not path.exists():
            nodes.pop(fid, None)
            cached_files.pop(rel, None)
            sym_prefix = "sym:{}::".format(rel)
            nodes = {k: v for k, v in nodes.items() if not k.startswith(sym_prefix)}
            edges = [e for e in edges if e.get("source") != fid and e.get("target") != fid
                     and not str(e.get("source", "")).startswith(sym_prefix)
                     and not str(e.get("target", "")).startswith(sym_prefix)]
        else:
            try:
                st = path.stat()
                sha = _sha256_file(path)
                old_entry = cached_files.get(rel)
                if not old_entry or old_entry.get("sha") != sha or old_entry.get("size") != st.st_size:
                    lang = index.lang(rel)
                    data = graph_extract_file(_read_text(path), lang)
                    cached_files[rel] = {"sha": sha, "size": st.st_size, "mtime": st.st_mtime_ns, "data": data}

                    file_comm = nodes.get(fid, {}).get("community", 0)
                    if fid not in nodes:
                        nodes[fid] = {
                            "id": fid, "label": posixpath.basename(rel), "kind": "file",
                            "source_file": rel, "source_location": "L1", "language": lang,
                            "community": file_comm
                        }

                    # Remove old symbol nodes and contains edges for this file
                    sym_prefix = "sym:{}::".format(rel)
                    nodes = {k: v for k, v in nodes.items() if not k.startswith(sym_prefix)}
                    edges = [e for e in edges if not (e.get("source") == fid and e.get("relation") == "contains")
                             and not str(e.get("source", "")).startswith(sym_prefix)
                             and not str(e.get("target", "")).startswith(sym_prefix)]

                    # Add new symbols and contains edges
                    for d in data.get("defs", []):
                        sid = "sym:{}::{}".format(rel, d["qual"])
                        if sid in nodes:
                            sid += "@{}".format(d["line"])
                        nodes[sid] = {
                            "id": sid, "label": d["name"], "kind": d["kind"], "source_file": rel,
                            "source_location": "L{}".format(d["line"]), "language": lang,
                            "community": file_comm
                        }
                        edges.append({
                            "source": fid, "target": sid, "relation": "contains", "confidence": CONF_EXTRACTED,
                            "confidence_score": 1.0, "source_file": rel, "source_location": "L{}".format(d["line"])
                        })
            except OSError:
                pass

    # Add task node & modified edges
    tid = task_data.get("id") or task_data.get("contract_id") or ("task-" + uuid.uuid4().hex[:8])
    clean_id = re.sub(r"[^\w\-.]", "_", str(tid))
    node_id = "task:" + str(tid)
    goal = task_data.get("goal") or task_data.get("query") or str(tid)
    completed_at = task_data.get("completed_at") or now_iso()
    date_str = str(completed_at)[:10]

    task_comm = 0
    for f in files_to_update:
        fid = "file:" + f
        if fid in nodes and "community" in nodes[fid]:
            task_comm = nodes[fid]["community"]
            break

    rel_task_source = ".veratum/graph/{}/{}.json".format(date_str, clean_id)
    nodes[node_id] = {
        "id": node_id,
        "label": _graph_label(goal),
        "kind": "task",
        "source_file": rel_task_source,
        "source_location": "L1",
        "language": "task",
        "date": date_str,
        "completed_at": completed_at,
        "community": task_comm,
    }

    seen_targets = set()
    for f in files_to_update:
        clean_f = to_posix(f).strip()
        if not clean_f or clean_f in seen_targets:
            continue
        seen_targets.add(clean_f)
        fid = by_file.get(clean_f) or by_file_lower.get(norm_case(clean_f)) or ("file:" + clean_f)
        if fid not in nodes and (ws.root / clean_f).exists():
            nodes[fid] = {
                "id": fid,
                "label": posixpath.basename(clean_f),
                "kind": "file",
                "source_file": clean_f,
                "source_location": "L1",
                "language": clean_f.split(".")[-1] if "." in clean_f else "text",
                "community": task_comm,
            }
            by_file[clean_f] = fid
            by_file_lower[norm_case(clean_f)] = fid
        if fid in nodes:
            edge_exists = any(e.get("source") == node_id and e.get("target") == fid and e.get("relation") == "modified" for e in edges)
            if not edge_exists:
                edges.append({
                    "source": node_id,
                    "target": fid,
                    "relation": "modified",
                    "confidence": CONF_EXTRACTED,
                    "confidence_score": 1.0,
                    "source_file": rel_task_source,
                    "source_location": "L1",
                    "target_file": clean_f,
                })

    graph["built_at"] = now_iso()
    stats = graph.setdefault("stats", {})
    stats["nodes"] = len(nodes)
    stats["edges"] = len(edges)
    stats["files"] = len(cached_files)
    stats["history_tasks"] = sum(1 for n in nodes.values() if n.get("kind") in ("task", "history"))
    stats["history_edges"] = sum(1 for e in edges if e.get("relation") == "modified" and str(e.get("source", "")).startswith("task:"))
    graph["nodes"] = list(nodes.values())
    graph["edges"] = edges

    # Atomically save root and date-wise snapshots
    _dump_json(gdir / "graph.json", graph)
    cache["files"] = cached_files
    cache["history_cache"] = history_cache
    _dump_json(gdir / "cache.json", cache)

    date_dir = gdir / date_str
    date_dir.mkdir(parents=True, exist_ok=True)
    _dump_json(date_dir / "graph.json", graph)
    _dump_json(date_dir / "cache.json", cache)

    rep_file = date_dir / "GRAPH_REPORT.md"
    root_rep = gdir / "GRAPH_REPORT.md"
    if not rep_file.is_file() or not root_rep.is_file():
        rep_text = graph_report(graph)
        rep_file.write_text(rep_text, encoding="utf-8", newline="\n")
        root_rep.write_text(rep_text, encoding="utf-8", newline="\n")
    _auto_write_html_views(gdir, date_dir, graph)
    return graph


# -- watch + auto-refresh -----------------------------------------------------------------------
def graph_watch(ws: Workspace, interval: float = 2.0, debounce: float = 3.0, cycles: int | None = None,
                sleep=time.sleep, say=print) -> int:
    """Poll for source/doc changes; rebuild (incrementally) once edits settle. Returns the number of rebuilds."""
    def signature():
        index = CodeIndex(ws, max_files=None)
        files = index.files + index._list_files(None, exts=_DOC_EXTS)
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
            if mode != "auto" or len(CodeIndex(ws, max_files=None).files) > 1500:
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
        g = graph_build(ws, full=args.full, max_files=max(0, args.max_files), max_file_kb=max(0, args.max_file_kb),
                        progress=lambda msg: print(msg, file=sys.stderr))
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
    if args.action == "history":
        gdir = ws.dir / "graph"
        date_re = re.compile(r"^\d{4}-\d{2}-\d{2}$")
        date_dirs = [p for p in gdir.iterdir() if p.is_dir() and date_re.match(p.name)] if gdir.is_dir() else []
        if (gdir / "history").is_dir():
            date_dirs += [p for p in (gdir / "history").iterdir() if p.is_dir() and date_re.match(p.name)]
        date_dirs = sorted(set(date_dirs), key=lambda d: d.name)
        if not date_dirs:
            print("🕸️  No date-wise history folders yet.")
            return 0
        print("🕸️  [VERATUM GRAPH HISTORY] {} date(s):".format(len(date_dirs)))
        for d in date_dirs:
            task_files = [f for f in d.glob("*.json") if f.name not in ("graph.json", "cache.json")]
            print("   - {} ({} task/query record(s), snapshot: {})".format(
                d.name, len(task_files), "yes" if (d / "graph.json").is_file() else "no"))
        return 0
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
