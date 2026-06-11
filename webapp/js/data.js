// Fetches graph.json (the analyzer's contract — see src/untangle/graph.schema.json)
// and runs the client-side DERIVE step the design handoff says to keep: degrees,
// the bundleable flag, language/system lookups, and relative "last commit" days.
// The visual precompute (colors, sizes, icons, adjacency) stays in app.js. The
// result mirrors the prototype's `window.UNTANGLE` model so app.js consumes it
// unchanged.

export class ReportLoadError extends Error {}

const DEFAULT_LANG_COLOR = "#8a8580";

function daysSince(iso) {
  if (!iso) return null;
  const t = new Date(iso);
  if (isNaN(t.getTime())) return null;
  return Math.max(0, Math.floor((Date.now() - t.getTime()) / 86400000));
}

// Fetches graph.json once; throws ReportLoadError on network/parse failure so the
// app can show a visible banner instead of a silent blank screen.
export async function loadGraph() {
  let resp;
  try {
    resp = await fetch("data/graph.json", { cache: "no-cache" });
  } catch (err) {
    throw new ReportLoadError(`Network error fetching the graph: ${err.message}`);
  }
  if (!resp.ok) throw new ReportLoadError(`Graph fetch failed: HTTP ${resp.status}`);
  try {
    return await resp.json();
  } catch {
    throw new ReportLoadError("graph.json is not valid JSON — analyzer output may be corrupted.");
  }
}

// Transform the raw contract into the in-memory model app.js expects. Pure given
// `graph` + the current clock (used only for relative last-commit days).
export function deriveModel(graph) {
  const LANGS = {};
  for (const l of graph.languages || []) {
    LANGS[l.id] = { color: l.color || DEFAULT_LANG_COLOR, label: l.label || l.id };
  }
  // Ensure every node language resolves even if it slipped past the contract.
  const ensureLang = (id) => { if (!LANGS[id]) LANGS[id] = { color: DEFAULT_LANG_COLOR, label: id }; };

  const SYSTEMS = (graph.systems || []).map((s) => ({ id: s.id, label: s.label || s.id, color: s.color || DEFAULT_LANG_COLOR }));
  const systemById = SYSTEMS.reduce((m, s) => ((m[s.id] = s), m), {});

  const nodes = (graph.nodes || []).map((n) => {
    ensureLang(n.language);
    return {
      id: n.id,
      label: n.label,
      kind: n.kind,
      system: n.system,
      lang: n.language,
      type: n.type,
      group: n.group || "",
      repoPath: n.repoPath || n.id,
      url: n.sourceUrl || "",
      description: n.description ?? null,
      lastCommit: n.lastCommit || null,
      lastDays: daysSince(n.lastCommit),
      indeg: 0,
      outdeg: 0,
      bundleable: false,
    };
  });
  const byId = nodes.reduce((m, n) => ((m[n.id] = n), m), {});

  const edges = (graph.edges || [])
    .filter((e) => byId[e.source] && byId[e.target] && e.source !== e.target)
    .map((e) => ({
      id: "e:" + e.source + "->" + e.target,
      source: e.source,
      target: e.target,
      kind: "depends",
      reasons: e.reasons || [],
    }));
  const edgeById = edges.reduce((m, e) => ((m[e.id] = e), m), {});

  // Degrees, then the bundleable rule (leaf consumer with no dependents).
  edges.forEach((e) => { byId[e.source].outdeg++; byId[e.target].indeg++; });
  nodes.forEach((n) => { n.bundleable = n.kind === "repo" && n.indeg === 0 && n.system !== "shared"; });

  // Shared-cluster components (rendered in the central "Shared Components" parent).
  const HUBS = nodes.filter((n) => n.system === "shared").map((n) => ({ id: n.id, label: n.label, lang: n.lang }));

  return {
    LANGS, SYSTEMS, HUBS,
    nodes, edges, byId, edgeById, systemById,
    generatedAt: graph.generatedAt || null,
    version: graph.version,
    appVersion: graph.appVersion || null,
    latestVersion: graph.latestVersion || null,
    latestVersionUrl: graph.latestVersionUrl || null,
  };
}
