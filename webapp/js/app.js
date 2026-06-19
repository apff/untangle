/* Untangle — interactive dependency graph (single screen).
   Ported from the design prototype. Behavior: deterministic ring layout, hover
   path-tracing, click-to-focus, consumer-bundle expand/collapse, system collapse,
   blast-radius highlighting, details panel, HTML title overlay, language filter +
   search. Theme is Midnight Refined in dark/light only. Data comes from the
   analyzer contract (graph.json) via data.js; cytoscape is a global from vendor/. */

import { THEMES } from "./themes.js";
import { loadGraph, deriveModel, ReportLoadError } from "./data.js";
import {
  clamp, decorateNodes, nodeEl, buildAdjacency, blastRadius,
  clearFx, neighborhood, softHighlight,
} from "./graph-render.js";

const cytoscape = window.cytoscape;
const STALE_MS = 36 * 60 * 60 * 1000; // matches the analyzer's daily cadence + headroom

function showError(msg) {
  const el = document.getElementById("error-banner");
  if (!el) return;
  el.textContent = msg;
  el.hidden = false;
}

function relativeAge(ms) {
  const m = Math.floor(ms / 60000);
  if (m < 60) return m + "m";
  const h = Math.floor(m / 60);
  if (h < 48) return h + "h";
  return Math.floor(h / 24) + "d";
}

function initStaleBadge(generatedAt) {
  const el = document.getElementById("stale");
  if (!el || !generatedAt) return;
  const t = new Date(generatedAt);
  if (isNaN(t.getTime())) return;
  const age = Date.now() - t.getTime();
  const stale = age > STALE_MS;
  el.hidden = false;
  el.classList.toggle("fresh", !stale);
  el.textContent = "Data " + relativeAge(age) + " ago" + (stale ? " · stale" : "");
}

// Numeric, dot-wise compare: is version `a` newer than `b`? (e.g. 0.10 > 0.9).
function isNewerVersion(a, b) {
  const pa = String(a).split("."), pb = String(b).split(".");
  for (let i = 0; i < Math.max(pa.length, pb.length); i++) {
    const x = parseInt(pa[i] || "0", 10), y = parseInt(pb[i] || "0", 10);
    if (isNaN(x) || isNaN(y)) return false;
    if (x !== y) return x > y;
  }
  return false;
}

function initFooter(D) {
  const footer = document.getElementById("footer");
  if (!footer) return;
  const ver = D.appVersion ? "Untangle v" + D.appVersion : "Untangle";
  footer.textContent = ver + " · generated from git dependency analysis · "
    + D.nodes.length + " repos · " + D.SYSTEMS.length + " systems · " + D.HUBS.length + " shared components";
  // Server-side check already resolved the latest release; just compare strings.
  if (D.appVersion && D.latestVersion && isNewerVersion(D.latestVersion, D.appVersion)) {
    footer.append(" · ");
    const a = document.createElement("a");
    a.className = "update-link";
    a.textContent = "update available → v" + D.latestVersion;
    if (D.latestVersionUrl) { a.href = D.latestVersionUrl; a.target = "_blank"; a.rel = "noopener"; }
    footer.append(a);
  }
}

async function init() {
  let D;
  try {
    D = deriveModel(await loadGraph());
  } catch (err) {
    const msg = err instanceof ReportLoadError ? err.message : `Failed to load graph: ${err.message}`;
    showError(msg);
    return;
  }
  if (!D.nodes.length) {
    showError("The graph is empty — waiting for the first analyzer run to publish data.");
    return;
  }
  build(D);
}

function build(D) {
  /* ---------- chrome wiring ---------- */
  initStaleBadge(D.generatedAt);
  initFooter(D);

  /* ---------- graph model precompute (shared with the embed via graph-render.js) ---------- */
  // Full-graph adjacency (independent of what's visible) + per-node visual data
  // (color / size / gradient / icon). blastRadius(fullIn, id) = transitive dependents.
  const { fullOut, fullIn } = buildAdjacency(D);
  decorateNodes(D);

  /* ---------- which nodes are bundled vs present ---------- */
  const memberToSys = {};               // bundleable node id -> system id
  const bundleMembers = {};             // system id -> [node ids]
  D.SYSTEMS.forEach((s) => (bundleMembers[s.id] = []));
  D.nodes.forEach((n) => { if (n.bundleable && bundleMembers[n.system]) { memberToSys[n.id] = n.system; bundleMembers[n.system].push(n.id); } });

  const presentInitial = D.nodes.filter((n) => !n.bundleable);

  /* ---------- build elements ---------- */
  const elements = [];
  // dummy visual fields so base node-style data() mappings resolve on parents/bundles
  const stub = { color: "#888", colorLite: "#aaa", colorDark: "#444", gradStops: "#aaa #888 #444", size: 50 };
  // parents: shared + systems
  elements.push({ group: "nodes", data: Object.assign({ id: "shared", label: "Shared Components", sysColor: "#9aa3ad", isParent: true }, stub) });
  D.SYSTEMS.forEach((s) => elements.push({ group: "nodes", data: Object.assign({ id: s.id, label: s.label, sysColor: s.color, isParent: true }, stub) }));
  // map shared hubs to parent 'shared'
  presentInitial.forEach((n) => { const el = nodeEl(n, D.systemById); if (n.system === "shared") el.data.parent = "shared"; elements.push(el); });
  // bundle nodes (one per system that has bundleables)
  D.SYSTEMS.forEach((s) => {
    const m = bundleMembers[s.id]; if (!m.length) return;
    elements.push({ group: "nodes", data: Object.assign({}, stub, {
      id: "bundle:" + s.id, parent: s.id, isBundle: true, sys: s.id,
      sysColor: s.color, size: clamp(50 + m.length * 2.2, 56, 86),
      label: m.length + "\n+",
    }), classes: "bundle" });
  });
  // edges among present nodes
  const presentIds = new Set(presentInitial.map((n) => n.id));
  D.edges.forEach((e) => { if (presentIds.has(e.source) && presentIds.has(e.target)) elements.push({ group: "edges", data: { id: e.id, source: e.source, target: e.target, kind: e.kind } }); });

  /* ---------- cytoscape ---------- */
  const cy = cytoscape({
    container: document.getElementById("cy"),
    elements, style: THEMES.midnight.style,
    wheelSensitivity: 0.25, minZoom: 0.15, maxZoom: 2.5,
    boxSelectionEnabled: false, selectionType: "single",
  });
  window.cy = cy;

  /* ---------- layout: shared cluster center, systems on a ring ---------- */
  function layoutGrid(ids, cx, cyy, spacing) {
    const n = ids.length; if (!n) return;
    const cols = Math.ceil(Math.sqrt(n)), rows = Math.ceil(n / cols);
    ids.forEach((id, i) => {
      const col = i % cols, row = Math.floor(i / cols);
      const x = cx + (col - (cols - 1) / 2) * spacing;
      const y = cyy + (row - (rows - 1) / 2) * spacing;
      const el = cy.getElementById(id); if (el.nonempty()) el.position({ x, y });
    });
  }
  function runLayout() {
    // shared hubs in center
    layoutGrid(D.HUBS.map((h) => h.id), 0, 0, 175);
    const R = 1380; // ring radius for the system clusters around the shared core
    const systems = D.SYSTEMS;
    systems.forEach((s, i) => {
      const ang = -Math.PI / 2 + (i / Math.max(1, systems.length)) * Math.PI * 2;
      const scx = Math.cos(ang) * R, scy = Math.sin(ang) * R;
      const kids = cy.nodes('[parent = "' + s.id + '"]').filter((n) => n.visible()).map((n) => n.id());
      layoutGrid(kids, scx, scy, 168);
    });
    cy.fit(undefined, 90);
  }
  runLayout();
  cy.minZoom(Math.min(cy.zoom() * 0.5, 0.15));

  /* ---------- highlight engine (primitives shared via graph-render.js) ---------- */
  const state = { locked: false, selected: null, theme: "midnight", light: false, langs: new Set(Object.keys(D.LANGS)), query: "" };
  function focusNode(node) {
    clearFx(cy); softHighlight(cy, node);
    cy.animate({ fit: { eles: neighborhood(node).nodes, padding: 110 } }, { duration: 420, easing: "ease-out" });
  }

  /* ---------- bundle expand / collapse ---------- */
  function expandBundle(sysId, animate) {
    const bundle = cy.getElementById("bundle:" + sysId);
    if (bundle.empty() || bundle.data("expanded")) return cy.collection();
    bundle.data("expanded", true).data("label", "−");
    const bp = bundle.position();
    const members = bundleMembers[sysId];
    const added = cy.collection();
    members.forEach((id) => {
      const n = D.byId[id]; const el = nodeEl(n, D.systemById);
      el.data.parent = sysId;
      const node = cy.add(el); node.position({ x: bp.x, y: bp.y }); added.merge(node);
    });
    members.forEach((id) => presentIds.add(id));
    // add edges that now have both endpoints present
    D.edges.forEach((e) => {
      if (cy.getElementById(e.id).nonempty()) return;
      if (presentIds.has(e.source) && presentIds.has(e.target)) cy.add({ group: "edges", data: { id: e.id, source: e.source, target: e.target, kind: e.kind } });
    });
    // fan out positions around the bundle
    const k = members.length, radius = clamp(70 + k * 9, 90, 200);
    members.forEach((id, i) => {
      const ang = (-Math.PI * 0.85) + (Math.PI * 1.7) * (k === 1 ? 0.5 : i / (k - 1));
      const tx = bp.x + Math.cos(ang) * radius, ty = bp.y + Math.sin(ang) * radius * 0.85;
      const node = cy.getElementById(id);
      if (animate === false) { node.position({ x: tx, y: ty }); }
      else { node.style("opacity", 0); node.animate({ position: { x: tx, y: ty }, style: { opacity: 1 } }, { duration: 420, easing: "ease-out" }); }
    });
    // Newly-added nodes must honor the active repo filter. Apply it now, and for
    // the animated path clear the fade-in's inline opacity once it settles —
    // otherwise that inline value overrides the .dim class and they look unfiltered.
    applyFilter();
    if (animate !== false) setTimeout(() => { added.removeStyle("opacity"); applyFilter(); }, 440);
    return added;
  }
  function collapseBundle(sysId) {
    const bundle = cy.getElementById("bundle:" + sysId);
    if (bundle.empty() || !bundle.data("expanded")) return;
    const bp = bundle.position();
    const members = bundleMembers[sysId];
    const nodes = cy.collection(); members.forEach((id) => nodes.merge(cy.getElementById(id)));
    nodes.animate({ position: { x: bp.x, y: bp.y }, style: { opacity: 0 } }, { duration: 320, easing: "ease-in", complete: () => {
      nodes.remove(); members.forEach((id) => presentIds.delete(id));
    }});
    bundle.data("expanded", false).data("label", members.length + "\n+");
  }
  function toggleBundle(bundle) {
    const sysId = bundle.data("sys");
    if (bundle.data("expanded")) collapseBundle(sysId);
    else { const added = expandBundle(sysId, true); cy.animate({ fit: { eles: added.add(bundle), padding: 120 } }, { duration: 450 }); }
  }

  /* ---------- system collapse (double-click a system region) ---------- */
  function styleSummary(sum, sysId, count) {
    const sz = clamp(64 + count * 1.4, 70, 116);
    sum.style({ "background-color": D.systemById[sysId].color, "background-opacity": 0.92, "background-fill": "solid", color: "#ffffff", "font-weight": 700, "font-size": Math.round(sz * 0.32), "border-width": 0, width: sz, height: sz, shape: "ellipse", "text-valign": "center", "text-halign": "center", "text-background-opacity": 0 });
  }
  function collapseSystem(sysId) {
    const parent = cy.getElementById(sysId); if (parent.data("collapsed")) return;
    collapseBundle(sysId);
    const count = D.nodes.filter((n) => n.system === sysId).length;
    const kids = parent.children();
    const center = parent.position();
    kids.style("display", "none");
    const sum = cy.add({ group: "nodes", data: { id: "sum:" + sysId, parent: sysId, label: String(count), sysColor: D.systemById[sysId].color }, classes: "collapsedSys" });
    sum.position(center);
    styleSummary(sum, sysId, count);
    parent.data("collapsed", true);
  }
  function expandSystem(sysId) {
    const parent = cy.getElementById(sysId); if (!parent.data("collapsed")) return;
    cy.getElementById("sum:" + sysId).remove();
    parent.children().style("display", "element");
    parent.data("collapsed", false);
  }
  function toggleSystem(parent) {
    if (parent.id() === "shared") return;
    parent.data("collapsed") ? expandSystem(parent.id()) : collapseSystem(parent.id());
  }

  /* ---------- ensure a node is visible (expand its bundle) ---------- */
  function ensurePresent(id) {
    if (cy.getElementById(id).nonempty() && cy.getElementById(id).visible()) return;
    const sys = memberToSys[id]; if (sys) { if (cy.getElementById(sys).data("collapsed")) expandSystem(sys); expandBundle(sys, true); }
  }

  /* ---------- blast radius ---------- */
  function showBlast(id) {
    const set = blastRadius(fullIn, id);
    const sysToExpand = new Set();
    set.forEach((d) => { if (memberToSys[d]) sysToExpand.add(memberToSys[d]); });
    sysToExpand.forEach((s) => { if (cy.getElementById(s).data("collapsed")) expandSystem(s); expandBundle(s, false); });
    clearFx(cy);
    cy.elements().addClass("dim"); cy.edges().addClass("dim-edge");
    cy.nodes(":parent").removeClass("dim");
    const inBlast = (nid) => set.has(nid) || nid === id;
    const blastNodes = cy.collection();
    set.forEach((d) => { const n = cy.getElementById(d); if (n.nonempty()) { n.removeClass("dim").addClass("blast-node"); blastNodes.merge(n); } });
    const target = cy.getElementById(id); target.removeClass("dim").addClass("hl-node"); blastNodes.merge(target);
    cy.edges().forEach((e) => { if (inBlast(e.source().id()) && inBlast(e.target().id())) e.removeClass("dim dim-edge").addClass("blast"); });
    cy.animate({ fit: { eles: blastNodes, padding: 100 } }, { duration: 500 });
    return set.size;
  }

  /* ---------- details panel ---------- */
  const panel = document.getElementById("detail");
  const ago = (d) => d == null ? "unknown" : d === 0 ? "today" : d === 1 ? "1 day ago" : d < 60 ? d + " days ago" : Math.round(d / 30) + " months ago";
  const esc = (s) => String(s == null ? "" : s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
  const chip = (txt, color, dark) => '<span class="chip" style="--c:' + color + '">' + (dark ? '<i class="dot"></i>' : '') + esc(txt) + '</span>';
  const FALLBACK_REF_COLOR = "#9aa3ad";
  function refColorOf(id) {
    const n = D.byId[id];
    if (!n) return FALLBACK_REF_COLOR;
    return (D.LANGS[n.lang] || {}).color || FALLBACK_REF_COLOR;
  }
  function listLinks(ids) {
    if (!ids.length) return '<span class="muted">none</span>';
    return ids.map((id) => '<button class="ref" style="--c:' + refColorOf(id) + '" data-go="' + esc(id) + '"><i class="rdot"></i>' + esc(D.byId[id] ? D.byId[id].label : id) + '</button>').join("");
  }
  // The dashed cluster outline is shown only while its system is the panel's
  // subject. Clearing on every non-system render keeps exactly one (or none) lit.
  function setActiveSystem(id) {
    cy.nodes(".sys-active").removeClass("sys-active");
    if (id) { const p = cy.getElementById(id); if (p.nonempty() && p.data("isParent")) p.addClass("sys-active"); }
  }
  function renderEmpty() {
    setActiveSystem(null);
    panel.innerHTML = '<div class="empty"><div class="empty-icon">◌</div><p>Select a node to inspect its dependencies, dependents, and blast radius.</p>'
      + '<ul class="hints"><li><b>Hover</b> — trace connected paths</li><li><b>Click</b> — focus on neighbors</li><li><b>Click a bundle</b> — expand consumers</li><li><b>Click a title</b> — zoom to that cluster</li><li><b>Drag a title</b> — move the cluster</li></ul></div>';
  }
  function renderNode(node) {
    setActiveSystem(null);
    const id = node.id(), n = D.byId[id];
    const deps = fullOut[id] || [], dependents = fullIn[id] || [];
    const blast = blastRadius(fullIn, id).size;
    const sys = D.systemById[n.system];
    const lang = D.LANGS[n.lang] || { label: n.lang, color: "#8a8580" };
    const kindLabel = n.kind === "hub" ? "shared component" : n.kind === "anchor" ? "library" : "repository";
    const groupPrefix = n.group ? esc(n.group) + "/" : "";
    panel.innerHTML =
      '<div class="d-head">'
      + '<div class="d-kind">' + kindLabel + '</div>'
      + '<h2>' + esc(n.label) + '</h2>'
      + '<div class="chips">' + (sys ? chip(sys.label, sys.color, true) : "") + chip(lang.label, lang.color, true) + '</div>'
      + '</div>'
      + '<div class="repo-meta">'
      + (n.url ? '<a class="repo-path" href="' + esc(n.url) + '" target="_blank" rel="noopener">' + groupPrefix + '<b>' + esc(n.label) + '</b><i>↗</i></a>'
               : '<span class="repo-path">' + groupPrefix + '<b>' + esc(n.label) + '</b></span>')
      + (n.description ? '<p class="repo-desc">' + esc(n.description) + '</p>' : '<p class="repo-desc none">No description available.</p>')
      + '</div>'
      + '<div class="blast-card' + (blast > 0 ? ' danger' : '') + '">'
      + '<div class="blast-num">' + blast + '</div>'
      + '<div class="blast-lbl">repo' + (blast === 1 ? "" : "s") + ' break if this fails<br><span>transitive blast radius</span></div>'
      + (blast > 0 ? '<button class="btn-blast" id="btnBlast">Highlight blast radius</button>' : '')
      + '</div>'
      + '<div class="d-sec"><div class="d-lbl">Depends on <b>' + deps.length + '</b></div><div class="reflist">' + listLinks(deps) + '</div></div>'
      + '<div class="d-sec"><div class="d-lbl">Depended on by <b>' + dependents.length + '</b></div><div class="reflist">' + listLinks(dependents) + '</div></div>'
      + '<div class="d-meta"><span>last commit</span><b>' + ago(n.lastDays) + (n.lastDays != null && n.lastDays > 120 ? ' <i class="stale">stale</i>' : '') + '</b></div>';
    const b = document.getElementById("btnBlast"); if (b) b.onclick = () => { const c = showBlast(id); b.textContent = "Showing " + c + " affected"; };
    wireRefs();
  }
  function renderBundle(node) {
    setActiveSystem(null);
    const sysId = node.data("sys"), s = D.systemById[sysId], members = bundleMembers[sysId];
    panel.innerHTML = '<div class="d-head"><div class="d-kind">consumer bundle</div><h2>' + esc(s.label) + ' consumers</h2>'
      + '<div class="chips">' + chip(s.label, s.color, true) + chip(members.length + " repos", "#9aa3ad", false) + '</div></div>'
      + '<p class="d-desc">Leaf repositories that only consume shared components — bundled to keep the graph readable. ' + (node.data("expanded") ? "Click the bundle to collapse." : "Click the bundle to expand.") + '</p>'
      + '<div class="d-sec"><div class="d-lbl">Members</div><div class="reflist">' + listLinks(members) + '</div></div>';
    wireRefs();
  }
  function renderSystem(parent) {
    const sysId = parent.id();
    setActiveSystem(sysId);
    if (sysId === "shared") {
      panel.innerHTML = '<div class="d-head"><div class="d-kind">cluster</div><h2>Shared Components</h2></div>'
        + '<p class="d-desc">Org-wide building blocks. These have the largest blast radius — select one to see what depends on it.</p>'
        + '<div class="d-sec"><div class="d-lbl">Components</div><div class="reflist">' + listLinks(D.HUBS.map((h) => h.id)) + '</div></div>';
      wireRefs(); return;
    }
    const s = D.systemById[sysId];
    const members = D.nodes.filter((n) => n.system === sysId);
    const langCount = {}; members.forEach((m) => langCount[m.lang] = (langCount[m.lang] || 0) + 1);
    panel.innerHTML = '<div class="d-head"><div class="d-kind">system</div><h2>' + esc(s.label) + '</h2>'
      + '<div class="chips">' + chip(members.length + " repos", s.color, true) + '</div></div>'
      + '<div class="d-sec"><div class="d-lbl">Languages</div><div class="chips">' + Object.keys(langCount).sort((a, b) => langCount[b] - langCount[a]).map((l) => chip((D.LANGS[l] ? D.LANGS[l].label : l) + " " + langCount[l], (D.LANGS[l] || {}).color || "#8a8580", true)).join("") + '</div></div>'
      + '<div class="d-sec"><button class="btn-blast" id="btnSys">' + (parent.data("collapsed") ? "Expand system" : "Collapse system") + '</button></div>';
    document.getElementById("btnSys").onclick = () => { toggleSystem(parent); renderSystem(parent); };
  }
  const REASON_META = {
    package:  { icon: "⬢", label: "Package import" },
    api:      { icon: "⇄", label: "API call" },
    database: { icon: "▤", label: "Shared database" },
    function: { icon: "ƒ", label: "Function / symbol" },
    pipeline: { icon: "⚙", label: "CI pipeline" },
    config:   { icon: "⚙", label: "Configuration" },
  };
  function renderEdge(edge) {
    setActiveSystem(null);
    const s = D.byId[edge.source().id()] || { label: edge.source().id() }, t = D.byId[edge.target().id()] || { label: edge.target().id() };
    const meta = D.edgeById[edge.id()], reasons = meta ? meta.reasons : [];
    const reasonHtml = reasons.map((r) => { const m = REASON_META[r.type] || { icon: "•", label: r.type }; return '<div class="reason"><div class="reason-type"><span class="ri">' + m.icon + '</span>' + esc(m.label) + '</div><code>' + esc(r.detail) + '</code></div>'; }).join("");
    panel.innerHTML = '<div class="d-head"><div class="d-kind">dependency</div><h2 class="edge-h">' + esc(s.label) + ' <i>→</i> ' + esc(t.label) + '</h2></div>'
      + '<p class="d-desc"><b>' + esc(s.label) + '</b> depends on <b>' + esc(t.label) + '</b>. It is coupled through:</p>'
      + '<div class="d-sec"><div class="d-lbl">Coupled through <b>' + reasons.length + '</b></div><div class="reasons">' + (reasonHtml || '<span class="muted">no detail captured</span>') + '</div></div>';
  }
  function wireRefs() {
    panel.querySelectorAll("[data-go]").forEach((b) => b.onclick = () => { const id = b.getAttribute("data-go"); ensurePresent(id); const node = cy.getElementById(id); if (node.nonempty()) { state.locked = true; state.selected = id; cy.$(":selected").unselect(); node.select(); focusNode(node); routeDetails(node); } });
  }
  function routeDetails(ele) {
    if (ele.isEdge && ele.isEdge()) return renderEdge(ele);
    if (ele.data("isParent")) return renderSystem(ele);
    if (ele.data("isBundle")) return renderBundle(ele);
    renderNode(ele);
  }
  renderEmpty();

  /* ---------- events ---------- */
  cy.on("mouseover", "node", (e) => { if (!state.locked && !e.target.data("isParent")) softHighlight(cy, e.target); });
  // Restore the language/search filter on mouseout — clearFx() strips the same
  // dim/hl-node classes the filter uses, so re-apply it or filtering "sticks off".
  cy.on("mouseout", "node", () => { if (!state.locked) { clearFx(cy); applyFilter(); } });
  cy.on("tap", "node", (e) => {
    const n = e.target;
    if (n.id().indexOf("sum:") === 0) { const sysId = n.id().slice(4); expandSystem(sysId); state.locked = false; clearFx(cy); renderSystem(cy.getElementById(sysId)); cy.animate({ fit: { eles: cy.getElementById(sysId), padding: 120 } }, { duration: 420 }); return; }
    if (n.data("isBundle")) { toggleBundle(n); renderBundle(n); return; }
    if (n.data("isParent")) { state.locked = false; clearFx(cy); renderSystem(n); return; }
    state.locked = true; state.selected = n.id(); focusNode(n); routeDetails(n);
  });
  cy.on("dbltap", "node", (e) => { if (e.target.data("isParent")) { toggleSystem(e.target); renderSystem(e.target); } });
  cy.on("tap", "edge", (e) => { state.locked = true; clearFx(cy); e.target.addClass("hl"); renderEdge(e.target); });
  function resetView() { state.locked = false; state.selected = null; cy.$(":selected").unselect(); clearFx(cy); applyFilter(); renderEmpty(); cy.animate({ fit: { padding: 90 } }, { duration: 420 }); }
  cy.on("tap", (e) => { if (e.target === cy) resetView(); });
  const overviewLink = document.getElementById("overviewLink");
  if (overviewLink) overviewLink.onclick = (e) => { e.preventDefault(); resetView(); };

  /* ---------- system titles (HTML overlay) ---------- */
  const titlesEl = document.getElementById("titles");
  const titleDivs = {};
  function titleFit(id) {
    const p = cy.getElementById(id); if (p.empty()) return;
    state.locked = false; cy.$(":selected").unselect(); clearFx(cy);
    renderSystem(p);
    cy.animate({ fit: { eles: p.descendants().add(p), padding: 70 } }, { duration: 420, easing: "ease-out" });
  }
  function makeTitle(id, label) {
    const div = document.createElement("div");
    div.className = "sys-title" + (id === "shared" ? " shared" : "");
    div.textContent = label;
    if (id !== "shared" && D.systemById[id]) div.style.color = D.systemById[id].color;
    titlesEl.appendChild(div);
    titleDivs[id] = div;
    let dragging = false, moved = false, sx = 0, sy = 0, start = {};
    div.addEventListener("mousedown", (e) => {
      e.preventDefault(); dragging = true; moved = false; sx = e.clientX; sy = e.clientY;
      div.classList.add("grabbing"); start = {};
      cy.getElementById(id).descendants().forEach((n) => { start[n.id()] = { x: n.position("x"), y: n.position("y") }; });
    });
    window.addEventListener("mousemove", (e) => {
      if (!dragging) return;
      const dx = e.clientX - sx, dy = e.clientY - sy;
      if (Math.abs(dx) + Math.abs(dy) > 4) moved = true;
      const z = cy.zoom();
      cy.getElementById(id).descendants().forEach((n) => { const s = start[n.id()]; if (s) n.position({ x: s.x + dx / z, y: s.y + dy / z }); });
      syncTitles();
    });
    window.addEventListener("mouseup", () => {
      if (!dragging) return; dragging = false; div.classList.remove("grabbing");
      if (!moved) titleFit(id);
    });
  }
  makeTitle("shared", "Shared Components");
  D.SYSTEMS.forEach((s) => makeTitle(s.id, s.label));
  function syncTitles() {
    Object.keys(titleDivs).forEach((id) => {
      const p = cy.getElementById(id), div = titleDivs[id];
      if (p.empty()) { div.style.display = "none"; return; }
      const bb = p.renderedBoundingBox({ includeLabels: false, includeOverlays: false });
      if (!bb || bb.w === 0) { div.style.display = "none"; return; }
      div.style.display = "block";
      div.style.left = ((bb.x1 + bb.x2) / 2) + "px";
      div.style.top = (bb.y1 - 3) + "px";
    });
  }
  let titleRaf = false;
  cy.on("render", () => { if (titleRaf) return; titleRaf = true; requestAnimationFrame(() => { titleRaf = false; syncTitles(); }); });
  syncTitles();

  /* ---------- theme switch (Midnight dark / light only) ---------- */
  function effectiveTheme() { return state.light ? "midnight-light" : "midnight"; }
  function applyTheme() {
    const id = effectiveTheme();
    state.theme = id;
    cy.style(THEMES[id].style);
    document.body.className = "theme-" + id;
    document.getElementById("themeToggle").classList.toggle("is-light", state.light);
    // re-apply collapsed-system summary inline styles (bypasses are cleared by style())
    D.SYSTEMS.forEach((s) => { if (cy.getElementById(s.id).data("collapsed")) { const sum = cy.getElementById("sum:" + s.id); if (sum.nonempty()) styleSummary(sum, s.id, D.nodes.filter((n) => n.system === s.id).length); } });
    syncTitles();
    applyFilter();
  }
  document.getElementById("themeToggle").onclick = () => { state.light = !state.light; applyTheme(); };

  /* ---------- language filter + search ---------- */
  function applyFilter() {
    if (state.locked) return;
    const q = state.query.trim().toLowerCase();
    cy.nodes().forEach((n) => {
      if (n.data("isParent") || n.data("isBundle")) return;
      const okLang = state.langs.has(n.data("lang"));
      const okQ = !q || (n.data("label") || "").toLowerCase().includes(q);
      n.toggleClass("dim", !(okLang && okQ));
      n.toggleClass("hl-node", !!q && okQ && okLang);
    });
  }
  const legend = document.getElementById("legend");
  Object.keys(D.LANGS).forEach((l) => {
    const b = document.createElement("button");
    b.className = "lang-chip active"; b.dataset.lang = l;
    b.innerHTML = '<i style="background:' + D.LANGS[l].color + '"></i>' + esc(D.LANGS[l].label);
    b.onclick = () => { if (state.langs.has(l)) { state.langs.delete(l); b.classList.remove("active"); } else { state.langs.add(l); b.classList.add("active"); } applyFilter(); };
    legend.appendChild(b);
  });
  const search = document.getElementById("search");
  search.oninput = () => { state.query = search.value; applyFilter(); };
  search.onkeydown = (e) => { if (e.key === "Enter") { const m = cy.nodes().filter((n) => !n.data("isParent") && !n.data("isBundle") && (n.data("label") || "").toLowerCase().includes(state.query.trim().toLowerCase()) && n.visible()); if (m.nonempty()) { const t = m[0]; state.locked = true; state.selected = t.id(); clearFx(cy); focusNode(t); routeDetails(t); } } };

  applyTheme();
}

init();
