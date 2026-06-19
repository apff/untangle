/* Untangle — shared graph rendering core.
   The visual identity of the dependency graph: language→color math, the type-icon
   set, per-node visual precompute, the Cytoscape element builder, adjacency/blast
   helpers, and the hover/dim highlight primitives. Both the full single-screen app
   (app.js) and the standalone embed (mountGraph, used by the marketing site) import
   from here so there is ONE source of truth — keep it framework-free and pure.
   cytoscape is a global from vendor/cytoscape.min.js; themes.js holds the styles. */

import { THEMES } from "./themes.js";

const cytoscape = window.cytoscape;

/* ---------- color helpers ---------- */
export const h2r = (h) => { h = h.replace("#", ""); return [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16)); };
export const r2h = (r, g, b) => "#" + [r, g, b].map((x) => ("0" + Math.round(Math.max(0, Math.min(255, x))).toString(16)).slice(-2)).join("");
export const mix = (hex, t, k) => { const a = h2r(hex), b = h2r(t); return r2h(a[0] + (b[0] - a[0]) * k, a[1] + (b[1] - a[1]) * k, a[2] + (b[2] - a[2]) * k); };
export const lighten = (h, k) => mix(h, "#ffffff", k);
export const darken = (h, k) => mix(h, "#000000", k);
export const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));

/* ---------- type icons (drawn inside each node) ---------- */
const ic = (inner) => "data:image/svg+xml;utf8," + encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="#1d2940" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' + inner + "</svg>");
export const ICONS = {
  database: ic('<ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v6c0 1.7 3.6 3 8 3s8-1.3 8-3V5"/><path d="M4 11v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6"/>'),
  api: ic('<path d="M3 9h13l-3-3"/><path d="M21 15H8l3 3"/>'),
  library: ic('<path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/><path d="M3.3 7L12 12l8.7-5"/><path d="M12 22V12"/>'),
  service: ic('<rect x="3" y="4" width="18" height="7" rx="1.5"/><rect x="3" y="13" width="18" height="7" rx="1.5"/><path d="M7 7.5h.01M7 16.5h.01"/>'),
  tool: ic('<path d="M14.7 6.3a4 4 0 0 0-5.4 5.4l-6.1 6 2.7 2.7 6-6.1a4 4 0 0 0 5.4-5.4l-2.6 2.6-2.1-2.1 2.1-2.1z"/>'),
  config: ic('<path d="M4 6h9M19 6h1"/><path d="M4 12h3M13 12h7"/><path d="M4 18h11M21 18h0"/><circle cx="16" cy="6" r="2"/><circle cx="10" cy="12" r="2"/><circle cx="18" cy="18" r="2"/>'),
  frontend: ic('<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 9h18"/><path d="M6.5 6.5h.01"/>'),
  infra: ic('<path d="M12 2l9 5-9 5-9-5 9-5z"/><path d="M3 12l9 5 9-5"/><path d="M3 17l9 5 9-5"/>'),
  container: ic('<path d="M12 2l8 4.5v9L12 20l-8-4.5v-9L12 2z"/><path d="M4 6.5l8 4.5 8-4.5"/><path d="M12 11v9"/>'),
  auth: ic('<rect x="4" y="10" width="16" height="10" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3"/>'),
  pipeline: ic('<circle cx="6" cy="6" r="2"/><circle cx="6" cy="18" r="2"/><circle cx="18" cy="12" r="2"/><path d="M6 8v8"/><path d="M8 6h6a2 2 0 0 1 2 2v2.5M16 13.5V16a2 2 0 0 1-2 2H8"/>'),
};

/* ---------- precompute node visual data (color / size / gradient / icon) ---------- */
export function decorateNodes(D) {
  D.nodes.forEach((n) => {
    const c = (D.LANGS[n.lang] || { color: "#8a8580" }).color;
    n.color = c; n.colorLite = lighten(c, 0.4); n.colorDark = darken(c, 0.35);
    const deg = n.indeg + n.outdeg;
    if (n.kind === "hub") { n.color = lighten(c, 0.05); n.size = clamp(48 + n.indeg * 1.1, 52, 92); }
    else { n.size = clamp(30 + deg * 3, 30, 60); }
    n.gradStops = lighten(n.color, 0.5) + " " + n.color + " " + darken(n.color, 0.35);
    n.icon = ICONS[n.type] || ICONS.service;
  });
  return D;
}

/* ---------- Cytoscape element builder ---------- */
export function nodeEl(n, systemById) {
  return { group: "nodes", data: {
    id: n.id, label: n.label, parent: n.system, kind: n.kind,
    color: n.color, colorLite: n.colorLite, colorDark: n.colorDark,
    gradStops: n.gradStops, icon: n.icon, ntype: n.type,
    sysColor: (systemById[n.system] || {}).color || "#888", size: n.size, lang: n.lang,
  }, classes: n.kind === "hub" ? "hub" : "" };
}

/* ---------- adjacency + blast radius (transitive dependents) ---------- */
export function buildAdjacency(D) {
  const fullOut = {}, fullIn = {};
  D.nodes.forEach((n) => { fullOut[n.id] = []; fullIn[n.id] = []; });
  D.edges.forEach((e) => { fullOut[e.source].push(e.target); fullIn[e.target].push(e.source); });
  return { fullOut, fullIn };
}

export function blastRadius(fullIn, id) { // transitive dependents (who breaks if id breaks)
  const seen = new Set(), q = [id];
  while (q.length) { const cur = q.shift(); (fullIn[cur] || []).forEach((s) => { if (!seen.has(s)) { seen.add(s); q.push(s); } }); }
  return seen;
}

/* ---------- highlight primitives ---------- */
export function clearFx(cy) { cy.elements().removeClass("dim dim-edge hl blast hl-node blast-node"); }

export function neighborhood(node) {
  const edges = node.connectedEdges(":visible");
  const nodes = edges.connectedNodes().add(node);
  return { edges, nodes };
}

export function softHighlight(cy, node) {
  const { edges, nodes } = neighborhood(node);
  cy.elements().addClass("dim"); cy.edges().addClass("dim-edge");
  nodes.removeClass("dim").addClass("hl-node"); node.removeClass("hl-node");
  edges.removeClass("dim dim-edge").addClass("hl"); nodes.removeClass("dim-edge");
  cy.nodes(":parent").removeClass("dim");
}

/* ---------- standalone embed: a small, self-contained graph for the marketing site ----------
   A flat (no system-cluster parents) graph with the exact app styling, a deterministic
   concentric layout (shared hubs in the middle), page-scroll-friendly (no zoom/pan grab),
   hover path-tracing and click-to-show-blast-radius. Returns the cytoscape instance. */
export function mountGraph(container, D, opts = {}) {
  const { theme = "midnight", interactive = true, fitPadding = 40, onSelect = null } = opts;
  decorateNodes(D);
  const { fullIn } = buildAdjacency(D);

  const elements = [];
  D.nodes.forEach((n) => { const el = nodeEl(n, D.systemById); delete el.data.parent; elements.push(el); });
  D.edges.forEach((e) => elements.push({ group: "edges", data: { id: e.id, source: e.source, target: e.target } }));

  const cy = cytoscape({
    container,
    elements,
    style: THEMES[theme].style,
    layout: {
      // Force-directed: organic, balanced clusters that read as a real graph.
      // Explicit landscape boundingBox so the spread doesn't collapse into the
      // (initially narrow) container — cy.fit() frames it afterwards.
      name: "cose",
      animate: false,
      padding: fitPadding,
      boundingBox: { x1: 0, y1: 0, w: 900, h: 560 },
      nodeRepulsion: 12000,
      idealEdgeLength: 100,
      edgeElasticity: 110,
      gravity: 0.35,
      componentSpacing: 110,
      numIter: 1400,
      nodeDimensionsIncludeLabels: true,
    },
    minZoom: 0.3, maxZoom: 2.5,
    boxSelectionEnabled: false,
    autoungrabify: true,            // nodes aren't draggable in the embed
    userZoomingEnabled: false,      // let the page scroll over the graph
    userPanningEnabled: false,
  });
  cy.fit(undefined, fitPadding);

  if (interactive) {
    let locked = false;
    cy.on("mouseover", "node", (e) => { if (!locked) softHighlight(cy, e.target); });
    cy.on("mouseout", "node", () => { if (!locked) clearFx(cy); });
    cy.on("tap", "node", (e) => {
      locked = true;
      clearFx(cy);
      const id = e.target.id();
      const set = blastRadius(fullIn, id);
      cy.elements().addClass("dim"); cy.edges().addClass("dim-edge");
      const inBlast = (x) => set.has(x) || x === id;
      set.forEach((d) => { const nn = cy.getElementById(d); if (nn.nonempty()) nn.removeClass("dim").addClass("blast-node"); });
      const target = cy.getElementById(id); target.removeClass("dim").addClass("hl-node");
      cy.edges().forEach((ed) => { if (inBlast(ed.source().id()) && inBlast(ed.target().id())) ed.removeClass("dim dim-edge").addClass("blast"); });
      if (onSelect) onSelect(D.byId[id], set.size);
    });
    cy.on("tap", (e) => { if (e.target === cy) { locked = false; clearFx(cy); if (onSelect) onSelect(null, 0); } });
  }
  return cy;
}

/* Restyle an existing instance on theme toggle (mirrors app.js applyTheme). */
export function setGraphTheme(cy, theme) { cy.style(THEMES[theme].style); }
