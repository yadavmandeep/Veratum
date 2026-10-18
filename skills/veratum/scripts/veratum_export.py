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
<title>Codebase Knowledge Graph</title>
<style>
:root{
  --bg:#0b0d14;--sidebar:#10131d;--border:#1b2030;
  --fg:#e2e8f0;--mute:#717d96;--accent:#3b82f6;
  --panel:#131722;--chk-bg:#2b3b55;--chk-border:#3b82f6;
}
*{box-sizing:border-box;margin:0;padding:0}
body{
  margin:0;height:100vh;width:100vw;overflow:hidden;
  display:flex;background:var(--bg);color:var(--fg);
  font:13px/1.4 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
}
#stage{
  flex:1;position:relative;height:100%;min-width:0;
  background:radial-gradient(circle at 45% 50%,#111524 0%,#08090f 100%);
}
canvas{position:absolute;inset:0;width:100%;height:100%;cursor:grab;display:block}
canvas.drag{cursor:grabbing}

/* Controls bar overlay */
#controls{
  position:absolute;top:16px;left:18px;display:flex;gap:8px;align-items:center;z-index:10;
}
.search-box{
  background:rgba(19,23,34,0.85);backdrop-filter:blur(8px);
  border:1px solid var(--border);border-radius:6px;
  padding:6px 12px;color:var(--fg);font-size:12px;width:240px;outline:none;
}
.search-box:focus{border-color:var(--accent)}
.btn{
  background:rgba(19,23,34,0.85);backdrop-filter:blur(8px);
  border:1px solid var(--border);border-radius:6px;padding:6px 10px;
  color:var(--mute);font-size:12px;cursor:pointer;transition:all .15s;
}
.btn:hover{color:var(--fg);border-color:var(--accent)}

/* Tooltip */
#tip{
  position:absolute;pointer-events:none;background:rgba(16,19,29,0.92);
  backdrop-filter:blur(10px);border:1px solid var(--border);
  box-shadow:0 8px 24px rgba(0,0,0,0.5);padding:6px 10px;border-radius:6px;
  display:none;max-width:360px;z-index:20;font-size:12px;color:var(--fg);
}

/* Right-hand sidebar matching screenshot */
#sidebar{
  width:290px;height:100%;background:var(--sidebar);
  border-left:1px solid var(--border);display:flex;flex-direction:column;
  flex-shrink:0;z-index:10;
}
.sidebar-header{
  padding:20px 20px 14px;
}
.sidebar-header h2{
  font-size:13px;letter-spacing:0.08em;font-weight:700;
  color:#94a3b8;text-transform:uppercase;margin-bottom:14px;
}
.select-all-row{
  display:flex;align-items:center;gap:10px;cursor:pointer;
  font-size:13px;font-weight:500;color:#cbd5e1;user-select:none;
}
.communities-list{
  flex:1;overflow-y:auto;padding:0 14px 20px 20px;display:flex;flex-direction:column;gap:5px;
}
.communities-list::-webkit-scrollbar{width:5px}
.communities-list::-webkit-scrollbar-thumb{background:#1f2638;border-radius:3px}

.comm-item{
  display:flex;align-items:center;gap:10px;padding:5px 6px;
  border-radius:5px;cursor:pointer;user-select:none;transition:background .1s;
}
.comm-item:hover{background:rgba(255,255,255,0.03)}
.comm-item.off{opacity:0.35}

/* Checkboxes styled like screenshot */
.chk{
  width:16px;height:16px;border-radius:3px;
  background:#1a2335;border:1px solid #3b82f6;
  display:flex;align-items:center;justify-content:center;
  flex-shrink:0;transition:all .15s;
}
.chk.checked{background:#3b82f6}
.chk svg{width:11px;height:11px;stroke:#fff;stroke-width:2.5;fill:none}
.chk:not(.checked) svg{display:none}

.swatch{
  width:12px;height:12px;border-radius:50%;flex-shrink:0;
}
.comm-label{
  flex:1;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;
  font-size:13px;color:#e2e8f0;
}
.comm-count{
  font-size:12px;color:#64748b;font-variant-numeric:tabular-nums;
  margin-left:auto;padding-left:8px;
}

/* Detail modal overlay */
#detail{
  display:none;position:absolute;bottom:20px;left:20px;max-width:420px;
  max-height:45vh;overflow-y:auto;background:rgba(16,19,29,0.95);
  backdrop-filter:blur(12px);border:1px solid var(--border);
  border-radius:8px;padding:14px;box-shadow:0 12px 32px rgba(0,0,0,0.6);z-index:15;
}
#detail h3{font-size:14px;margin-bottom:4px;color:#fff}
#detail p{color:var(--mute);font-size:12px;margin-bottom:8px}
#detail .close-btn{float:right;cursor:pointer;color:var(--mute);font-size:16px;line-height:1}
#detail .close-btn:hover{color:#fff}
</style></head><body>
<div id="stage">
  <div id="controls">
    <input id="q" class="search-box" type="search" placeholder="Search files or symbols..." autocomplete="off">
    <button id="fit" class="btn">Fit</button>
    <button id="pause" class="btn">Pause</button>
  </div>
  <canvas id="cv"></canvas>
  <div id="tip"></div>
  <div id="detail"><span class="close-btn" onclick="select(null)">&times;</span><div id="detail-body"></div></div>
</div>
<div id="sidebar">
  <div class="sidebar-header">
    <h2>COMMUNITIES</h2>
    <div class="select-all-row" id="select-all">
      <div class="chk checked" id="chk-all"><svg viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"></polyline></svg></div>
      <span>Select All</span>
    </div>
  </div>
  <div class="communities-list" id="comm-list"></div>
</div>
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
for(var i=0;i<N.length;i++){var n=N[i],a=i*2.399963,r0=30*Math.sqrt(i+1);n.i=i;n.x=Math.cos(a)*r0;n.y=Math.sin(a)*r0;n.vx=0;n.vy=0;n.out=[];n.inn=[];n.show=true;n.hit=true;n.r=4.5+Math.min(9,Math.sqrt(n.ns)*0.8);n.sl=(n.l+" "+n.p+" "+n.sy.map(function(s){return s[0]}).join(" ")).toLowerCase()}
for(var j=0;j<L.length;j++){var e=L[j];e.a=N[e.s];e.b=N[e.t];e.a.out.push(e);e.b.inn.push(e);e.show=true}
var offC={};
var query="",sel=null,hover=null,drag=null,panning=false,running=true,alpha=1,last={x:0,y:0};

function renderCommunities(){
  var list=$("comm-list");list.textContent="";
  var allChecked=true;
  D.communities.forEach(function(c){
    var checked=!offC[c.id];if(!checked)allChecked=false;
    var row=el("div",null,"comm-item"+(checked?"":" off"));
    var chk=el("div",null,"chk"+(checked?" checked":""));
    chk.innerHTML='<svg viewBox="0 0 24 24"><polyline points="20 6 9 17 4 12"></polyline></svg>';
    var sw=el("span",null,"swatch");sw.style.background=colorOf(c.id);
    var label=el("span",c.name,"comm-label");label.title=c.name;
    var count=el("span",String(c.size),"comm-count");
    row.appendChild(chk);row.appendChild(sw);row.appendChild(label);row.appendChild(count);
    row.onclick=function(){
      offC[c.id]=!offC[c.id];
      renderCommunities();refilter();
    };
    list.appendChild(row);
  });
  var chkAll=$("chk-all");
  if(allChecked){chkAll.classList.add("checked")}else{chkAll.classList.remove("checked")}
}

$("select-all").onclick=function(){
  var chkAll=$("chk-all");
  var currentlyChecked=chkAll.classList.contains("checked");
  if(currentlyChecked){
    D.communities.forEach(function(c){offC[c.id]=true});
  } else {
    offC={};
  }
  renderCommunities();refilter();
};

function refilter(){
  N.forEach(function(n){n.show=!offC[n.c]});
  L.forEach(function(e){e.show=e.a.show&&e.b.show});
  alpha=Math.max(alpha,.5);search(query);
}
function search(q){
  query=q.trim().toLowerCase();
  N.forEach(function(n){n.hit=!query||n.sl.indexOf(query)>=0});
}
function w2s(x,y){return [x*z+tx,y*z+ty]}
function s2w(x,y){return [(x-tx)/z,(y-ty)/z]}
function fit(){
  var xs=[],ys=[];N.forEach(function(n){if(n.show){xs.push(n.x-n.r);xs.push(n.x+n.r);ys.push(n.y-n.r);ys.push(n.y+n.r)}});
  if(!xs.length)return;
  xs.sort(function(a,b){return a-b});ys.sort(function(a,b){return a-b});
  var lo=Math.floor(xs.length*.02),hi=Math.max(lo,Math.ceil(xs.length*.98)-1);
  var x0=xs[lo],x1=xs[hi],y0=ys[lo],y1=ys[hi],pad=40;
  z=Math.max(.05,Math.min(2.5,Math.min((W-pad*2)/Math.max(1,x1-x0),(H-pad*2)/Math.max(1,y1-y0))));
  tx=W/2-((x0+x1)/2)*z;ty=H/2-((y0+y1)/2)*z;
}
function tick(){
  var cell=160,grid={},vis=[],cen={};
  N.forEach(function(n){if(!n.show)return;vis.push(n);var k=Math.floor(n.x/cell)+","+Math.floor(n.y/cell);(grid[k]||(grid[k]=[])).push(n);
    var c=cen[n.c]||(cen[n.c]={x:0,y:0,k:0});c.x+=n.x;c.y+=n.y;c.k++});
  vis.forEach(function(n){
    var cx=Math.floor(n.x/cell),cy=Math.floor(n.y/cell);
    for(var gx=cx-1;gx<=cx+1;gx++)for(var gy=cy-1;gy<=cy+1;gy++){
      var b=grid[gx+","+gy];if(!b)continue;
      for(var k=0;k<b.length;k++){var m=b[k];if(m===n)continue;var dx=n.x-m.x,dy=n.y-m.y,d2=dx*dx+dy*dy||.01,d=Math.sqrt(d2),other=n.c!==m.c,min=n.r+m.r+(other?45:22);
        var f=(other?3200:1800)/d2;if(d<min)f+=(min-d)*.07;n.vx+=dx*f;n.vy+=dy*f}}});
  L.forEach(function(e){if(!e.show)return;var a=e.a,b=e.b,dx=b.x-a.x,dy=b.y-a.y,d=Math.sqrt(dx*dx+dy*dy)||.01,f=(d-(80+a.r+b.r))*.008*(1+Math.log(e.n+1)*.25);a.vx+=dx/d*f;a.vy+=dy/d*f;b.vx-=dx/d*f;b.vy-=dy/d*f});
  vis.forEach(function(n){
    var c=cen[n.c];if(c&&c.k>1){n.vx+=(c.x/c.k-n.x)*.014;n.vy+=(c.y/c.k-n.y)*.014}
    var g=.006;n.vx-=n.x*g;n.vy-=n.y*g;
    if(n===drag){n.vx=0;n.vy=0;return}
    n.vx*=.75;n.vy*=.75;n.x+=n.vx*alpha*2.2;n.y+=n.vy*alpha*2.2});
  alpha=Math.max(.015,alpha*.985);
}
function neighbours(n){var s={};n.out.forEach(function(e){if(e.show)s[e.b.i]=1});n.inn.forEach(function(e){if(e.show)s[e.a.i]=1});return s}
function draw(){
  ctx.setTransform(dpr,0,0,dpr,0,0);ctx.clearRect(0,0,W,H);
  var focus=sel||hover,nb=focus?neighbours(focus):null,filtering=!!query;
  L.forEach(function(e){
    if(!e.show)return;var p=w2s(e.a.x,e.a.y),q=w2s(e.b.x,e.b.y);
    var on=focus&&(e.a===focus||e.b===focus),dim=(focus&&!on)||(filtering&&!(e.a.hit||e.b.hit));
    ctx.globalAlpha=dim?.03:(on?.85:.22);
    ctx.strokeStyle=on?"#7aa2ff":colorOf(e.a.c);
    ctx.lineWidth=on?1.8:0.9;
    ctx.beginPath();ctx.moveTo(p[0],p[1]);ctx.lineTo(q[0],q[1]);ctx.stroke();
  });
  ctx.globalAlpha=1;
  N.forEach(function(n){
    if(!n.show)return;var p=w2s(n.x,n.y),r=n.r*z,rr=Math.max(3,r);
    var dim=(focus&&n!==focus&&!(nb&&nb[n.i]))||(filtering&&!n.hit);
    ctx.globalAlpha=dim?.12:1;
    ctx.fillStyle=colorOf(n.c);
    ctx.beginPath();ctx.arc(p[0],p[1],rr,0,6.2832);ctx.fill();
    if(n===sel||n===hover||(filtering&&n.hit)){
      ctx.lineWidth=2;ctx.strokeStyle="#ffffff";ctx.stroke();
    }
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
  N.forEach(function(n){if(!n.show)return;var dx=n.x-w[0],dy=n.y-w[1],d=Math.sqrt(dx*dx+dy*dy),rr=n.r+6/z;if(d<rr&&d<bd){bd=d;best=n}});
  return best;
}
function detail(n){
  var box=$("detail"),body=$("detail-body");body.textContent="";
  if(!n){box.style.display="none";return}
  box.style.display="block";
  body.appendChild(el("h3",n.l));
  body.appendChild(el("p",(CM[n.c]?CM[n.c].name:"community "+n.c)+" · "+n.p));
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
  if(n){tip.style.display="block";tip.style.left=Math.min(W-220,sx+14)+"px";tip.style.top=(sy+14)+"px";tip.textContent=n.l+" ("+(CM[n.c]?CM[n.c].name:"")+")"}else tip.style.display="none";
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
$("fit").onclick=fit;
$("pause").onclick=function(){running=!running;if(running)alpha=Math.max(alpha,.3);$("pause").textContent=running?"Pause":"Resume"};
window.addEventListener("resize",function(){resize()});
renderCommunities();
resize();for(var s=0;s<380;s++)tick();fit();requestAnimationFrame(frame);
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
