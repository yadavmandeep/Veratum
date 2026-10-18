#!/usr/bin/env python3
"""
Veratum graph exports: self-contained HTML, SVG, Obsidian vault and Neo4j Cypher script. Stdlib only.
Loaded on demand by `graph export` (see veratum_graph.run_command).
"""
from __future__ import annotations

import json
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


_VIEW_PALETTE = ["#4f7cff", "#ff8a3d", "#2fbf9b", "#e5547c", "#9b6bff", "#e8b931", "#3bb5e8", "#8bc34a", "#c0794a", "#8794a8"]
_FILE_KINDS = ("file", "doc", "asset")


def _graph_file_view(graph: dict, max_nodes: int) -> tuple:
    """File-level map for the picture exports: one node per file/doc, one link per (file -> file) pair with the
    underlying symbol links (relation, confidence, file:line) kept as samples. Far easier to read than 1000+ symbols."""
    nodes = {n["id"]: n for n in graph["nodes"]}
    holders = {n["source_file"]: n for n in graph["nodes"] if n["kind"] in _FILE_KINDS}
    symbols: dict = {}
    for n in graph["nodes"]:
        if n["kind"] not in _FILE_KINDS and n["source_file"] in holders:
            symbols.setdefault(n["source_file"], []).append(n)
    pairs: dict = {}
    weight: dict = {}
    for e in graph["edges"]:
        if e["relation"] == "contains":
            continue
        a, b = nodes[e["source"]]["source_file"], nodes[e["target"]]["source_file"]
        if a == b or a not in holders or b not in holders:
            continue
        p = pairs.setdefault((a, b), {"n": 0, "cc": {}, "rc": {}, "x": []})
        p["n"] += 1
        p["cc"][e["confidence"]] = p["cc"].get(e["confidence"], 0) + 1
        p["rc"][e["relation"]] = p["rc"].get(e["relation"], 0) + 1
        if len(p["x"]) < 12:
            p["x"].append({"r": e["relation"], "q": e["confidence"], "a": _graph_label(nodes[e["source"]]["label"]),
                           "b": _graph_label(nodes[e["target"]]["label"]), "f": e["source_file"], "o": e["source_location"]})
        weight[a] = weight.get(a, 0) + 1
        weight[b] = weight.get(b, 0) + 1
    chosen = sorted(sorted(weight), key=lambda f: -weight[f])[:max_nodes]
    ordered = sorted(chosen)
    index = {f: i for i, f in enumerate(ordered)}
    files = []
    for f in ordered:
        h = holders[f]
        syms = sorted(symbols.get(f, []), key=lambda s: int(str(s["source_location"]).lstrip("L") or 0))
        files.append({"l": _graph_label(h["label"]), "p": f, "k": h["kind"], "c": h.get("community", -1),
                      "ns": len(syms), "d": weight.get(f, 0),
                      "sy": [[_graph_label(s["label"]), s["kind"], s["source_location"]] for s in syms[:80]]})
    links = []
    for (a, b), p in sorted(pairs.items()):
        if a in index and b in index:
            best = "EXTRACTED" if "EXTRACTED" in p["cc"] else ("INFERRED" if "INFERRED" in p["cc"] else "AMBIGUOUS")
            links.append({"s": index[a], "t": index[b], "n": p["n"], "q": best, "cc": p["cc"], "rc": p["rc"], "x": p["x"]})
    return files, links


def graph_export_svg(graph: dict, max_nodes: int = 300) -> str:
    """Static picture of the file-level map: community colours, one label per file, line width = number of links."""
    import html as _html
    import math
    files, links = _graph_file_view(graph, max_nodes)
    ids = list(range(len(files)))
    pos = _graph_layout(ids, [{"source": l["s"], "target": l["t"]} for l in links], width=1400.0, height=900.0)
    names = {c["id"]: c["name"] for c in graph.get("communities", [])}
    out = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1400 900" width="100%" font-family="system-ui,sans-serif" font-size="11">',
           '<rect width="1400" height="900" fill="#ffffff"/>']
    by_comm: dict = {}
    for i, f in enumerate(files):
        by_comm.setdefault(f["c"], []).append(i)
    for c, members in sorted(by_comm.items()):
        if len(members) < 2:
            continue
        cx = sum(pos[i][0] for i in members) / len(members)
        cy = sum(pos[i][1] for i in members) / len(members)
        rad = max(math.hypot(pos[i][0] - cx, pos[i][1] - cy) for i in members) + 34
        color = _VIEW_PALETTE[(c if c >= 0 else 0) % len(_VIEW_PALETTE)]
        out.append('<circle cx="{:.0f}" cy="{:.0f}" r="{:.0f}" fill="{}" fill-opacity="0.08" stroke="{}" stroke-opacity="0.3"/>'.format(cx, cy, rad, color, color))
        out.append('<text x="{:.0f}" y="{:.0f}" text-anchor="middle" font-weight="600" fill="{}" fill-opacity="0.85">{}</text>'.format(
            cx, cy - rad + 16, color, _html.escape(_graph_label(names.get(c, "community {}".format(c)))[:34])))
    for l in links:
        (x1, y1), (x2, y2) = pos[l["s"]], pos[l["t"]]
        dash = {"EXTRACTED": "", "INFERRED": ' stroke-dasharray="5 4"', "AMBIGUOUS": ' stroke-dasharray="1.5 3" stroke="#dc2626"'}[l["q"]]
        stroke = "" if l["q"] == "AMBIGUOUS" else ' stroke="#8a94a6"'
        out.append('<line x1="{:.0f}" y1="{:.0f}" x2="{:.0f}" y2="{:.0f}"{} stroke-opacity="0.55" stroke-width="{:.1f}"{}><title>{}</title></line>'.format(
            x1, y1, x2, y2, stroke, min(5.0, 1 + math.log2(l["n"] + 1) * 0.8), dash,
            _html.escape("{} -> {}: {} link(s) [{}]".format(files[l["s"]]["p"], files[l["t"]]["p"], l["n"], l["q"]))))
    for i, f in enumerate(files):
        x, y = pos[i]
        r = 7 + min(16, math.sqrt(f["ns"]) * 1.6)
        color = _VIEW_PALETTE[(f["c"] if f["c"] >= 0 else 0) % len(_VIEW_PALETTE)]
        out.append('<g><circle cx="{:.0f}" cy="{:.0f}" r="{:.1f}" fill="{}" stroke="#ffffff" stroke-width="2"/>'
                   '<text x="{:.0f}" y="{:.0f}" text-anchor="middle" fill="#1b1f24" paint-order="stroke" stroke="#ffffff" stroke-width="3">{}</text>'
                   '<title>{}</title></g>'.format(x, y, r, color, x, y + r + 12, _html.escape(f["l"]),
                                                    _html.escape("{} - {} symbol(s), {} link(s)".format(f["p"], f["ns"], f["d"]))))
    out.append("</svg>")
    return "\n".join(out)


_HTML_TEMPLATE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Veratum code map</title>
<style>
:root{--bg:#fbfbfd;--panel:#ffffff;--fg:#1b1f24;--mute:#6b7280;--line:#e3e6ec;--accent:#4f7cff;--chip:#eef1f6;--halo:#fbfbfd}
:root.dark{--bg:#0d1117;--panel:#141a22;--fg:#e8ebf0;--mute:#8b95a5;--line:#242c37;--accent:#7aa2ff;--chip:#1d2530;--halo:#0d1117}
@media (prefers-color-scheme:dark){:root:not(.light){--bg:#0d1117;--panel:#141a22;--fg:#e8ebf0;--mute:#8b95a5;--line:#242c37;--accent:#7aa2ff;--chip:#1d2530;--halo:#0d1117}}
*{box-sizing:border-box}
body{margin:0;height:100vh;display:grid;grid-template-rows:auto 1fr;background:var(--bg);color:var(--fg);font:13px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif}
header{display:flex;flex-wrap:wrap;gap:8px;align-items:center;padding:9px 14px;border-bottom:1px solid var(--line);background:var(--panel)}
header h1{font-size:15px;margin:0 10px 0 0;font-weight:650}
header .stat{color:var(--mute);margin-right:auto}
input[type=search]{padding:7px 11px;width:280px;border:1px solid var(--line);border-radius:8px;background:var(--bg);color:var(--fg)}
input[type=search]:focus{outline:2px solid var(--accent);outline-offset:-1px}
button{padding:6px 11px;border:1px solid var(--line);border-radius:8px;background:var(--panel);color:var(--fg);cursor:pointer}
button:hover{border-color:var(--accent);color:var(--accent)}
main{display:grid;grid-template-columns:230px 1fr 330px;min-height:0}
aside{overflow:auto;padding:12px 14px;background:var(--panel)}
aside.left{border-right:1px solid var(--line)}aside.right{border-left:1px solid var(--line)}
aside h2{font-size:11px;text-transform:uppercase;letter-spacing:.07em;color:var(--mute);margin:16px 0 6px;font-weight:600}
aside h2:first-child{margin-top:0}
label.opt{display:flex;gap:7px;align-items:center;padding:2px 0;cursor:pointer}
.sw{width:12px;height:12px;border-radius:50%;display:inline-block;flex:none}
.comm{display:flex;gap:7px;align-items:center;padding:4px 6px;border-radius:6px;cursor:pointer}
.comm:hover{background:var(--chip)}.comm.off{opacity:.4}.comm.off span:nth-child(2){text-decoration:line-through}
.comm .n{color:var(--mute);margin-left:auto}
#stage{position:relative;min-width:0;min-height:0;background:radial-gradient(circle at 50% 40%,var(--panel),var(--bg))}
canvas{position:absolute;inset:0;display:block;cursor:grab}canvas.drag{cursor:grabbing}
#tip{position:absolute;pointer-events:none;background:var(--panel);border:1px solid var(--line);box-shadow:0 4px 14px #0002;padding:5px 9px;border-radius:8px;display:none;max-width:380px;z-index:2}
.badge{display:inline-block;padding:0 7px;border-radius:10px;font-size:11px;background:var(--chip)}
.badge.EXTRACTED{background:#16a34a22;color:#16a34a}.badge.INFERRED{background:#d9770622;color:#d97706}.badge.AMBIGUOUS{background:#dc262622;color:#dc2626}
.conn{padding:6px 0;border-bottom:1px solid var(--line)}
.conn .top{cursor:pointer}.conn .top:hover strong{color:var(--accent)}
.conn .more{margin-top:4px;padding-left:8px;border-left:2px solid var(--line);color:var(--mute);font-size:12px}
.sym{display:flex;gap:8px;padding:1px 0;font-size:12px}.sym .k{color:var(--mute);width:58px;flex:none}.sym .ln{margin-left:auto;color:var(--mute)}
.mute{color:var(--mute)}code{font:12px ui-monospace,Consolas,monospace;word-break:break-all}
h3{margin:0 0 2px;font-size:15px}
#help{color:var(--mute);font-size:12px;margin-top:14px}
@media(max-width:900px){main{grid-template-columns:1fr}aside{display:none}}
</style></head><body>
<header>
  <h1>Veratum code map</h1><span class="stat" id="stat"></span>
  <input id="q" type="search" placeholder="Search a file or function  ( / )" autocomplete="off">
  <button id="fit">Fit</button><button id="pause">Pause</button><button id="reset">Reset</button><button id="theme">Theme</button>
</header>
<main>
  <aside class="left">
    <h2>View</h2>
    <label class="opt"><input type="checkbox" id="bub" checked><span>Group by community</span></label>
    <label class="opt"><input type="checkbox" id="lab" checked><span>Always show file names</span></label>
    <h2>Link confidence</h2><div id="conf"></div>
    <h2>Link type</h2><div id="rel"></div>
    <h2>File type</h2><div id="kind"></div>
    <h2>Communities (click to hide)</h2><div id="comm"></div>
    <p id="help">Each dot is a file; its size is how many functions and classes it holds. A line means one file uses another (thicker = more links). Drag a dot to move it, drag the background to pan, scroll to zoom, click a file for details. Solid line = written in the code (EXTRACTED), dashed = matched by name (INFERRED), red dotted = AMBIGUOUS.</p>
  </aside>
  <div id="stage"><canvas id="cv"></canvas><div id="tip"></div></div>
  <aside class="right"><div id="detail"></div></aside>
</main>
<script id="data" type="application/json">__DATA__</script>
<script>
(function(){
"use strict";
var D=JSON.parse(document.getElementById("data").textContent);
var N=D.nodes,L=D.links,P=D.palette,CM={};
D.communities.forEach(function(c){CM[c.id]=c});
function $(id){return document.getElementById(id)}
var cv=$("cv"),ctx=cv.getContext("2d"),tip=$("tip");
var W=1,H=1,dpr=window.devicePixelRatio||1,z=1,tx=0,ty=0;
function colorOf(c){return P[(c<0?0:c)%P.length]}
function rgba(hex,a){var v=parseInt(hex.slice(1),16);return "rgba("+(v>>16&255)+","+(v>>8&255)+","+(v&255)+","+a+")"}
function el(tag,text,cls){var e=document.createElement(tag);if(text!=null)e.textContent=text;if(cls)e.className=cls;return e}
function css(name){return getComputedStyle(document.documentElement).getPropertyValue(name).trim()}
for(var i=0;i<N.length;i++){var n=N[i],a=i*2.399963,r0=30*Math.sqrt(i+1);n.i=i;n.x=Math.cos(a)*r0;n.y=Math.sin(a)*r0;n.vx=0;n.vy=0;n.out=[];n.inn=[];n.show=true;n.hit=true;n.r=8+Math.min(17,Math.sqrt(n.ns)*1.6);n.sl=(n.l+" "+n.p+" "+n.sy.map(function(s){return s[0]}).join(" ")).toLowerCase()}
for(var j=0;j<L.length;j++){var e=L[j];e.a=N[e.s];e.b=N[e.t];e.a.out.push(e);e.b.inn.push(e);e.show=true}
var kinds={},rels={},confs={EXTRACTED:1,INFERRED:1,AMBIGUOUS:1};
N.forEach(function(n){kinds[n.k]=1});L.forEach(function(e){Object.keys(e.rc).forEach(function(r){rels[r]=1})});
var onK={},onR={},onQ={},offC={},bubbles=true,labels=true;
Object.keys(kinds).forEach(function(k){onK[k]=true});Object.keys(rels).forEach(function(k){onR[k]=true});Object.keys(confs).forEach(function(k){onQ[k]=true});
var query="",sel=null,hover=null,drag=null,panning=false,running=true,alpha=1,last={x:0,y:0};

function checks(box,keys,state,badge){
  var host=$(box);host.textContent="";
  keys.forEach(function(k){
    var l=el("label",null,"opt"),c=document.createElement("input");c.type="checkbox";c.checked=!!state[k];
    c.onchange=function(){state[k]=c.checked;refilter()};
    l.appendChild(c);if(badge){l.appendChild(el("span",k,"badge "+k))}else l.appendChild(el("span",k));
    host.appendChild(l)});
}
function comms(){
  var host=$("comm");host.textContent="";
  D.communities.forEach(function(c){
    var row=el("div",null,"comm"+(offC[c.id]?" off":"")),sw=el("span",null,"sw");sw.style.background=colorOf(c.id);
    row.appendChild(sw);row.appendChild(el("span",c.name));row.appendChild(el("span",String(c.size),"n"));
    row.onclick=function(){offC[c.id]=!offC[c.id];comms();refilter()};host.appendChild(row)});
}
function any(counts,on){for(var k in counts){if(on[k]&&counts[k])return true}return false}
function refilter(){
  N.forEach(function(n){n.show=!!onK[n.k]&&!offC[n.c]});
  L.forEach(function(e){e.show=e.a.show&&e.b.show&&any(e.cc,onQ)&&any(e.rc,onR)});
  countVisible();alpha=Math.max(alpha,.5);search(query);
}
function countVisible(){N.forEach(function(n){n.vd=0});L.forEach(function(e){if(e.show){e.a.vd++;e.b.vd++}})}
function search(q){
  query=q.trim().toLowerCase();
  N.forEach(function(n){n.hit=!query||n.sl.indexOf(query)>=0});
}
function w2s(x,y){return [x*z+tx,y*z+ty]}
function s2w(x,y){return [(x-tx)/z,(y-ty)/z]}
function fit(){
  var xs=[],ys=[];N.forEach(function(n){if(n.show){xs.push(n.x-n.r);xs.push(n.x+n.r);ys.push(n.y-n.r-14);ys.push(n.y+n.r+14)}});
  if(!xs.length)return;
  xs.sort(function(a,b){return a-b});ys.sort(function(a,b){return a-b});
  var lo=Math.floor(xs.length*.02),hi=Math.max(lo,Math.ceil(xs.length*.98)-1);
  var x0=xs[lo],x1=xs[hi],y0=ys[lo],y1=ys[hi],pad=50;
  z=Math.max(.05,Math.min(2.2,Math.min((W-pad*2)/Math.max(1,x1-x0),(H-pad*2)/Math.max(1,y1-y0))));
  tx=W/2-((x0+x1)/2)*z;ty=H/2-((y0+y1)/2)*z;
}
function tick(){
  var cell=170,grid={},vis=[],cen={};
  N.forEach(function(n){if(!n.show)return;vis.push(n);var k=Math.floor(n.x/cell)+","+Math.floor(n.y/cell);(grid[k]||(grid[k]=[])).push(n);
    var c=cen[n.c]||(cen[n.c]={x:0,y:0,k:0});c.x+=n.x;c.y+=n.y;c.k++});
  vis.forEach(function(n){
    var cx=Math.floor(n.x/cell),cy=Math.floor(n.y/cell);
    for(var gx=cx-1;gx<=cx+1;gx++)for(var gy=cy-1;gy<=cy+1;gy++){
      var b=grid[gx+","+gy];if(!b)continue;
      for(var k=0;k<b.length;k++){var m=b[k];if(m===n)continue;var dx=n.x-m.x,dy=n.y-m.y,d2=dx*dx+dy*dy||.01,d=Math.sqrt(d2),other=n.c!==m.c,min=n.r+m.r+(other?60:34);
        var f=(other?4200:2600)/d2;if(d<min)f+=(min-d)*.06;n.vx+=dx*f;n.vy+=dy*f}}});  /* different communities push each other further apart */
  L.forEach(function(e){if(!e.show)return;var a=e.a,b=e.b,dx=b.x-a.x,dy=b.y-a.y,d=Math.sqrt(dx*dx+dy*dy)||.01,f=(d-(130+a.r+b.r))*.006*(1+Math.log(e.n+1)*.25);a.vx+=dx/d*f;a.vy+=dy/d*f;b.vx-=dx/d*f;b.vy-=dy/d*f});
  vis.forEach(function(n){
    var c=cen[n.c];if(c&&c.k>1){n.vx+=(c.x/c.k-n.x)*.012;n.vy+=(c.y/c.k-n.y)*.012}   /* members of a community drift together */
    var g=n.vd?.0009:.012;n.vx-=n.x*g;n.vy-=n.y*g;
    if(n===drag){n.vx=0;n.vy=0;return}
    n.vx*=.8;n.vy*=.8;n.x+=n.vx*alpha*2.4;n.y+=n.vy*alpha*2.4});
  alpha=Math.max(.015,alpha*.988);
}
function neighbours(n){var s={};n.out.forEach(function(e){if(e.show)s[e.b.i]=1});n.inn.forEach(function(e){if(e.show)s[e.a.i]=1});return s}
function draw(){
  ctx.setTransform(dpr,0,0,dpr,0,0);ctx.clearRect(0,0,W,H);
  var fg=css("--fg")||"#222",mute=css("--mute")||"#888",halo=css("--halo")||"#fff";
  var focus=sel||hover,nb=focus?neighbours(focus):null,filtering=!!query;
  if(bubbles){
    var cen={};N.forEach(function(n){if(n.show&&!offC[n.c]){var c=cen[n.c]||(cen[n.c]=[]);c.push(n)}});
    Object.keys(cen).forEach(function(id){
      var m=cen[id];if(m.length<2)return;var cx=0,cy=0;m.forEach(function(n){cx+=n.x;cy+=n.y});cx/=m.length;cy/=m.length;
      var R=0;m.forEach(function(n){R=Math.max(R,Math.hypot(n.x-cx,n.y-cy)+n.r)});R+=40;
      var s=w2s(cx,cy),col=colorOf(+id);
      ctx.globalAlpha=1;ctx.fillStyle=rgba(col,.07);ctx.strokeStyle=rgba(col,.28);ctx.lineWidth=1.2;
      ctx.beginPath();ctx.arc(s[0],s[1],R*z,0,6.2832);ctx.fill();ctx.stroke();
      var nm=(CM[id]?CM[id].name:"community "+id);if(nm.length>30)nm=nm.slice(0,29)+"…";
      ctx.fillStyle=rgba(col,.95);ctx.font="600 "+Math.max(10,Math.min(15,12*z))+"px system-ui,sans-serif";ctx.textAlign="center";ctx.fillText(nm,s[0],s[1]-R*z+16*Math.min(1.2,z+.3));
    });
  }
  L.forEach(function(e){
    if(!e.show)return;var p=w2s(e.a.x,e.a.y),q=w2s(e.b.x,e.b.y);
    var on=focus&&(e.a===focus||e.b===focus),dim=(focus&&!on)||(filtering&&!(e.a.hit||e.b.hit));
    ctx.globalAlpha=dim?.05:(on?.95:.4);
    var col=e.q==="AMBIGUOUS"?"#dc2626":(on?fg:mute);
    ctx.strokeStyle=col;ctx.lineWidth=Math.min(5,1+Math.log(e.n+1)*.75)*(on?1.3:1);
    ctx.setLineDash(e.q==="EXTRACTED"?[]:(e.q==="INFERRED"?[6,5]:[2,4]));
    ctx.beginPath();ctx.moveTo(p[0],p[1]);ctx.lineTo(q[0],q[1]);ctx.stroke();ctx.setLineDash([]);
    var ang=Math.atan2(q[1]-p[1],q[0]-p[0]),rr=(e.b.r+2)*z,ax=q[0]-Math.cos(ang)*rr,ay=q[1]-Math.sin(ang)*rr,s=Math.max(5,Math.min(9,7*z));
    ctx.fillStyle=col;ctx.beginPath();ctx.moveTo(ax,ay);ctx.lineTo(ax-Math.cos(ang-.45)*s,ay-Math.sin(ang-.45)*s);ctx.lineTo(ax-Math.cos(ang+.45)*s,ay-Math.sin(ang+.45)*s);ctx.closePath();ctx.fill();
  });
  ctx.globalAlpha=1;ctx.textAlign="center";
  N.forEach(function(n){
    if(!n.show)return;var p=w2s(n.x,n.y),r=n.r*z,rr=Math.max(4,r);
    var dim=(focus&&n!==focus&&!(nb&&nb[n.i]))||(filtering&&!n.hit);
    ctx.globalAlpha=dim?.15:1;ctx.fillStyle=colorOf(n.c);ctx.strokeStyle=halo;ctx.lineWidth=2.5;
    ctx.beginPath();
    if(n.k==="file"){ctx.arc(p[0],p[1],rr,0,6.2832)}else{var q=rr*.9;ctx.rect(p[0]-q,p[1]-q,q*2,q*2)}
    ctx.fill();ctx.stroke();
    if(n===sel||n===hover||(filtering&&n.hit)){ctx.lineWidth=2.4;ctx.strokeStyle=fg;ctx.stroke()}
    var showLabel=n===sel||n===hover||(nb&&nb[n.i])||(filtering&&n.hit)||(labels&&(z>=.5||n.top));
    if(showLabel&&!dim){
      ctx.globalAlpha=1;ctx.font=(n===sel||n===hover?"600 ":"")+Math.max(10,Math.min(13,11.5*z))+"px system-ui,sans-serif";
      ctx.lineWidth=3.5;ctx.strokeStyle=halo;ctx.strokeText(n.l,p[0],p[1]+rr+13);ctx.fillStyle=fg;ctx.fillText(n.l,p[0],p[1]+rr+13)}
  });
  ctx.globalAlpha=1;
}
function frame(){if(running&&alpha>.016)tick();draw();requestAnimationFrame(frame)}
function resize(){
  var r=cv.parentElement.getBoundingClientRect();W=Math.max(100,r.width);H=Math.max(100,r.height);
  cv.width=Math.round(W*dpr);cv.height=Math.round(H*dpr);cv.style.width=W+"px";cv.style.height=H+"px";
}
function pick(sx,sy){
  var w=s2w(sx,sy),best=null,bd=1e9;
  N.forEach(function(n){if(!n.show)return;var dx=n.x-w[0],dy=n.y-w[1],d=Math.sqrt(dx*dx+dy*dy),rr=n.r+5/z;if(d<rr&&d<bd){bd=d;best=n}});
  return best;
}
function plural(c){return Object.keys(c).map(function(k){return k+" ×"+c[k]}).join(" · ")}
function detail(n){
  var box=$("detail");box.textContent="";
  if(!n){box.appendChild(el("h3","Pick a file"));box.appendChild(el("p","Click a dot to see what it contains, which files it uses and which files use it. Every line is backed by a file and line number.","mute"));return}
  box.appendChild(el("h3",n.l));
  box.appendChild(el("p",(n.k==="file"?"code file":n.k)+" · "+(CM[n.c]?CM[n.c].name:"community "+n.c)+" · "+n.ns+" symbols · "+n.d+" links","mute"));
  var path=el("p");path.appendChild(el("code",n.p));box.appendChild(path);
  var cp=el("button","Copy path");cp.onclick=function(){if(navigator.clipboard)navigator.clipboard.writeText(n.p)};box.appendChild(cp);
  if(n.sy.length){
    box.appendChild(el("h2","Inside this file ("+n.ns+")"));
    n.sy.slice(0,50).forEach(function(s){var row=el("div",null,"sym");row.appendChild(el("span",s[1],"k"));row.appendChild(el("span",s[0]));row.appendChild(el("span",s[2].replace(/^L/,":"),"ln"));box.appendChild(row)});
    if(n.ns>50)box.appendChild(el("p","… "+(n.ns-50)+" more","mute"));
  }
  function list(title,arr,other){
    var vis=arr.filter(function(e){return e.show});if(!vis.length)return;
    box.appendChild(el("h2",title+" ("+vis.length+")"));
    vis.sort(function(a,b){return b.n-a.n}).slice(0,60).forEach(function(e){
      var o=other(e),row=el("div",null,"conn"),top=el("div",null,"top");
      top.appendChild(el("span",e.q,"badge "+e.q));top.appendChild(document.createTextNode(" "));top.appendChild(el("strong",o.l));
      top.appendChild(el("span","  "+plural(e.rc),"mute"));row.appendChild(top);
      var more=el("div",null,"more");more.style.display="none";
      e.x.forEach(function(x){more.appendChild(el("div",x.a+" → "+x.b+"  ["+x.q+"]  "+x.f+x.o.replace(/^L/,":")))});
      if(e.n>e.x.length)more.appendChild(el("div","… "+(e.n-e.x.length)+" more"));
      row.appendChild(more);
      top.onclick=function(ev){if(ev.detail>1){select(o,true)}else{more.style.display=more.style.display==="none"?"block":"none"}};
      top.title="click: show the exact lines · double-click: go to this file";
      box.appendChild(row)});
  }
  list("Uses",n.out,function(e){return e.b});list("Used by",n.inn,function(e){return e.a});
}
function select(n,center){sel=n;detail(n);if(n&&center){var w=w2s(n.x,n.y);tx+=W/2-w[0];ty+=H/2-w[1]}}
cv.addEventListener("mousedown",function(ev){
  var r=cv.getBoundingClientRect(),n=pick(ev.clientX-r.left,ev.clientY-r.top);
  last={x:ev.clientX,y:ev.clientY};
  if(n){drag=n;alpha=Math.max(alpha,.35)}else{panning=true;cv.classList.add("drag")}
});
window.addEventListener("mousemove",function(ev){
  var r=cv.getBoundingClientRect(),sx=ev.clientX-r.left,sy=ev.clientY-r.top;
  if(drag){var w=s2w(sx,sy);drag.x=w[0];drag.y=w[1];return}
  if(panning){tx+=ev.clientX-last.x;ty+=ev.clientY-last.y;last={x:ev.clientX,y:ev.clientY};return}
  var n=(sx>=0&&sy>=0&&sx<=W&&sy<=H)?pick(sx,sy):null;hover=n;
  if(n){tip.style.display="block";tip.style.left=Math.min(W-220,sx+14)+"px";tip.style.top=(sy+14)+"px";tip.textContent=n.p+"  ·  "+n.ns+" symbols"}else tip.style.display="none";
});
window.addEventListener("mouseup",function(ev){
  var moved=Math.abs(ev.clientX-last.x)+Math.abs(ev.clientY-last.y);
  if(drag){if(moved<4)select(drag===sel?null:drag);drag=null}
  else if(panning){panning=false;cv.classList.remove("drag");if(moved<4)select(null)}
});
cv.addEventListener("wheel",function(ev){
  ev.preventDefault();var r=cv.getBoundingClientRect(),sx=ev.clientX-r.left,sy=ev.clientY-r.top,k=Math.exp(-ev.deltaY*.0015),nz=Math.max(.05,Math.min(6,z*k));
  tx=sx-(sx-tx)*(nz/z);ty=sy-(sy-ty)*(nz/z);z=nz;
},{passive:false});
$("q").addEventListener("input",function(e){search(e.target.value)});
$("q").addEventListener("keydown",function(e){if(e.key==="Enter"&&query){var m=N.filter(function(n){return n.show&&n.hit});if(m.length)select(m[0],true)}});
window.addEventListener("keydown",function(e){
  if(e.key==="/"&&document.activeElement!==$("q")){e.preventDefault();$("q").focus()}
  if(e.key==="Escape"){$("q").value="";search("");select(null)}
});
$("bub").onchange=function(){bubbles=$("bub").checked};$("lab").onchange=function(){labels=$("lab").checked};
$("fit").onclick=fit;
$("pause").onclick=function(){running=!running;if(running)alpha=Math.max(alpha,.3);$("pause").textContent=running?"Pause":"Resume"};
function resetAll(){Object.keys(onK).forEach(function(k){onK[k]=true});Object.keys(onR).forEach(function(k){onR[k]=true});Object.keys(onQ).forEach(function(k){onQ[k]=true});offC={};
  checks("conf",Object.keys(confs),onQ,true);checks("rel",Object.keys(rels).sort(),onR);checks("kind",Object.keys(kinds).sort(),onK);comms();$("q").value="";refilter();fit()}
$("reset").onclick=resetAll;
$("theme").onclick=function(){var r=document.documentElement,dark=r.classList.contains("dark")||(!r.classList.contains("light")&&matchMedia("(prefers-color-scheme: dark)").matches);r.classList.toggle("dark",!dark);r.classList.toggle("light",dark)};
window.addEventListener("resize",function(){resize()});
$("stat").textContent=D.meta.shown+" of "+D.meta.total_files+" files shown (most connected first) · "+L.length+" file-to-file links · "+D.meta.nodes+" symbols & files analysed";
checks("conf",Object.keys(confs),onQ,true);checks("rel",Object.keys(rels).sort(),onR);checks("kind",Object.keys(kinds).sort(),onK);comms();
N.slice().sort(function(a,b){return b.d-a.d}).slice(0,40).forEach(function(n){n.top=true});
countVisible();detail(null);resize();for(var s=0;s<420;s++)tick();fit();requestAnimationFrame(frame);
})();
</script></body></html>
"""


def graph_export_html(graph: dict, max_nodes: int = 300, snapshots: dict | None = None) -> str:
    """Self-contained interactive map (canvas + vanilla JS, no CDN, no network). One dot per file, links aggregated per file
    pair with their exact symbol lines one click away, community bubbles, search, filters and a details panel. Data is embedded
    as escaped JSON and rendered with textContent only, so hostile names cannot inject markup."""
    if not graph or not graph.get("nodes"):
        return _HTML_TEMPLATE.replace("__DATA__", "{}")
    files, links = _graph_file_view(graph, max_nodes)
    present = {f["c"] for f in files}
    counts: dict = {}
    for f in files:
        counts[f["c"]] = counts.get(f["c"], 0) + 1
    names = {c["id"]: c["name"] for c in graph.get("communities", [])}
    data = {
        "meta": {"shown": len(files), "nodes": graph["stats"]["nodes"],
                 "total_files": len({n["source_file"] for n in graph["nodes"] if n["kind"] in _FILE_KINDS})},
        "palette": _VIEW_PALETTE,
        "nodes": files,
        "links": links,
        "communities": [{"id": c, "name": _graph_label(names.get(c, "community {}".format(c))), "size": counts[c]}
                        for c in sorted(present, key=lambda c: (-counts[c], c))[:60]],
    }
    payload = (json.dumps(data, ensure_ascii=False, separators=(",", ":"))
               .replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
               .replace("\u2028", "\\u2028").replace("\u2029", "\\u2029"))
    return _HTML_TEMPLATE.replace("__DATA__", payload)


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


def graph_export(ws, graph: dict, fmt: str, out: str | None, max_nodes: int = 400) -> list:
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
