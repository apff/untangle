"""Source/env scanning for undocumented internal references + heuristics.

Everything here works on raw file content with regexes — deliberately
best-effort. It finds the dependencies nobody declared: internal URLs buried in
source code and env templates, database hints, and internal package references
inside already-parsed manifests.
"""

from __future__ import annotations

import re
from pathlib import Path

from .fswalk import find_by_extensions, find_files, read_text_capped
from .patterns import DetectionPatterns

SOURCE_EXTENSIONS = {".py", ".js", ".ts", ".jsx", ".tsx", ".cs", ".go", ".rb", ".sh"}

ENV_FILE_NAMES = [".env.example", ".env.sample", ".env.template", ".env.dev"]

# Heuristic database hints from env templates: flags what a service *probably*
# uses; never treated as a hard fact.
DB_PATTERNS = {
    "mongodb": re.compile(r"mongo", re.IGNORECASE),
    "mssql": re.compile(r"mssql|sqlserver|sql.server", re.IGNORECASE),
    "postgresql": re.compile(r"postgres|pghost|pg_", re.IGNORECASE),
    "redis": re.compile(r"redis", re.IGNORECASE),
    "mysql": re.compile(r"mysql", re.IGNORECASE),
}


def scan_source_for_urls(repo_dir: Path, patterns: DetectionPatterns) -> list[dict]:
    hits = []
    for f in find_by_extensions(repo_dir, SOURCE_EXTENSIONS):
        content = read_text_capped(f)
        if content is None:
            continue
        rel = str(f.relative_to(repo_dir))
        for i, line in enumerate(content.splitlines(), 1):
            for m in patterns.internal_url_re.finditer(line):
                url = m.group(0).rstrip("\"'`,);]}")
                hits.append({"url": url, "file": rel, "line": i})
    return hits


def scan_env_files(repo_dir: Path, patterns: DetectionPatterns) -> list[dict]:
    hits = []
    for f in find_files(repo_dir, ENV_FILE_NAMES):
        content = read_text_capped(f)
        if content is None:
            continue
        rel = str(f.relative_to(repo_dir))
        for i, line in enumerate(content.splitlines(), 1):
            for m in patterns.internal_url_re.finditer(line):
                key = line.split("=", 1)[0].strip() if "=" in line else ""
                hits.append({"key": key, "url": m.group(0), "file": rel, "line": i})
    return hits


def classify_internal_url(url: str, known_projects: set[str], patterns: DetectionPatterns) -> str:
    url_lower = url.lower()
    if patterns.matches_registry_host(url_lower):
        return "docker_registry"
    if patterns.matches_git_host(url_lower):
        return "git_host"
    for proj in known_projects:
        proj_slug = proj.split("/")[-1]
        if proj_slug in url_lower:
            return "service_reference"
    return "internal_url"


def deduplicate_urls(hits: list[dict]) -> list[dict]:
    seen = set()
    unique = []
    for h in hits:
        key = h.get("url", h.get("value", ""))
        if key not in seen:
            seen.add(key)
            unique.append(h)
    return unique


def manifest_internal_refs(manifest: dict[str, list], patterns: DetectionPatterns) -> list[dict]:
    """Find internal references inside parsed manifest entries.

    Catches scoped npm packages, git dependencies on internal hosts, and images
    from internal registries — the cross-ecosystem classification that individual
    parsers don't do themselves.
    """
    refs = []
    for section_deps in manifest.values():
        if not isinstance(section_deps, list):
            continue
        for dep in section_deps:
            if not isinstance(dep, dict):
                continue
            name = dep.get("name", "")
            raw = dep.get("raw", "")
            if patterns.is_internal_npm(name):
                refs.append({
                    "target": name,
                    "type": "internal_npm_package",
                    "source": dep.get("source", ""),
                })
            if patterns.matches_git_host(raw):
                refs.append({
                    "target": raw,
                    "type": "git_dependency",
                    "source": dep.get("source", ""),
                })
            image = dep.get("image", "")
            if patterns.registry_re.search(image):
                refs.append({
                    "target": image,
                    "type": "docker_registry",
                    "source": dep.get("source", ""),
                })
    return refs


def detect_databases(repo_dir: Path) -> list[dict]:
    found = []
    for env_file in find_files(repo_dir, [".env.example", ".env.sample", ".env.template"]):
        content = read_text_capped(env_file)
        if content is None:
            continue
        for db_type, pattern in DB_PATTERNS.items():
            if pattern.search(content):
                found.append({"type": db_type, "source": str(env_file.relative_to(repo_dir))})
    return found
