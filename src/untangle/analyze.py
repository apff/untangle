"""Analyze cloned repos and assemble ``dependency_report.json``.

Thin orchestrator: runs every registered ecosystem parser (``parsers/``) over
each repo, scans for undocumented internal URLs (``scanner``), resolves them to
owning repos via the route registry (``routes``), builds the dependency graphs
(``graph``), checks config drift (``drift``), and writes the validated report
(``report_schema``).
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from pathlib import Path

from . import __version__, scanner
from .config import Settings
from .drift import detect_config_drift, warn_config_drift
from .graph import build_internal_graph, build_shared_infra, build_system_graph
from .graph_contract import build_graph, validate_graph
from .parsers import PARSERS, ParseResult
from .patterns import DetectionPatterns
from .report_schema import SCHEMA_VERSION, validate_report
from .routes import (
    build_prefix_index,
    build_route_registry,
    normalize_url_to_path,
    resolve_url_to_repo,
)
from .static_config import (
    load_app_config,
    load_language_palette,
    load_prefixes,
    load_shared_config,
    load_systems,
    load_update_check_config,
)
from .updates import latest_release

logger = logging.getLogger(__name__)

# Palette for synthesized systems when no systems.yml is configured.
_SYNTH_COLORS = [
    "#e8c84a", "#6c8ebf", "#c678dd", "#56b6c2", "#e06c75", "#98c379",
    "#d19a66", "#7ec8a0", "#abb2bf", "#be5046", "#8a8580", "#5c6370",
]


def load_manifest(settings: Settings) -> list[dict]:
    if not settings.manifest_path.exists():
        raise SystemExit(
            f"ERROR: {settings.manifest_path} not found. Run `untangle clone` first."
        )
    return json.loads(settings.manifest_path.read_text())


def analyze_project(
    repo_dir: Path, project: dict, known_projects: set[str], patterns: DetectionPatterns
) -> dict:
    result: dict = {
        "path": project["path"],
        "name": project["name"],
        "id": project.get("id"),
        "web_url": project["web_url"],
        "branch": project["branch"],
        "description": project.get("description", ""),
        "topics": project.get("topics", []),
        "last_activity_at": project.get("last_activity_at"),
        "ecosystems": [],
        "dependencies": {"manifest": {}, "internal": [], "undocumented": []},
        "shared_networks": [],
        "databases": [],
    }

    # Every registered ecosystem parser, merged in registry order.
    merged = ParseResult()
    for parser in PARSERS:
        merged.merge(parser.parse(repo_dir, patterns))
    result["ecosystems"] = merged.ecosystems
    result["dependencies"]["manifest"] = merged.manifest
    result["dependencies"]["internal"] = merged.internal
    result["shared_networks"] = merged.shared_networks

    # Internal references hiding inside the parsed manifests (scoped npm
    # packages, git deps on internal hosts, internal registry images).
    result["dependencies"]["internal"].extend(
        scanner.manifest_internal_refs(merged.manifest, patterns)
    )

    # Undocumented: internal URLs in source code and env templates.
    all_undoc = []
    for h in scanner.scan_source_for_urls(repo_dir, patterns):
        all_undoc.append({
            "url": h["url"],
            "type": scanner.classify_internal_url(h["url"], known_projects, patterns),
            "file": h["file"],
            "line": h["line"],
        })
    for h in scanner.scan_env_files(repo_dir, patterns):
        all_undoc.append({
            "url": h["url"],
            "type": scanner.classify_internal_url(h["url"], known_projects, patterns),
            "file": h["file"],
            "line": h["line"],
            "env_key": h.get("key", ""),
        })
    result["dependencies"]["undocumented"] = scanner.deduplicate_urls(all_undoc)

    result["databases"] = scanner.detect_databases(repo_dir)
    result["shared_networks"] = list(set(result["shared_networks"]))

    return result


def synthesize_systems(projects: list[dict]) -> dict[str, dict]:
    """One system per top-level repo group — the zero-config fallback.

    Keeps the webapp's grouping views working when no ``systems.yml`` exists;
    deployments can graduate to a hand-written one later.
    """
    groups = sorted({p["path"].split("/")[0] for p in projects if "/" in p["path"]})
    ungrouped = [p for p in projects if "/" not in p["path"]]
    systems = {}
    for i, group in enumerate(groups):
        systems[group] = {
            "name": group.replace("-", " ").replace("_", " ").title(),
            "groups": [group],
            "description": "",
            "tier": "primary",
            "color": _SYNTH_COLORS[i % len(_SYNTH_COLORS)],
        }
    if ungrouped:
        systems["ungrouped"] = {
            "name": "Ungrouped",
            "groups": [""],
            "description": "Repositories without a group prefix",
            "tier": "secondary",
            "color": _SYNTH_COLORS[len(groups) % len(_SYNTH_COLORS)],
        }
    return systems


def _resolve_undocumented_refs(projects: list[dict], settings: Settings, patterns: DetectionPatterns, prefixes: dict[str, str]) -> dict:
    """Route-registry pass: turn undocumented URL refs into service-call edges.

    Opt-in only. Path-based URL→repo inference is a best-effort heuristic that
    mis-attributes shared-gateway / path-routed URLs (and infra URLs like the git
    forge's own API), so it stays off unless ``detection.infer_service_calls`` is
    set. When disabled, undocumented refs are left untouched and no edges are made.
    """
    if not patterns.infer_service_calls:
        logger.info(
            "\nService-call inference disabled (detection.infer_service_calls is off) — "
            "leaving undocumented URL refs unresolved."
        )
        return {
            "enabled": False,
            "repos_with_routes": 0,
            "total_routes_discovered": 0,
            "resolved_service_calls": 0,
            "remaining_undocumented": sum(
                len(p["dependencies"].get("undocumented", [])) for p in projects
            ),
        }

    logger.info("\nBuilding route registry from all repos...")
    repo_dirs = {p["path"]: settings.repos_dir / p["path"] for p in projects}
    registry = build_route_registry(repo_dirs)
    prefix_index = build_prefix_index(registry, prefixes)
    logger.info("  routes discovered: %d across %d repos", sum(len(r) for r in registry.values()), len(registry))
    logger.info("  prefix index size: %d", len(prefix_index))

    resolved_count = 0
    unresolved_count = 0
    internal_hosts = patterns.internal_domains
    for proj in projects:
        new_internal = []
        new_undocumented = []
        seen_edges = set()
        for ref in proj["dependencies"].get("undocumented", []):
            # Infra references (the git forge's own API/admin, container registries)
            # are not inter-service calls — classify_internal_url already tagged them.
            if ref.get("type") in ("git_host", "docker_registry"):
                new_undocumented.append(ref)
                continue
            url = ref.get("url", "")
            target_repo = resolve_url_to_repo(url, prefix_index, internal_hosts)
            if target_repo and target_repo != proj["path"]:
                edge_key = (target_repo, normalize_url_to_path(url, internal_hosts) or "")
                if edge_key in seen_edges:
                    continue
                seen_edges.add(edge_key)
                new_internal.append({
                    "target": target_repo,
                    "type": "service_call",
                    "detail": url,
                    "source": f"{ref.get('file', '')}:{ref.get('line', '?')}",
                })
                resolved_count += 1
            else:
                new_undocumented.append(ref)
                unresolved_count += 1
        proj["dependencies"]["internal"].extend(new_internal)
        proj["dependencies"]["undocumented"] = new_undocumented

    logger.info("  resolved service-call edges: %d", resolved_count)
    logger.info("  remaining undocumented refs: %d\n", unresolved_count)

    return {
        "enabled": True,
        "repos_with_routes": len(registry),
        "total_routes_discovered": sum(len(r) for r in registry.values()),
        "resolved_service_calls": resolved_count,
        "remaining_undocumented": unresolved_count,
    }


def run(settings: Settings, patterns: DetectionPatterns) -> int:
    manifest = load_manifest(settings)
    known_projects = {p["path"] for p in manifest}
    logger.info("Analyzing %d projects...\n", len(manifest))

    projects = []
    for project in manifest:
        repo_dir = settings.repos_dir / project["path"]
        if not repo_dir.exists():
            logger.info("[SKIP] %s — directory not found", project["path"])
            continue
        logger.info("[ANALYZE] %s", project["path"])
        result = analyze_project(repo_dir, project, known_projects, patterns)
        projects.append(result)

        n_manifest = sum(
            len(v) if isinstance(v, list) else 0
            for v in result["dependencies"]["manifest"].values()
        )
        logger.info("  ecosystems: %s", ", ".join(result["ecosystems"]) or "none")
        logger.info(
            "  manifest deps: %d, internal: %d, undocumented refs: %d",
            n_manifest,
            len(result["dependencies"]["internal"]),
            len(result["dependencies"]["undocumented"]),
        )

    prefixes = load_prefixes()
    route_summary = _resolve_undocumented_refs(projects, settings, patterns, prefixes)

    internal_graph = build_internal_graph(projects, known_projects, patterns)
    shared_infra = build_shared_infra(projects)
    systems = load_systems() or synthesize_systems(projects)
    config_drift = detect_config_drift(known_projects, systems, prefixes)

    app_config = load_app_config()
    report = {
        "schema_version": SCHEMA_VERSION,
        "title": app_config.get("title") or "Untangle",
        # The webapp flags stale data using this; keep it UTC + ISO-8601.
        "generated_at": datetime.now(UTC).isoformat(),
        # System groupings are the single source of truth here (config/systems.yml,
        # or synthesized from repo groups); the webapp reads them from the report.
        "systems": systems,
        "projects": projects,
        "internal_graph": internal_graph,
        "system_graph": build_system_graph(internal_graph, systems),
        "shared_infrastructure": shared_infra,
        "config_drift": config_drift,
        "route_registry_summary": route_summary,
        "summary": {
            "generated_at": datetime.now(UTC).isoformat(),
            "total_projects": len(projects),
            "total_internal_edges": len(internal_graph["edges"]),
            "ecosystems": {},
            "projects_with_undocumented_refs": sum(
                1 for p in projects if p["dependencies"]["undocumented"]
            ),
        },
    }
    for p in projects:
        for eco in p["ecosystems"]:
            report["summary"]["ecosystems"][eco] = report["summary"]["ecosystems"].get(eco, 0) + 1

    validate_report(report)
    settings.analysis_dir.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(report, indent=2, default=str)
    settings.report_path.write_text(payload)
    logger.info("\nReport written to %s", settings.report_path)

    # The frontend contract: a trimmed projection of the analysis above into the
    # node/edge graph model (graph.schema.json). The full report stays the
    # internal artifact feeding mermaid/graphml/markdown/drift.
    # Optional server-side "newer release available?" check (degrades to None).
    update_cfg = load_update_check_config()
    release = latest_release(update_cfg["repo"]) if update_cfg["enabled"] else None
    if release:
        logger.info("Latest published release: v%s", release["version"])

    graph = build_graph(
        projects=projects,
        internal_graph=internal_graph,
        systems=systems,
        generated_at=report["generated_at"],
        shared_cfg=load_shared_config(),
        palette=load_language_palette(),
        app_version=__version__,
        latest_version=release["version"] if release else None,
        latest_version_url=release["url"] if release else None,
    )
    validate_graph(graph)
    graph_payload = json.dumps(graph, indent=2, default=str)
    settings.graph_path.write_text(graph_payload)
    logger.info("Graph written to %s", settings.graph_path)

    # Optional convenience copies for serving the webapp without a published
    # artifact. graph.json is what the webapp fetches; the report is kept too.
    if settings.webapp_data_dir:
        settings.webapp_data_dir.mkdir(parents=True, exist_ok=True)
        (settings.webapp_data_dir / "dependency_report.json").write_text(payload)
        (settings.webapp_data_dir / "graph.json").write_text(graph_payload)
        logger.info("Webapp copy written to %s", settings.webapp_data_dir / "graph.json")

    logger.info("\n=== Summary ===")
    logger.info("  projects analyzed: %d", report["summary"]["total_projects"])
    logger.info("  internal dependency edges: %d", report["summary"]["total_internal_edges"])
    logger.info("  ecosystems: %s", report["summary"]["ecosystems"])
    logger.info("  projects with undocumented refs: %d", report["summary"]["projects_with_undocumented_refs"])

    warn_config_drift(config_drift)

    return 0
