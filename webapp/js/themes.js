/* Untangle — Cytoscape stylesheets for the Midnight Refined theme (dark + light).
   Page chrome is themed via a body class in CSS; this module only produces the
   graph stylesheets. Nodes carry precomputed data: color / colorLite / colorDark
   (language), sysColor (owning system), size (diameter), label, icon. */

const fontSans = '"Space Grotesk", system-ui, sans-serif';
const fontMono = '"JetBrains Mono", ui-monospace, monospace';

const baseEdge = (extra) => Object.assign({
  "curve-style": "bezier",
  "target-arrow-shape": "triangle",
  "arrow-scale": 0.85,
  width: 1.4,
  "target-distance-from-node": 3,
  "source-endpoint": "outside-to-node",
  "target-endpoint": "outside-to-node",
}, extra);

/* ============================ MIDNIGHT (dark) ============================ */
const midnight = [
  { selector: "node", style: {
      width: "data(size)", height: "data(size)", shape: "ellipse",
      "background-color": "data(color)",
      "background-fill": "radial-gradient",
      "background-gradient-stop-colors": "data(gradStops)",
      "background-gradient-stop-positions": "0 55 100",
      "border-width": 1.5, "border-color": "data(colorLite)", "border-opacity": 0.5,
      label: "data(label)", "font-family": fontMono, "font-size": 12,
      color: "#aeb6c0", "text-valign": "bottom", "text-margin-y": 7,
      "text-halign": "center", "min-zoomed-font-size": 7,
      "text-background-color": "#0d0f12", "text-background-opacity": 0.55,
      "text-background-padding": 3, "text-background-shape": "roundrectangle",
      "z-index": 10,
  }},
  { selector: "node[icon]", style: {
      "background-image": "data(icon)", "background-width": "44%", "background-height": "44%",
      "background-position-x": "50%", "background-position-y": "50%", "background-clip": "none",
      "background-image-opacity": 0.9,
  }},
  { selector: "node.hub", style: {
      "border-width": 2, "border-color": "#e9d8a6", "border-opacity": 0.7,
      color: "#f0e6cf", "font-family": fontSans, "font-size": 13, "font-weight": 600,
      "z-index": 20,
  }},
  { selector: "node.bundle", style: {
      shape: "ellipse", width: "data(size)", height: "data(size)",
      "background-fill": "solid", "background-color": "#161b23", "background-opacity": 0.95,
      "border-width": 2, "border-color": "data(sysColor)", "border-style": "dashed",
      "border-opacity": 0.85, label: "data(label)", "text-wrap": "wrap", "text-valign": "center",
      "text-margin-y": 0, color: "#dce2e9", "font-family": fontSans, "font-size": 15,
      "font-weight": 700, "text-background-opacity": 0, "z-index": 15,
  }},
  { selector: "$node > node", style: {} },
  { selector: ":parent", style: {
      "background-opacity": 0, "border-width": 0,
      shape: "round-rectangle", padding: 36,
      label: "data(label)", "font-family": fontSans, "font-size": 21, "font-weight": 700,
      color: "data(sysColor)", "text-valign": "top", "text-halign": "center",
      "text-margin-y": -18, "text-background-opacity": 0, "text-opacity": 0, "z-index": 1,
  }},
  { selector: ":parent.sys-active", style: {
      "border-width": 2, "border-style": "dashed", "border-color": "data(sysColor)", "border-opacity": 0.6,
      "border-dash-pattern": [6, 12],
  }},
  { selector: "node.collapsedSys", style: {
      shape: "ellipse", "text-valign": "center", "text-halign": "center", "text-margin-y": 0,
  }},
  { selector: "edge", style: baseEdge({
      "line-color": "#e7c66a", "line-opacity": 0.22,
      "target-arrow-color": "#9c8748", "z-index": 2,
  })},
  { selector: "edge.hl", style: {
      "line-color": "#ffd76a", "line-opacity": 0.95, width: 2.6,
      "target-arrow-color": "#ffd76a", "z-index": 30,
  }},
  { selector: "edge.blast", style: {
      "line-color": "#ff7a59", "line-opacity": 0.95, width: 2.6,
      "target-arrow-color": "#ff7a59", "z-index": 30,
  }},
  { selector: ".hl-node", style: {
      "border-width": 2.5, "border-color": "#ffd76a", "border-opacity": 1,
  }},
  { selector: ".blast-node", style: {
      "border-width": 2.5, "border-color": "#ff7a59", "border-opacity": 1,
  }},
  { selector: ".dim", style: { opacity: 0.12 } },
  { selector: ".dim-edge", style: { opacity: 0.05 } },
  { selector: "node:selected", style: {
      "border-width": 3, "border-color": "#ffffff", "border-opacity": 0.9,
  }},
];

/* ===================== MIDNIGHT — LIGHT VARIANT ======================== */
const midnightLight = [
  { selector: "node", style: {
      width: "data(size)", height: "data(size)", shape: "ellipse",
      "background-color": "data(color)",
      "background-fill": "radial-gradient",
      "background-gradient-stop-colors": "data(gradStops)",
      "background-gradient-stop-positions": "0 55 100",
      "border-width": 1.5, "border-color": "data(colorDark)", "border-opacity": 0.55,
      label: "data(label)", "font-family": fontMono, "font-size": 12,
      color: "#3a4452", "text-valign": "bottom", "text-margin-y": 7,
      "text-halign": "center", "min-zoomed-font-size": 7,
      "text-background-color": "#ffffff", "text-background-opacity": 0.7,
      "text-background-padding": 3, "text-background-shape": "roundrectangle",
      "z-index": 10,
  }},
  { selector: "node[icon]", style: {
      "background-image": "data(icon)", "background-width": "44%", "background-height": "44%",
      "background-position-x": "50%", "background-position-y": "50%", "background-clip": "none",
      "background-image-opacity": 0.9,
  }},
  { selector: "node.hub", style: {
      "border-width": 2, "border-color": "#b8740a", "border-opacity": 0.85,
      color: "#5a3d00", "font-family": fontSans, "font-size": 13, "font-weight": 600,
      "z-index": 20,
  }},
  { selector: "node.bundle", style: {
      shape: "ellipse", width: "data(size)", height: "data(size)",
      "background-fill": "solid", "background-color": "#eef1f4", "background-opacity": 1,
      "border-width": 2, "border-color": "data(sysColor)", "border-style": "dashed",
      "border-opacity": 0.85, label: "data(label)", "text-wrap": "wrap", "text-valign": "center",
      "text-margin-y": 0, color: "#3a4654", "font-family": fontSans, "font-size": 15,
      "font-weight": 700, "text-background-opacity": 0, "z-index": 15,
  }},
  { selector: "$node > node", style: {} },
  { selector: ":parent", style: {
      "background-opacity": 0, "border-width": 0,
      shape: "round-rectangle", padding: 36,
      label: "data(label)", "font-family": fontSans, "font-size": 21, "font-weight": 700,
      color: "data(sysColor)", "text-valign": "top", "text-halign": "center",
      "text-margin-y": -18, "text-background-opacity": 0, "text-opacity": 0, "z-index": 1,
  }},
  { selector: ":parent.sys-active", style: {
      "border-width": 2, "border-style": "dashed", "border-color": "data(sysColor)", "border-opacity": 0.6,
      "border-dash-pattern": [6, 12],
  }},
  { selector: "node.collapsedSys", style: {
      shape: "ellipse", "text-valign": "center", "text-halign": "center", "text-margin-y": 0,
  }},
  { selector: "edge", style: baseEdge({
      "line-color": "#aeb4bd", "line-opacity": 0.65,
      "target-arrow-color": "#9aa1ab", "z-index": 2,
  })},
  { selector: "edge.hl", style: {
      "line-color": "#b8740a", "line-opacity": 1, width: 2.6,
      "target-arrow-color": "#b8740a", "z-index": 30,
  }},
  { selector: "edge.blast", style: {
      "line-color": "#e5604d", "line-opacity": 1, width: 2.6,
      "target-arrow-color": "#e5604d", "z-index": 30,
  }},
  { selector: ".hl-node", style: {
      "border-width": 2.5, "border-color": "#b8740a", "border-opacity": 1,
  }},
  { selector: ".blast-node", style: {
      "border-width": 2.5, "border-color": "#e5604d", "border-opacity": 1,
  }},
  { selector: ".dim", style: { opacity: 0.15 } },
  { selector: ".dim-edge", style: { opacity: 0.08 } },
  { selector: "node:selected", style: {
      "border-width": 3, "border-color": "#1b2230", "border-opacity": 0.9,
  }},
];

export const THEMES = {
  midnight: { id: "midnight", label: "Midnight Refined", style: midnight },
  "midnight-light": { id: "midnight-light", label: "Midnight Light", style: midnightLight },
};
