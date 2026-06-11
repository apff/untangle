"""GitLab CI: ``.gitlab-ci.yml`` cross-project includes, components, and images.

Harmless for repos without a ``.gitlab-ci.yml`` (returns nothing), so it runs
for every origin type — GitHub-hosted repos simply never match.
"""

from __future__ import annotations

import logging
from pathlib import Path

import yaml

from ..fswalk import read_text_capped
from ..patterns import DetectionPatterns
from .base import ParseResult

logger = logging.getLogger(__name__)

name = "gitlab_ci"


def _extract_component_project(component_str: str) -> str | None:
    """Extract the project path from a CI component reference.

    Examples:
        $CI_SERVER_FQDN/infra/ci-components/docker-build@v1.0.0 -> infra/ci-components
        git.example.dev/infra/ci-components/semantic-release@~latest -> infra/ci-components
    """
    s = component_str.strip()
    s = s.split("@")[0]
    parts = s.split("/")
    if len(parts) >= 3:
        if parts[0].startswith("$") or "." in parts[0]:
            parts = parts[1:]
        if len(parts) >= 2:
            return "/".join(parts[:-1])
    return None


def parse_gitlab_ci(path: Path, patterns: DetectionPatterns) -> dict:
    text = read_text_capped(path)
    if text is None:
        return {}
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        logger.warning("[WARN] %s: invalid YAML — %s", path, exc)
        return {}
    if not isinstance(data, dict):
        return {}

    result: dict = {"includes": [], "components": [], "images": []}

    includes = data.get("include", [])
    if isinstance(includes, dict):
        includes = [includes]
    if isinstance(includes, list):
        for inc in includes:
            if isinstance(inc, dict) and "project" in inc:
                result["includes"].append({
                    "project": inc["project"],
                    "file": inc.get("file", ""),
                    "ref": inc.get("ref", ""),
                })
            if isinstance(inc, dict) and "component" in inc:
                comp = inc["component"]
                project_path = _extract_component_project(comp)
                if project_path:
                    component_name = comp.rsplit("/", 1)[-1].split("@")[0] if "/" in comp else comp
                    result["components"].append({
                        "project": project_path,
                        "component": component_name,
                        "raw": comp,
                    })

    for key, value in data.items():
        if isinstance(value, dict):
            img = value.get("image")
            if isinstance(img, str) and patterns.contains_internal_domain(img):
                result["images"].append({"job": key, "image": img})
            elif isinstance(img, dict) and patterns.contains_internal_domain(str(img.get("name", ""))):
                result["images"].append({"job": key, "image": img["name"]})

    default_image = data.get("image")
    if isinstance(default_image, str) and patterns.contains_internal_domain(default_image):
        result["images"].append({"job": "default", "image": default_image})

    return result


def parse(repo_dir: Path, patterns: DetectionPatterns) -> ParseResult:
    result = ParseResult()
    ci_file = repo_dir / ".gitlab-ci.yml"
    if not ci_file.exists():
        return result

    ci_data = parse_gitlab_ci(ci_file, patterns)
    for inc in ci_data.get("includes", []):
        result.internal.append({
            "target": inc["project"],
            "type": "ci_include",
            "file": inc.get("file", ""),
            "source": ".gitlab-ci.yml",
        })
    for comp in ci_data.get("components", []):
        result.internal.append({
            "target": comp["project"],
            "type": "ci_component",
            "detail": comp.get("component", ""),
            "source": ".gitlab-ci.yml",
        })
    for img in ci_data.get("images", []):
        result.internal.append({
            "target": img["image"],
            "type": "ci_image",
            "job": img["job"],
            "source": ".gitlab-ci.yml",
        })
    return result
