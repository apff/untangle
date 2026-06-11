"""Generate architecture diagrams and reports from the dependency analysis."""

from __future__ import annotations

import io
import json
import xml.etree.ElementTree as ET
from collections import defaultdict

from .config import Settings


def load_report(settings: Settings) -> dict:
    if not settings.report_path.exists():
        raise SystemExit(
            f"ERROR: {settings.report_path} not found. Run `untangle analyze` first."
        )
    return json.loads(settings.report_path.read_text())


def sanitize_mermaid_id(s: str) -> str:
    return s.replace("/", "_").replace("-", "_").replace(".", "_")


def generate_mermaid(report: dict) -> str:
    graph = report["internal_graph"]
    projects = {p["path"]: p for p in report["projects"]}

    groups: dict[str, list[str]] = defaultdict(list)
    for node in graph["nodes"]:
        groups[node["group"] or "root"].append(node["id"])

    edge_styles = {
        "ci_include": "-.->",
        "ci_image": "-.->",
        "docker_registry": "-->",
        "compose_env": "-->",
        "internal_npm_package": "-->",
        "git_dependency": "-->",
        "terraform": "==>",
        "service_reference": "-.->",
    }

    lines = ["graph LR"]

    for group, members in sorted(groups.items()):
        if group:
            lines.append(f"    subgraph {sanitize_mermaid_id(group)}[\"{group}\"]")
        for member in sorted(members):
            mid = sanitize_mermaid_id(member)
            name = projects.get(member, {}).get("name", member.split("/")[-1])
            ecosystems = projects.get(member, {}).get("ecosystems", [])
            eco_label = f" ({', '.join(ecosystems)})" if ecosystems else ""
            lines.append(f"        {mid}[\"{name}{eco_label}\"]")
        if group:
            lines.append("    end")

    lines.append("")

    for edge in graph["edges"]:
        src = sanitize_mermaid_id(edge["from"])
        dst = sanitize_mermaid_id(edge["to"])
        arrow = edge_styles.get(edge["type"], "-->")
        label = edge["type"].replace("_", " ")
        lines.append(f"    {src} {arrow}|{label}| {dst}")

    infra = report.get("shared_infrastructure", {})
    networks = infra.get("networks", {})
    for net_name, net_members in networks.items():
        if len(net_members) > 1:
            lines.append(f"\n    subgraph net_{sanitize_mermaid_id(net_name)}[\"{net_name}\"]")
            for m in sorted(net_members):
                lines.append(f"        {sanitize_mermaid_id(m)}")
            lines.append("    end")

    return "\n".join(lines)


def generate_graphml(report: dict) -> str:
    graph = report["internal_graph"]
    projects = {p["path"]: p for p in report["projects"]}

    ns = "http://graphml.graphstruct.org/xmlns"
    ET.register_namespace("", ns)

    graphml = ET.Element("graphml", xmlns=ns)

    ET.SubElement(graphml, "key", id="d0", attrib={
        "for": "node", "attr.name": "label", "attr.type": "string",
    })
    ET.SubElement(graphml, "key", id="d1", attrib={
        "for": "node", "attr.name": "group", "attr.type": "string",
    })
    ET.SubElement(graphml, "key", id="d2", attrib={
        "for": "node", "attr.name": "ecosystems", "attr.type": "string",
    })
    ET.SubElement(graphml, "key", id="d3", attrib={
        "for": "edge", "attr.name": "type", "attr.type": "string",
    })
    ET.SubElement(graphml, "key", id="d4", attrib={
        "for": "edge", "attr.name": "detail", "attr.type": "string",
    })

    g = ET.SubElement(graphml, "graph", id="G", edgedefault="directed")

    for node in graph["nodes"]:
        n = ET.SubElement(g, "node", id=node["id"])
        d = ET.SubElement(n, "data", key="d0")
        d.text = projects.get(node["id"], {}).get("name", node["id"])
        d = ET.SubElement(n, "data", key="d1")
        d.text = node.get("group", "")
        d = ET.SubElement(n, "data", key="d2")
        d.text = ", ".join(node.get("ecosystems", []))

    for i, edge in enumerate(graph["edges"]):
        e = ET.SubElement(g, "edge", id=f"e{i}", source=edge["from"], target=edge["to"])
        d = ET.SubElement(e, "data", key="d3")
        d.text = edge["type"]
        d = ET.SubElement(e, "data", key="d4")
        d.text = edge.get("detail", "")

    tree = ET.ElementTree(graphml)
    ET.indent(tree, space="  ")
    buf = io.BytesIO()
    tree.write(buf, encoding="utf-8", xml_declaration=True)
    return buf.getvalue().decode("utf-8")


def generate_markdown_report(report: dict) -> str:
    projects = report["projects"]
    graph = report["internal_graph"]
    infra = report.get("shared_infrastructure", {})
    summary = report["summary"]

    sections = []

    title = report.get("title", "Untangle")
    sections.append(f"# {title} — Dependency Report\n")
    sections.append(f"**Projects analyzed:** {summary['total_projects']}  ")
    sections.append(f"**Internal dependency edges:** {summary['total_internal_edges']}  ")
    sections.append(f"**Ecosystems:** {', '.join(f'{k} ({v})' for k, v in sorted(summary['ecosystems'].items()))}  ")
    sections.append(f"**Projects with undocumented refs:** {summary['projects_with_undocumented_refs']}  ")
    generated_at = report.get("generated_at") or summary.get("generated_at")
    if generated_at:
        sections.append(f"**Generated at:** {generated_at}  ")
    sections.append("")

    # Configuration drift — hand-maintained hints that no longer match the repos
    drift = report.get("config_drift", {})
    stale = drift.get("stale_prefix_targets", [])
    unmapped = drift.get("unmapped_repo_groups", [])
    empty = drift.get("empty_system_groups", [])
    if stale or unmapped or empty:
        sections.append("## ⚠️ Configuration Drift\n")
        sections.append(
            "Hand-maintained config has drifted from the live repo set. "
            "Reconcile `config/prefixes.yml` / `config/systems.yml` (see docs/extending.md).\n"
        )
        if stale:
            sections.append("**Prefix hints pointing at missing repos:**\n")
            for t in stale:
                sections.append(f"- `{t}`")
            sections.append("")
        if unmapped:
            sections.append("**Repo groups not mapped to any system:**\n")
            for g in unmapped:
                sections.append(f"- `{g}`")
            sections.append("")
        if empty:
            sections.append("**System groups with no repos:**\n")
            for g in empty:
                sections.append(f"- `{g}`")
            sections.append("")

    # Project inventory by group
    sections.append("## Project Inventory\n")
    groups: dict[str, list[dict]] = defaultdict(list)
    for p in projects:
        group = p["path"].split("/")[0] if "/" in p["path"] else "(root)"
        groups[group].append(p)

    for group, members in sorted(groups.items()):
        sections.append(f"### {group}\n")
        sections.append("| Project | Ecosystems | Branch | Description |")
        sections.append("|---------|-----------|--------|-------------|")
        for p in sorted(members, key=lambda x: x["path"]):
            name = p["path"].split("/")[-1] if "/" in p["path"] else p["path"]
            eco = ", ".join(p["ecosystems"]) or "—"
            desc = (p.get("description") or "—")[:80]
            sections.append(f"| [{name}]({p['web_url']}) | {eco} | {p['branch']} | {desc} |")
        sections.append("")

    # Internal dependency matrix
    sections.append("## Internal Dependencies\n")
    if graph["edges"]:
        sections.append("| From | To | Type | Detail |")
        sections.append("|------|-----|------|--------|")
        for edge in sorted(graph["edges"], key=lambda e: (e["from"], e["to"])):
            detail = (edge.get("detail") or "")[:60]
            sections.append(f"| {edge['from']} | {edge['to']} | {edge['type']} | {detail} |")
    else:
        sections.append("No internal dependency edges detected.\n")
    sections.append("")

    # Connectivity analysis
    sections.append("## Connectivity Analysis\n")
    in_degree: dict[str, int] = defaultdict(int)
    out_degree: dict[str, int] = defaultdict(int)
    for edge in graph["edges"]:
        out_degree[edge["from"]] += 1
        in_degree[edge["to"]] += 1

    connected = set()
    for edge in graph["edges"]:
        connected.add(edge["from"])
        connected.add(edge["to"])
    all_paths = {p["path"] for p in projects}
    orphans = all_paths - connected

    if orphans:
        sections.append("### Orphan Projects (no internal connections)\n")
        for o in sorted(orphans):
            sections.append(f"- {o}")
        sections.append("")

    most_depended = sorted(in_degree.items(), key=lambda x: -x[1])
    if most_depended:
        sections.append("### Most Depended-On (potential single points of failure)\n")
        for proj, count in most_depended[:10]:
            sections.append(f"- **{proj}**: {count} dependents")
        sections.append("")

    most_deps = sorted(out_degree.items(), key=lambda x: -x[1])
    if most_deps:
        sections.append("### Most Dependencies (outgoing)\n")
        for proj, count in most_deps[:10]:
            sections.append(f"- **{proj}**: depends on {count} internal projects")
        sections.append("")

    # Shared infrastructure
    sections.append("## Shared Infrastructure\n")

    networks = infra.get("networks", {})
    if networks:
        sections.append("### Docker Networks\n")
        for net, members in sorted(networks.items()):
            sections.append(f"**{net}:** {', '.join(sorted(members))}\n")

    databases = infra.get("databases", {})
    if databases:
        sections.append("### Databases\n")
        for db_type, db_projects in sorted(databases.items()):
            sections.append(f"**{db_type}:** {', '.join(sorted(db_projects))}\n")

    registries = infra.get("registry_images", [])
    if registries:
        sections.append("### Docker Registry Images\n")
        for img in sorted(registries):
            sections.append(f"- `{img}`")
        sections.append("")

    # Undocumented dependencies
    sections.append("## Undocumented Dependencies (Flagged for Review)\n")
    undoc_projects = [p for p in projects if p["dependencies"]["undocumented"]]
    if undoc_projects:
        for p in sorted(undoc_projects, key=lambda x: x["path"]):
            sections.append(f"### {p['path']}\n")
            seen_urls = set()
            for ref in p["dependencies"]["undocumented"]:
                url = ref["url"]
                if url in seen_urls:
                    continue
                seen_urls.add(url)
                env_key = ref.get("env_key", "")
                key_note = f" (`{env_key}`)" if env_key else ""
                sections.append(f"- `{url}`{key_note} — {ref['type']} ({ref['file']}:{ref.get('line', '?')})")
            sections.append("")
    else:
        sections.append("No undocumented internal references found.\n")

    return "\n".join(sections)


def run(settings: Settings) -> int:
    report = load_report(settings)
    settings.analysis_dir.mkdir(parents=True, exist_ok=True)

    mermaid_path = settings.analysis_dir / "architecture.mmd"
    mermaid_path.write_text(generate_mermaid(report))
    print(f"Mermaid diagram: {mermaid_path}")

    graphml_path = settings.analysis_dir / "architecture.graphml"
    graphml_path.write_text(generate_graphml(report))
    print(f"GraphML export: {graphml_path}")

    md_path = settings.analysis_dir / "REPORT.md"
    md_path.write_text(generate_markdown_report(report))
    print(f"Report: {md_path}")

    print("\nDone. Open REPORT.md for the full analysis.")
    return 0
