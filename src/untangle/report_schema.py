"""The report contract: ``dependency_report.json`` shape, version, and validation.

This JSON is the interface between the analyzer and the webapp (and any other
consumer). Bump ``SCHEMA_VERSION`` on breaking shape changes so consumers can
detect mismatches instead of failing obscurely.

The TypedDicts document the shape for contributors and type-checkers; runtime
validation is deliberately light (top-level keys + types only) to avoid a
schema-library dependency for what is an internally-produced document.
"""

from __future__ import annotations

from typing import TypedDict

SCHEMA_VERSION = 1


class ProjectDependencies(TypedDict):
    manifest: dict[str, list]   # section -> entries ({"name","raw"|"version","source"} | {"image","source"})
    internal: list[dict]        # {"target","type","source", ...}
    undocumented: list[dict]    # {"url","type","file","line"[, "env_key"]}


class Project(TypedDict, total=False):
    path: str                   # unique id, e.g. "group/repo"
    name: str
    id: int | None              # origin-native id (GitLab); absent for other origins
    web_url: str
    branch: str
    description: str
    topics: list[str]
    last_activity_at: str | None
    ecosystems: list[str]
    dependencies: ProjectDependencies
    shared_networks: list[str]
    databases: list[dict]       # {"type","source"}


class GraphEdge(TypedDict):
    type: str
    detail: str                 # human-readable evidence (URL, raw spec, ...)


class InternalGraph(TypedDict):
    nodes: list[dict]           # {"id","name","group","ecosystems"}
    edges: list[dict]           # {"from","to","type","detail"}


class SystemGraph(TypedDict):
    edges: list[dict]           # {"from","to","count","types": {type: count}}


class DependencyReport(TypedDict, total=False):
    schema_version: int
    title: str
    generated_at: str           # UTC ISO-8601; the webapp's staleness check
    systems: dict[str, dict]    # system id -> {"name","groups","tier","color",...}
    projects: list[Project]
    internal_graph: InternalGraph
    system_graph: SystemGraph
    shared_infrastructure: dict
    config_drift: dict
    route_registry_summary: dict
    summary: dict


_TOP_LEVEL: dict[str, type | tuple[type, ...]] = {
    "schema_version": int,
    "title": str,
    "generated_at": str,
    "systems": dict,
    "projects": list,
    "internal_graph": dict,
    "system_graph": dict,
    "shared_infrastructure": dict,
    "config_drift": dict,
    "route_registry_summary": dict,
    "summary": dict,
}


def validate_report(report: dict) -> None:
    """Assert the report has the documented top-level shape; raise ValueError if not."""
    problems = []
    for key, expected in _TOP_LEVEL.items():
        if key not in report:
            problems.append(f"missing key: {key}")
        elif not isinstance(report[key], expected):
            problems.append(f"{key}: expected {expected}, got {type(report[key]).__name__}")
    for graph_key in ("nodes", "edges"):
        if graph_key not in report.get("internal_graph", {}):
            problems.append(f"internal_graph.{graph_key} missing")
    if problems:
        raise ValueError("report failed schema validation: " + "; ".join(problems))
