"""Node.js ecosystem: ``package.json``."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from ..fswalk import read_text_capped
from ..patterns import DetectionPatterns
from .base import ParseResult

logger = logging.getLogger(__name__)

name = "nodejs"


def parse_package_json(path: Path) -> list[dict]:
    text = read_text_capped(path)
    if text is None:
        return []
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        logger.warning("[WARN] %s: invalid JSON — %s", path, exc)
        return []
    if not isinstance(data, dict):
        return []
    deps = []
    for section in ("dependencies", "devDependencies", "peerDependencies"):
        entries = data.get(section)
        if not isinstance(entries, dict):
            continue
        for dep_name, version in entries.items():
            deps.append({"name": dep_name, "version": version, "source": f"package.json:{section}"})
    return deps


def parse(repo_dir: Path, patterns: DetectionPatterns) -> ParseResult:
    result = ParseResult()
    pkg_json = repo_dir / "package.json"
    if pkg_json.exists():
        result.ecosystems.append(name)
        result.manifest[name] = parse_package_json(pkg_json)
    return result
