"""The graph contract: build_graph projection + validate_graph shape checks."""

from __future__ import annotations

import pytest

from untangle.graph_contract import build_graph, validate_graph

# Three systems; one repo each plus shared infra. ``base`` is depended on by
# repos in two systems (cross-system -> hub); ``events-lib`` only by its own
# system (-> anchor); ``leaf`` has no dependents (-> repo).
SYSTEMS = {
    "infra": {"name": "Infra", "groups": ["infra"], "color": "#e5604d"},
    "events": {"name": "Events", "groups": ["events"], "color": "#5bb98c"},
    "web": {"name": "Web", "groups": ["web"], "color": "#38b6c4"},
}

PROJECTS = [
    {"path": "infra/base", "name": "base", "ecosystems": ["docker"], "web_url": "https://git/infra/base", "description": "Base image", "last_activity_at": "2026-06-01T00:00:00+00:00"},
    {"path": "events/events-lib", "name": "events-lib", "ecosystems": ["python", "docker"], "web_url": "https://git/events/events-lib", "description": None, "last_activity_at": None},
    {"path": "events/consumer", "name": "consumer", "ecosystems": ["python"], "web_url": "", "description": "", "last_activity_at": None},
    {"path": "web/portal", "name": "portal", "ecosystems": ["nodejs"], "web_url": "https://git/web/portal", "description": "Portal", "last_activity_at": None},
    {"path": "events/leaf", "name": "leaf-tool", "ecosystems": ["python"], "web_url": "", "description": None, "last_activity_at": None},
]

INTERNAL_GRAPH = {
    "nodes": [{"id": p["path"], "name": p["name"], "group": p["path"].split("/")[0], "ecosystems": p["ecosystems"]} for p in PROJECTS],
    "edges": [
        # base is depended on from events and web -> cross-system hub
        {"from": "events/consumer", "to": "infra/base", "type": "docker_registry", "detail": "FROM base:1"},
        {"from": "web/portal", "to": "infra/base", "type": "docker_registry", "detail": "FROM base:1"},
        # events-lib depended on only within events -> anchor
        {"from": "events/consumer", "to": "events/events-lib", "type": "internal_npm_package", "detail": "@ev/lib"},
        # two parallel edges consumer->events-lib of different types collapse into one edge, two reasons
        {"from": "events/consumer", "to": "events/events-lib", "type": "service_call", "detail": "GET /lib/v1"},
    ],
}


def _build(**overrides):
    kwargs = dict(
        projects=PROJECTS,
        internal_graph=INTERNAL_GRAPH,
        systems=SYSTEMS,
        generated_at="2026-06-18T00:00:00+00:00",
    )
    kwargs.update(overrides)
    return build_graph(**kwargs)


def _node(graph, path):
    return next(n for n in graph["nodes"] if n["id"] == path)


def test_build_graph_validates_and_has_top_level_shape():
    graph = _build()
    validate_graph(graph)  # must not raise
    assert graph["version"] == 1
    assert graph["generatedAt"] == "2026-06-18T00:00:00+00:00"
    assert {"version", "generatedAt", "languages", "systems", "nodes", "edges"} <= graph.keys()


def test_kind_derivation_repo_anchor_hub():
    graph = _build()
    assert _node(graph, "events/leaf")["kind"] == "repo"          # no dependents
    assert _node(graph, "events/events-lib")["kind"] == "anchor"  # depended on within one system
    base = _node(graph, "infra/base")
    assert base["kind"] == "hub"                                   # cross-system dependents
    assert base["system"] == "shared"                              # hubs move to the shared cluster


def test_shared_include_exclude_overrides_win():
    # include forces a leaf into the shared cluster as a hub
    g_inc = _build(shared_cfg={"include": ["events/leaf"]})
    leaf = _node(g_inc, "events/leaf")
    assert leaf["kind"] == "hub" and leaf["system"] == "shared"

    # exclude keeps a cross-system target out of shared (demoted to anchor)
    g_exc = _build(shared_cfg={"exclude": ["infra/base"]})
    base = _node(g_exc, "infra/base")
    assert base["kind"] == "anchor" and base["system"] == "infra"


def test_edges_collapse_with_mapped_reasons():
    graph = _build()
    lib_edges = [e for e in graph["edges"] if e["source"] == "events/consumer" and e["target"] == "events/events-lib"]
    assert len(lib_edges) == 1  # two analyzer edges collapsed into one
    reason_types = {r["type"] for r in lib_edges[0]["reasons"]}
    assert reason_types == {"package", "api"}  # npm_package->package, service_call->api

    base_edges = [e for e in graph["edges"] if e["target"] == "infra/base"]
    assert all(r["type"] == "package" for e in base_edges for r in e["reasons"])  # docker_registry->package


def test_language_extraction_and_palette_fallback():
    graph = _build(palette={"python": "#abcabc"})
    lang_ids = {lang["id"]: lang for lang in graph["languages"]}
    # primary language picks the app language over docker for a python+docker repo
    assert _node(graph, "events/events-lib")["language"] == "python"
    assert lang_ids["python"]["color"] == "#abcabc"  # palette override applied
    # docker keeps its default color (only used as a primary by infra/base)
    assert lang_ids["docker"]["color"] == "#4aa3df"


def test_node_metadata_fields():
    graph = _build()
    base = _node(graph, "infra/base")
    assert base["group"] == "infra"
    assert base["repoPath"] == "infra/base"
    assert base["sourceUrl"] == "https://git/infra/base"
    assert base["lastCommit"] == "2026-06-01T00:00:00+00:00"
    assert _node(graph, "events/events-lib")["description"] is None
    assert _node(graph, "events/consumer")["description"] is None  # "" -> None


def test_type_inference():
    graph = _build()
    assert _node(graph, "web/portal")["type"] == "frontend"  # name rule: portal
    assert _node(graph, "events/leaf")["type"] == "tool"      # name rule: tool


def test_unmapped_group_gets_fallback_system():
    projects = PROJECTS + [{"path": "orphans/thing", "name": "thing", "ecosystems": ["go"], "web_url": "", "description": None, "last_activity_at": None}]
    ig = {
        "nodes": INTERNAL_GRAPH["nodes"] + [{"id": "orphans/thing", "name": "thing", "group": "orphans", "ecosystems": ["go"]}],
        "edges": INTERNAL_GRAPH["edges"],
    }
    graph = _build(projects=projects, internal_graph=ig)
    validate_graph(graph)  # node's system must still resolve to a systems[] entry
    assert _node(graph, "orphans/thing")["system"] == "orphans"
    assert any(s["id"] == "orphans" for s in graph["systems"])


def test_version_fields_passthrough():
    graph = _build(app_version="0.1.0", latest_version="0.2.0", latest_version_url="https://x/releases/v0.2.0")
    validate_graph(graph)
    assert graph["appVersion"] == "0.1.0"
    assert graph["latestVersion"] == "0.2.0"
    assert graph["latestVersionUrl"] == "https://x/releases/v0.2.0"
    # defaults when the update check is disabled / unavailable
    bare = _build()
    assert bare["appVersion"] == "" and bare["latestVersion"] is None and bare["latestVersionUrl"] is None


def test_validate_graph_rejects_missing_keys():
    graph = _build()
    with pytest.raises(ValueError, match="nodes"):
        validate_graph({k: v for k, v in graph.items() if k != "nodes"})


def test_validate_graph_rejects_dangling_edge():
    graph = _build()
    graph["edges"].append({"source": "events/consumer", "target": "does/not-exist", "reasons": []})
    with pytest.raises(ValueError, match="not a node"):
        validate_graph(graph)
