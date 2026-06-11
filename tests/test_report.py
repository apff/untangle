"""Output generators: mermaid, GraphML, and markdown stay structurally valid."""

from __future__ import annotations

import xml.etree.ElementTree as ET

from untangle.report import generate_graphml, generate_markdown_report, generate_mermaid
from untangle.report_schema import validate_report

SAMPLE = {
    "schema_version": 1,
    "title": "Acme Stack",
    "generated_at": "2026-01-01T00:00:00+00:00",
    "systems": {"events": {"name": "Events", "groups": ["events"], "color": "#aaa"}},
    "projects": [
        {
            "path": "events/calendar",
            "name": "Calendar",
            "web_url": "https://gitlab.example.dev/events/calendar",
            "branch": "main",
            "ecosystems": ["python"],
            "dependencies": {"manifest": {}, "internal": [], "undocumented": [
                {"url": "https://example.dev/x", "type": "internal_url", "file": "a.py", "line": 1},
            ]},
        },
        {
            "path": "infra/ci-templates",
            "name": "CI Templates",
            "web_url": "https://gitlab.example.dev/infra/ci-templates",
            "branch": "main",
            "ecosystems": [],
            "dependencies": {"manifest": {}, "internal": [], "undocumented": []},
        },
    ],
    "internal_graph": {
        "nodes": [
            {"id": "events/calendar", "name": "Calendar", "group": "events", "ecosystems": ["python"]},
            {"id": "infra/ci-templates", "name": "CI Templates", "group": "infra", "ecosystems": []},
        ],
        "edges": [
            {"from": "events/calendar", "to": "infra/ci-templates", "type": "ci_include", "detail": "x"},
        ],
    },
    "system_graph": {"edges": []},
    "shared_infrastructure": {"networks": {}, "databases": {}, "registry_images": []},
    "config_drift": {"stale_prefix_targets": [], "unmapped_repo_groups": [], "empty_system_groups": []},
    "route_registry_summary": {},
    "summary": {
        "total_projects": 2,
        "total_internal_edges": 1,
        "ecosystems": {"python": 1},
        "projects_with_undocumented_refs": 1,
    },
}


def test_sample_passes_schema_validation():
    validate_report(SAMPLE)


def test_validate_report_rejects_missing_keys():
    import pytest

    with pytest.raises(ValueError, match="projects"):
        validate_report({k: v for k, v in SAMPLE.items() if k != "projects"})


def test_mermaid_contains_nodes_and_edges():
    mmd = generate_mermaid(SAMPLE)
    assert mmd.startswith("graph ")
    assert "events_calendar" in mmd          # sanitized node id
    assert "-.->|ci include|" in mmd          # edge with humanized type label


def test_graphml_is_valid_xml_with_all_nodes():
    xml = generate_graphml(SAMPLE)
    root = ET.fromstring(xml)
    assert root.tag.endswith("graphml")
    nodes = [el for el in root.iter() if el.tag.endswith("node")]
    assert len(nodes) == 2


def test_markdown_uses_report_title():
    md = generate_markdown_report(SAMPLE)
    assert md.startswith("# Acme Stack — Dependency Report")
    assert "events/calendar" in md
