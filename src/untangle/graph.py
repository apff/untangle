"""Build the internal dependency graph and roll-ups from per-project results."""

from __future__ import annotations

from .patterns import DetectionPatterns


def build_internal_graph(
    projects: list[dict], known_projects: set[str], patterns: DetectionPatterns
) -> dict:
    nodes = []
    edges = []
    project_slugs = {p["path"].split("/")[-1].lower(): p["path"] for p in projects}

    for proj in projects:
        nodes.append({
            "id": proj["path"],
            "name": proj["name"],
            "group": proj["path"].split("/")[0] if "/" in proj["path"] else "",
            "ecosystems": proj["ecosystems"],
        })

        for dep in proj["dependencies"]["internal"]:
            target = dep["target"]
            # Fast-path: target is already an exact known repo path
            if target in known_projects and target != proj["path"]:
                resolved_target = target
            else:
                resolved_target = _resolve_target(target, known_projects, project_slugs, patterns)
            if resolved_target and resolved_target != proj["path"]:
                edges.append({
                    "from": proj["path"],
                    "to": resolved_target,
                    "type": dep["type"],
                    "detail": dep.get("detail") or target,
                })

    unique_edges = []
    seen_edges = set()
    for e in edges:
        key = (e["from"], e["to"], e["type"])
        if key not in seen_edges:
            seen_edges.add(key)
            unique_edges.append(e)

    return {"nodes": nodes, "edges": unique_edges}


def _resolve_target(
    target: str,
    known_projects: set[str],
    project_slugs: dict[str, str],
    patterns: DetectionPatterns,
) -> str | None:
    target_lower = target.lower().strip()

    for proj in known_projects:
        if proj.lower() in target_lower:
            return proj

    registry_path = patterns.strip_registry_prefix(target)
    if registry_path:
        if registry_path in known_projects:
            return registry_path
        for proj in known_projects:
            if proj.endswith(registry_path) or registry_path.endswith(proj.split("/")[-1]):
                return proj

    for slug, full_path in project_slugs.items():
        if slug in target_lower and len(slug) > 3:
            return full_path

    return None


def build_shared_infra(projects: list[dict]) -> dict:
    networks: dict[str, list[str]] = {}
    databases: dict[str, list[str]] = {}
    registries: list[str] = []

    for proj in projects:
        for net in proj.get("shared_networks", []):
            networks.setdefault(net, []).append(proj["path"])
        for db in proj.get("databases", []):
            databases.setdefault(db["type"], []).append(proj["path"])
        for dep in proj["dependencies"]["internal"]:
            if dep["type"] == "docker_registry":
                registries.append(dep["target"])

    for db_type in databases:
        databases[db_type] = sorted(set(databases[db_type]))

    return {
        "networks": networks,
        "databases": databases,
        "registry_images": sorted(set(registries)),
    }


def build_system_graph(internal_graph: dict, systems: dict[str, dict]) -> dict:
    """Roll project→project edges up to system→system edges with counts.

    Gives the webapp something meaningful to draw when a system group is
    collapsed: one aggregated edge per (system, system) pair, with the total
    project-edge count and a per-type breakdown.
    """
    group_to_system = {
        group: sys_id for sys_id, sys in systems.items() for group in sys.get("groups", [])
    }
    node_system = {
        node["id"]: group_to_system.get(node.get("group", "")) for node in internal_graph["nodes"]
    }

    aggregated: dict[tuple[str, str], dict] = {}
    for edge in internal_graph["edges"]:
        sys_from = node_system.get(edge["from"])
        sys_to = node_system.get(edge["to"])
        if not sys_from or not sys_to or sys_from == sys_to:
            continue
        agg = aggregated.setdefault(
            (sys_from, sys_to), {"from": sys_from, "to": sys_to, "count": 0, "types": {}}
        )
        agg["count"] += 1
        agg["types"][edge["type"]] = agg["types"].get(edge["type"], 0) + 1

    return {"edges": sorted(aggregated.values(), key=lambda e: (e["from"], e["to"]))}
