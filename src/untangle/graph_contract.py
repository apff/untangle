"""The graph contract: ``graph.json`` shape, version, validation, and builder.

This is the seam between the analyzer and the redesigned single-screen webapp
(see ``graph.schema.json`` next to this module — the authoritative JSON Schema).
``build_graph`` is a pure projection of the already-computed analysis (projects +
internal graph + systems) into the frontend's node/edge model; it does not redo
any analysis. ``dependency_report.json`` remains the analyzer's full internal
artifact (mermaid/graphml/markdown/drift still read it); ``graph.json`` is the
trimmed, frontend-facing view.

Semantics (mirrors graph.schema.json): an edge ``source -> target`` means
"source DEPENDS ON target". Dependents of X are X's incoming edges; the blast
radius of X is the transitive incoming closure. The frontend keeps a small
client-side *derive* step (degrees, adjacency, colors, sizes, icons, the
``bundleable`` flag) on top of this contract.
"""

from __future__ import annotations

import re
from fnmatch import fnmatch

GRAPH_VERSION = 1

# Default per-language colors (handoff palette). Overridable via config/languages.yml.
DEFAULT_LANGUAGE_COLORS: dict[str, str] = {
    "docker": "#4aa3df",
    "nodejs": "#5bb98c",
    "python": "#f2c14e",
    "terraform": "#b48ce8",
    "go": "#43c9d6",
    "rust": "#e08a5b",
    "gitlab_ci": "#e0a73a",
}
_DEFAULT_LANG_COLOR = "#8a8580"

# Which ecosystem is the node's *primary* language when it has several. App
# languages rank above infra/CI ecosystems so a "python + docker" repo reads as
# python. Unlisted ecosystems fall back to first-seen order.
_LANGUAGE_PRIORITY = ["python", "nodejs", "go", "rust", "terraform", "docker", "gitlab_ci"]

# Fallback palette for systems referenced by a node but absent from systems.yml
# (keeps every node parented so the frontend layout never orphans one).
_SYNTH_SYSTEM_COLORS = [
    "#e8c84a", "#6c8ebf", "#c678dd", "#56b6c2", "#e06c75", "#98c379",
    "#d19a66", "#7ec8a0", "#abb2bf", "#be5046", "#8a8580", "#5c6370",
]

# Analyzer edge ``type`` -> contract reason ``type`` (package|api|database|
# function|pipeline|config). Unmapped types default to "package".
_REASON_TYPE_MAP: dict[str, str] = {
    "internal_npm_package": "package",
    "git_dependency": "package",
    "docker_registry": "package",
    "terraform": "package",
    "ci_include": "pipeline",
    "ci_component": "pipeline",
    "ci_image": "pipeline",
    "compose_env": "api",
    "service_call": "api",
}

# Node ``type`` (drives the icon) inferred from the repo name. Ported from the
# prototype's TYPE_RULES; first match wins. Falls back to an ecosystem hint,
# then "service".
_TYPE_RULES: list[tuple[re.Pattern, str]] = [
    (re.compile(r"gateway|webhook|(^|-)api(-|$)|introspect|router"), "api"),
    (re.compile(r"warehouse|dbt|registry|kafka|ingest|rollup|backfill|schema"), "database"),
    (re.compile(r"ui$|web|portal|site|console|dash|gallery|pages|docs|status|blog|checkout"), "frontend"),
    (re.compile(r"lib|sdk|components|rules|models|core|pymage"), "library"),
    (re.compile(r"docker|image|cdn|network|vm|dns|mesh|hetzner|cloudflare|asset"), "infra"),
    (re.compile(r"config|flags|loader|vault"), "config"),
    (re.compile(r"auth|lock"), "auth"),
    (re.compile(r"(^|-)ci(-|$)|pipeline"), "pipeline"),
    (re.compile(r"bot|runner|cleaner|scanner|archiver|gen|sync|baker|encoder|thumbnailer|watermarker|exporter|mailer|printer|lint|tool"), "tool"),
]
_ECOSYSTEM_TYPE_HINT = {"terraform": "infra", "docker": "container", "gitlab_ci": "pipeline"}

_VALID_KINDS = {"hub", "anchor", "repo"}
_VALID_NODE_TYPES = {
    "database", "api", "library", "service", "tool", "config",
    "frontend", "infra", "container", "auth", "pipeline",
}
_VALID_REASON_TYPES = {"package", "api", "database", "function", "pipeline", "config"}


def _group_of(path: str) -> str:
    """Top-level group of a repo path (``events/calendar`` -> ``events``)."""
    return path.split("/")[0] if "/" in path else ""


def _parent_group(path: str) -> str:
    """Everything but the last path segment (``a/b/c`` -> ``a/b``)."""
    return path.rsplit("/", 1)[0] if "/" in path else ""


def _primary_language(ecosystems: list[str]) -> str:
    if not ecosystems:
        return "none"
    for lang in _LANGUAGE_PRIORITY:
        if lang in ecosystems:
            return lang
    return ecosystems[0]


def _infer_type(name: str, ecosystems: list[str]) -> str:
    lname = name.lower()
    for pattern, node_type in _TYPE_RULES:
        if pattern.search(lname):
            return node_type
    for eco in ecosystems:
        if eco in _ECOSYSTEM_TYPE_HINT:
            return _ECOSYSTEM_TYPE_HINT[eco]
    return "service"


def _is_shared(path: str, patterns: list[str]) -> bool:
    return any(fnmatch(path, pat) for pat in patterns)


def build_graph(
    *,
    projects: list[dict],
    internal_graph: dict,
    systems: dict[str, dict],
    generated_at: str,
    shared_cfg: dict | None = None,
    palette: dict[str, str] | None = None,
    app_version: str = "",
    latest_version: str | None = None,
    latest_version_url: str | None = None,
    version: int = GRAPH_VERSION,
) -> dict:
    """Project the analysis into the frontend graph contract (graph.schema.json).

    - ``projects``        per-repo analysis results (path, name, ecosystems, web_url, ...).
    - ``internal_graph``  ``{"nodes": [...], "edges": [{"from","to","type","detail"}]}``.
    - ``systems``         id -> ``{"name","groups","color",...}`` (config or synthesized).
    - ``shared_cfg``      ``{"include": [...glob], "exclude": [...glob]}`` override lists.
    - ``palette``         language id -> hex color (merged over the defaults).
    - ``app_version``     the Untangle release that produced this graph (shown in the footer).
    - ``latest_version``  newest release available (from the GitHub check), or None;
      with ``latest_version_url`` it drives the footer's "update available" link.
    """
    shared_cfg = shared_cfg or {}
    include = list(shared_cfg.get("include", []) or [])
    exclude = list(shared_cfg.get("exclude", []) or [])
    colors = {**DEFAULT_LANGUAGE_COLORS, **(palette or {})}

    node_ids = {p["path"] for p in projects}

    # group -> system id (a group may appear under at most one system).
    group_to_system: dict[str, str] = {}
    for sys_id, sys in systems.items():
        for group in sys.get("groups", []):
            group_to_system[group] = sys_id

    def base_system(path: str) -> str:
        """System a repo belongs to before shared-hub reclassification."""
        sid = group_to_system.get(_group_of(path))
        if sid:
            return sid
        # Unmapped group: keep it stable and non-empty so the node stays parented.
        return _group_of(path) or "ungrouped"

    # Dependents (incoming edges) and the base systems they come from, used to
    # decide whether a node is an org-wide hub.
    dependents: dict[str, set[str]] = {pid: set() for pid in node_ids}
    for e in internal_graph.get("edges", []):
        src, tgt = e["from"], e["to"]
        if src in node_ids and tgt in node_ids and src != tgt:
            dependents[tgt].add(src)

    def classify_kind(path: str) -> str:
        if _is_shared(path, exclude):
            deps = dependents.get(path, set())
            return "anchor" if deps else "repo"
        if _is_shared(path, include):
            return "hub"
        deps = dependents.get(path, set())
        if not deps:
            return "repo"
        dep_systems = {base_system(d) for d in deps}
        if len(dep_systems) >= 2:
            return "hub"
        return "anchor"

    # --- nodes ---
    nodes = []
    used_systems: set[str] = set()
    used_languages: list[str] = []
    for proj in projects:
        path = proj["path"]
        ecosystems = proj.get("ecosystems", []) or []
        kind = classify_kind(path)
        system = "shared" if kind == "hub" else base_system(path)
        if system != "shared":
            used_systems.add(system)
        language = _primary_language(ecosystems)
        if language not in used_languages:
            used_languages.append(language)
        nodes.append({
            "id": path,
            "label": path.split("/")[-1],
            "system": system,
            "language": language,
            "kind": kind,
            "type": _infer_type(proj.get("name", "") or path.split("/")[-1], ecosystems),
            "group": _parent_group(path),
            "repoPath": path,
            "sourceUrl": proj.get("web_url", "") or "",
            "description": proj.get("description") or None,
            "lastCommit": proj.get("last_activity_at"),
        })

    # --- systems[] (only those actually used; synthesize colors for unmapped) ---
    out_systems = []
    for i, sid in enumerate(sorted(used_systems)):
        sys = systems.get(sid)
        if sys:
            out_systems.append({"id": sid, "label": sys.get("name", sid), "color": sys.get("color", _DEFAULT_LANG_COLOR)})
        else:
            label = sid.replace("-", " ").replace("_", " ").title()
            out_systems.append({"id": sid, "label": label, "color": _SYNTH_SYSTEM_COLORS[i % len(_SYNTH_SYSTEM_COLORS)]})

    # --- languages[] (only those actually used) ---
    out_languages = [
        {"id": lid, "label": lid, "color": colors.get(lid, _DEFAULT_LANG_COLOR)}
        for lid in used_languages
    ]

    # --- edges[] (collapse parallel analyzer edges into one with reasons[]) ---
    grouped: dict[tuple[str, str], list[dict]] = {}
    order: list[tuple[str, str]] = []
    for e in internal_graph.get("edges", []):
        src, tgt = e["from"], e["to"]
        if src not in node_ids or tgt not in node_ids or src == tgt:
            continue
        key = (src, tgt)
        if key not in grouped:
            grouped[key] = []
            order.append(key)
        grouped[key].append(e)

    edges = []
    for src, tgt in order:
        reasons = []
        seen = set()
        for e in grouped[(src, tgt)]:
            rtype = _REASON_TYPE_MAP.get(e.get("type", ""), "package")
            detail = e.get("detail", "") or e.get("type", "")
            sig = (rtype, detail)
            if sig in seen:
                continue
            seen.add(sig)
            reasons.append({"type": rtype, "detail": detail})
        edges.append({"source": src, "target": tgt, "reasons": reasons})

    return {
        "version": version,
        "appVersion": app_version,
        "latestVersion": latest_version,
        "latestVersionUrl": latest_version_url,
        "generatedAt": generated_at,
        "languages": out_languages,
        "systems": out_systems,
        "nodes": nodes,
        "edges": edges,
    }


def validate_graph(graph: dict) -> None:
    """Assert ``graph`` matches graph.schema.json's shape; raise ValueError if not.

    Light, dependency-free validation (top-level keys + per-item required fields
    + enum membership) — enough to catch a malformed builder change before the
    file ships to the frontend.
    """
    problems: list[str] = []
    top = {
        "version": int,
        "generatedAt": str,
        "languages": list,
        "systems": list,
        "nodes": list,
        "edges": list,
    }
    for key, expected in top.items():
        if key not in graph:
            problems.append(f"missing key: {key}")
        elif not isinstance(graph[key], expected):
            problems.append(f"{key}: expected {expected.__name__}, got {type(graph[key]).__name__}")
    if problems:
        raise ValueError("graph failed schema validation: " + "; ".join(problems))

    lang_ids = {lang.get("id") for lang in graph["languages"]}
    system_ids = {s.get("id") for s in graph["systems"]} | {"shared"}
    node_ids = set()

    for item, item_fields in (("languages", ("id", "label", "color")), ("systems", ("id", "label", "color"))):
        for entry in graph[item]:
            for f in item_fields:
                if f not in entry:
                    problems.append(f"{item}[].{f} missing in {entry!r}")

    for n in graph["nodes"]:
        for f in ("id", "label", "system", "language", "kind", "type"):
            if f not in n:
                problems.append(f"node missing {f}: {n.get('id', n)!r}")
        node_ids.add(n.get("id"))
        if n.get("kind") not in _VALID_KINDS:
            problems.append(f"node {n.get('id')!r}: bad kind {n.get('kind')!r}")
        if n.get("type") not in _VALID_NODE_TYPES:
            problems.append(f"node {n.get('id')!r}: bad type {n.get('type')!r}")
        if n.get("language") not in lang_ids:
            problems.append(f"node {n.get('id')!r}: language {n.get('language')!r} not in languages[]")
        if n.get("system") not in system_ids:
            problems.append(f"node {n.get('id')!r}: system {n.get('system')!r} not in systems[]")

    for e in graph["edges"]:
        for f in ("source", "target"):
            if f not in e:
                problems.append(f"edge missing {f}: {e!r}")
        if e.get("source") not in node_ids:
            problems.append(f"edge source {e.get('source')!r} is not a node")
        if e.get("target") not in node_ids:
            problems.append(f"edge target {e.get('target')!r} is not a node")
        for r in e.get("reasons", []):
            if r.get("type") not in _VALID_REASON_TYPES:
                problems.append(f"edge {e.get('source')}->{e.get('target')}: bad reason type {r.get('type')!r}")

    if problems:
        raise ValueError("graph failed schema validation: " + "; ".join(problems))
