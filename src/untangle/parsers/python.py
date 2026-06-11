"""Python ecosystem: ``pyproject.toml`` + ``requirements*.txt``."""

from __future__ import annotations

import logging
import re
import tomllib
from pathlib import Path

from ..fswalk import find_files, read_text_capped
from ..patterns import DetectionPatterns
from .base import ParseResult

logger = logging.getLogger(__name__)

name = "python"

# Splits "httpx>=0.27", "pkg[extra]; python_version<'3.13'", "pkg @ url" → bare name.
_NAME_SPLIT_RE = re.compile(r"[><=!~\s\[;@]")


def _dep_name(spec: str) -> str:
    return _NAME_SPLIT_RE.split(spec)[0].strip()


def parse_pyproject_toml(path: Path) -> list[dict]:
    text = read_text_capped(path)
    if text is None:
        return []
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        logger.warning("[WARN] %s: invalid TOML — %s", path, exc)
        return []
    deps = []
    project = data.get("project", {})
    for dep in project.get("dependencies", []):
        if dep_name := _dep_name(str(dep)):
            deps.append({"name": dep_name, "raw": str(dep).strip(), "source": path.name})
    for group, group_deps in project.get("optional-dependencies", {}).items():
        for dep in group_deps:
            if dep_name := _dep_name(str(dep)):
                deps.append({"name": dep_name, "raw": str(dep).strip(), "source": f"{path.name}[{group}]"})
    return deps


def parse_requirements_txt(path: Path) -> list[dict]:
    text = read_text_capped(path)
    if text is None:
        return []
    deps = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line.startswith("-"):
            continue
        if dep_name := _dep_name(line):
            deps.append({"name": dep_name, "raw": line, "source": path.name})
    return deps


def parse(repo_dir: Path, patterns: DetectionPatterns) -> ParseResult:
    result = ParseResult()

    pyproject = repo_dir / "pyproject.toml"
    if pyproject.exists():
        result.ecosystems.append(name)
        result.manifest[name] = parse_pyproject_toml(pyproject)

    for req in find_files(repo_dir, ["requirements.txt", "requirements*.txt"]):
        if name not in result.ecosystems:
            result.ecosystems.append(name)
        result.manifest[f"{name}:{req.name}"] = parse_requirements_txt(req)

    return result
