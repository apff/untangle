"""Tests for the manifest parsers, URL scanning, edge resolution and config drift.

The parsing/resolution core drives the whole report, so it gets fixture-based
coverage here. Fixtures are written to ``tmp_path`` rather than committed so
each case is self-describing, and use neutral example.* hosts (see conftest).
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from untangle.analyze import _resolve_undocumented_refs, analyze_project, synthesize_systems
from untangle.drift import detect_config_drift
from untangle.graph import build_internal_graph, build_system_graph
from untangle.parsers.docker import parse_docker_compose, parse_dockerfile
from untangle.parsers.gitlab_ci import parse_gitlab_ci
from untangle.parsers.nodejs import parse_package_json
from untangle.parsers.python import parse_pyproject_toml
from untangle.patterns import DetectionPatterns


def _write(repo: Path, rel: str, content: str) -> None:
    p = repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content)


def _project(path: str, name: str) -> dict:
    return {
        "id": 1,
        "path": path,
        "name": name,
        "web_url": f"https://gitlab.example.dev/{path}",
        "branch": "main",
        "description": "",
        "topics": [],
        "last_activity_at": None,
    }


# --- individual parsers ---

def test_parse_pyproject_extracts_name_and_optional_groups(tmp_path: Path):
    _write(tmp_path, "pyproject.toml", """
[project]
name = "svc"
dependencies = ["httpx>=0.27", "pyyaml"]
[project.optional-dependencies]
dev = ["pytest>=8"]
""")
    deps = parse_pyproject_toml(tmp_path / "pyproject.toml")
    names = {d["name"] for d in deps}
    assert {"httpx", "pyyaml", "pytest"} <= names
    assert any(d["source"].endswith("[dev]") for d in deps)


def test_parse_pyproject_invalid_toml_warns_and_returns_empty(tmp_path: Path, caplog):
    _write(tmp_path, "pyproject.toml", "[project\nbroken")
    assert parse_pyproject_toml(tmp_path / "pyproject.toml") == []
    assert "invalid TOML" in caplog.text


def test_parse_package_json_includes_all_sections(tmp_path: Path):
    _write(tmp_path, "package.json", """
{"dependencies": {"@acme/text": "^1.0.0"},
 "devDependencies": {"jest": "^29"}}
""")
    deps = parse_package_json(tmp_path / "package.json")
    names = {d["name"] for d in deps}
    assert "@acme/text" in names and "jest" in names


def test_parse_dockerfile_handles_continuations_and_skips_args(tmp_path: Path):
    _write(tmp_path, "Dockerfile", "FROM \\\n  ubuntu:22.04\nFROM ${BASE_IMAGE}\nFROM alpine:3 AS build\n")
    deps = parse_dockerfile(tmp_path / "Dockerfile")
    images = [d["image"] for d in deps]
    assert images == ["ubuntu:22.04", "alpine:3"]


def test_parse_gitlab_ci_includes_and_components(tmp_path: Path, patterns):
    _write(tmp_path, ".gitlab-ci.yml", """
include:
  - project: 'infra/ci-templates'
    file: '/base.yml'
  - component: '$CI_SERVER_FQDN/infra/ci-components/docker-build@v1.0.0'
""")
    ci = parse_gitlab_ci(tmp_path / ".gitlab-ci.yml", patterns)
    assert {"project": "infra/ci-templates", "file": "/base.yml", "ref": ""} in ci["includes"]
    assert ci["components"][0]["project"] == "infra/ci-components"


def test_parse_docker_compose_internal_env_ref(tmp_path: Path, patterns):
    _write(tmp_path, "docker-compose.yml", """
services:
  api:
    image: registry.example.dev/core/core:latest
    environment:
      MAIA_URL: https://example.dev/maiav4
""")
    data = parse_docker_compose(tmp_path / "docker-compose.yml", patterns)
    assert data["images"][0]["image"] == "registry.example.dev/core/core:latest"
    assert any("example.dev/maiav4" in r["value"] for r in data["env_refs"])


# --- end-to-end project analysis ---

def test_analyze_project_collects_internal_edges_and_undocumented(tmp_path: Path, patterns):
    repo = tmp_path / "events" / "calendar"
    _write(repo, "package.json", '{"dependencies": {"@acme/text": "^1.0.0", "left-pad": "^1"}}')
    _write(repo, "pyproject.toml", """
[project]
name = "calendar"
dependencies = ["git+https://gitlab.example.dev/shared-libs/wordapi.git"]
""")
    _write(repo, ".gitlab-ci.yml", """
include:
  - project: 'infra/ci-templates'
    file: '/base.yml'
""")
    _write(repo, "main.tf", 'module "x" { source = "git::https://gitlab.example.dev/infra/tf-modules.git" }')
    _write(repo, "src/api.js", 'const MAIA = "https://example.dev/maiav4/SendEmail";\n')

    known = {"events/calendar", "infra/ci-templates", "shared-libs/wordapi"}
    result = analyze_project(repo, _project("events/calendar", "calendar"), known, patterns)

    assert set(result["ecosystems"]) >= {"nodejs", "python", "terraform"}
    edge_types = {e["type"] for e in result["dependencies"]["internal"]}
    assert "internal_npm_package" in edge_types   # @acme/text
    assert "git_dependency" in edge_types          # gitlab.example.dev git dep
    assert "ci_include" in edge_types              # infra/ci-templates
    assert "terraform" in edge_types               # tf module source
    # the hardcoded MAIA url is an undocumented ref until route resolution
    assert any("maiav4" in u["url"] for u in result["dependencies"]["undocumented"])


def test_analyze_project_compose_files_parsed_once(tmp_path: Path, patterns):
    # docker-compose.yml matches both the literal and wildcard find patterns;
    # entries must not be duplicated (regression for the double-parse bug).
    repo = tmp_path / "core" / "api"
    _write(repo, "docker-compose.yml", """
services:
  api:
    image: registry.example.dev/core/api:latest
""")
    result = analyze_project(repo, _project("core/api", "api"), {"core/api"}, patterns)
    images = result["dependencies"]["manifest"]["docker_images"]
    assert len(images) == 1


# --- service-call inference (opt-in, off by default) ---

def _undoc(url: str, type_: str) -> dict:
    return {"url": url, "type": type_, "file": "src/x.js", "line": 1}


def test_service_call_inference_disabled_by_default(patterns):
    # patterns fixture leaves infer_service_calls at its default (False).
    projects = [{
        "path": "infra/source",
        "dependencies": {"internal": [], "undocumented": [
            _undoc("https://example.dev/widgets/list", "internal_url"),
        ]},
    }]
    summary = _resolve_undocumented_refs(projects, SimpleNamespace(repos_dir=Path("/nope")), patterns, {})

    assert summary["enabled"] is False
    # No edges invented; the undocumented ref is left exactly as-is.
    assert projects[0]["dependencies"]["internal"] == []
    assert len(projects[0]["dependencies"]["undocumented"]) == 1


def test_service_call_inference_skips_infra_hosts_but_resolves_app_urls(tmp_path: Path):
    patterns = DetectionPatterns(
        internal_domains=("example.dev", "example.org"),
        git_hosts=("gitlab.example.dev",),
        registry_hosts=("registry.example.dev",),
        npm_scopes=("@acme",),
        infer_service_calls=True,
    )
    repos = tmp_path / "repos"
    # Target repo declares a discoverable express route -> widgets/list.
    _write(repos / "core/widgets", "src/app.js", 'app.get("/widgets/list", h);\n')

    projects = [
        {
            "path": "infra/source",
            "dependencies": {"internal": [], "undocumented": [
                # GitLab's own API: classified git_host -> must NOT become a service call.
                _undoc("https://gitlab.example.dev/api/v4", "git_host"),
                # A real internal app URL -> resolves to the owning repo.
                _undoc("https://example.dev/widgets/list", "internal_url"),
            ]},
        },
        # The route owner; its routes must be discoverable for resolution to work.
        {"path": "core/widgets", "dependencies": {"internal": [], "undocumented": []}},
    ]
    summary = _resolve_undocumented_refs(projects, SimpleNamespace(repos_dir=repos), patterns, {})

    assert summary["enabled"] is True
    internal = projects[0]["dependencies"]["internal"]
    assert internal == [{
        "target": "core/widgets",
        "type": "service_call",
        "detail": "https://example.dev/widgets/list",
        "source": "src/x.js:1",
    }]
    # The forge-API ref is preserved as undocumented, never an edge.
    remaining = projects[0]["dependencies"]["undocumented"]
    assert [r["url"] for r in remaining] == ["https://gitlab.example.dev/api/v4"]


def test_build_internal_graph_resolves_and_dedupes_edges(patterns):
    projects = [{
        "path": "events/calendar",
        "name": "calendar",
        "ecosystems": ["nodejs"],
        "dependencies": {"internal": [
            {"target": "infra/ci-templates", "type": "ci_include"},
            {"target": "infra/ci-templates", "type": "ci_include"},  # dup -> collapsed
        ], "undocumented": []},
    }]
    graph = build_internal_graph(projects, {"events/calendar", "infra/ci-templates"}, patterns)
    edges = [(e["from"], e["to"], e["type"]) for e in graph["edges"]]
    assert edges == [("events/calendar", "infra/ci-templates", "ci_include")]


def test_build_system_graph_aggregates_cross_system_edges():
    internal_graph = {
        "nodes": [
            {"id": "events/calendar", "group": "events"},
            {"id": "infra/ci-templates", "group": "infra"},
            {"id": "infra/runner", "group": "infra"},
        ],
        "edges": [
            {"from": "events/calendar", "to": "infra/ci-templates", "type": "ci_include"},
            {"from": "events/calendar", "to": "infra/runner", "type": "ci_image"},
            {"from": "infra/runner", "to": "infra/ci-templates", "type": "ci_include"},  # intra: dropped
        ],
    }
    systems = {
        "events": {"groups": ["events"]},
        "infra": {"groups": ["infra"]},
    }
    sg = build_system_graph(internal_graph, systems)
    assert sg["edges"] == [
        {"from": "events", "to": "infra", "count": 2, "types": {"ci_include": 1, "ci_image": 1}},
    ]


def test_synthesize_systems_one_per_group():
    projects = [{"path": "events/calendar"}, {"path": "events/cfp"}, {"path": "infra/runner"}]
    systems = synthesize_systems(projects)
    assert set(systems) == {"events", "infra"}
    assert systems["events"]["groups"] == ["events"]
    assert systems["events"]["color"].startswith("#")


# --- config drift ---

def test_detect_config_drift_flags_stale_and_unmapped():
    systems = {"events": {"groups": ["events"]}}
    prefixes = {"foo": "events/calendar", "ghost": "events/deleted-repo"}
    known = {"events/calendar", "orphans/widget"}
    drift = detect_config_drift(known, systems, prefixes)

    assert drift["stale_prefix_targets"] == ["events/deleted-repo"]
    assert drift["unmapped_repo_groups"] == ["orphans"]
    assert drift["empty_system_groups"] == []


def test_detect_config_drift_clean_when_aligned():
    drift = detect_config_drift(
        {"events/calendar"}, {"events": {"groups": ["events"]}}, {"foo": "events/calendar"}
    )
    assert drift == {"stale_prefix_targets": [], "unmapped_repo_groups": [], "empty_system_groups": []}


# --- static_config resolution ---

def test_static_config_missing_files_return_empty(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("UNTANGLE_CONFIG_DIR", str(tmp_path / "nope"))
    from untangle.static_config import load_app_config, load_prefixes, load_systems
    assert load_prefixes() == {}
    assert load_systems() == {}
    assert load_app_config() == {}
