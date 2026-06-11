"""Docker ecosystem: ``Dockerfile*`` base images + ``docker-compose*`` services."""

from __future__ import annotations

import logging
import re
from pathlib import Path

import yaml

from ..fswalk import find_files, read_text_capped
from ..patterns import DetectionPatterns
from .base import ParseResult

logger = logging.getLogger(__name__)

name = "docker"

_FROM_RE = re.compile(r"^\s*FROM\s+(\S+)", re.IGNORECASE)


def _join_continuations(text: str) -> list[str]:
    """Merge backslash-continued lines so multi-line FROM instructions parse."""
    lines: list[str] = []
    for line in text.splitlines():
        if lines and lines[-1].rstrip().endswith("\\"):
            lines[-1] = lines[-1].rstrip()[:-1] + " " + line.strip()
        else:
            lines.append(line)
    return lines


def parse_dockerfile(path: Path) -> list[dict]:
    text = read_text_capped(path)
    if text is None:
        return []
    deps = []
    for line in _join_continuations(text):
        m = _FROM_RE.match(line)
        if not m:
            continue
        image = m.group(1)
        # `FROM ${BASE_IMAGE}` is a build arg, not a resolvable image reference.
        if image.startswith("$"):
            continue
        deps.append({"image": image, "source": path.name})
    return deps


def parse_docker_compose(path: Path, patterns: DetectionPatterns) -> dict:
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

    result: dict = {"images": [], "depends_on": [], "networks": [], "env_refs": []}
    services = data.get("services", {})
    if not isinstance(services, dict):
        return result

    for svc_name, svc in services.items():
        if not isinstance(svc, dict):
            continue
        img = svc.get("image")
        if img:
            result["images"].append({"service": svc_name, "image": str(img), "source": path.name})
        deps_on = svc.get("depends_on")
        if isinstance(deps_on, list):
            result["depends_on"].extend(deps_on)
        elif isinstance(deps_on, dict):
            result["depends_on"].extend(deps_on.keys())

        for env_val in _extract_env_values(svc):
            if patterns.contains_internal_domain(env_val):
                result["env_refs"].append({"value": env_val, "service": svc_name, "source": path.name})

    networks = data.get("networks", {})
    if isinstance(networks, dict):
        result["networks"] = list(networks.keys())

    return result


def _extract_env_values(svc: dict) -> list[str]:
    values = []
    env = svc.get("environment")
    if isinstance(env, dict):
        values.extend(str(v) for v in env.values() if v)
    elif isinstance(env, list):
        for item in env:
            if "=" in str(item):
                values.append(str(item).split("=", 1)[1])
    return values


def parse(repo_dir: Path, patterns: DetectionPatterns) -> ParseResult:
    result = ParseResult()

    for dockerfile in find_files(repo_dir, ["Dockerfile", "Dockerfile.*"]):
        if name not in result.ecosystems:
            result.ecosystems.append(name)
        result.manifest.setdefault("docker_images", []).extend(parse_dockerfile(dockerfile))

    for compose in find_files(
        repo_dir,
        ["docker-compose.yml", "docker-compose.yaml", "docker-compose*.yml", "docker-compose*.yaml"],
    ):
        compose_data = parse_docker_compose(compose, patterns)
        if compose_data.get("images"):
            result.manifest.setdefault("docker_images", []).extend(compose_data["images"])
        if compose_data.get("depends_on"):
            result.manifest.setdefault("compose_depends_on", []).extend(compose_data["depends_on"])
        result.shared_networks.extend(compose_data.get("networks", []))
        for ref in compose_data.get("env_refs", []):
            result.internal.append({
                "target": ref["value"],
                "type": "compose_env",
                "source": ref["source"],
                "service": ref["service"],
            })

    return result
