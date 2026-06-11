"""Terraform: module sources and backend addresses on internal git hosts."""

from __future__ import annotations

from pathlib import Path

from ..fswalk import find_files, read_text_capped
from ..patterns import DetectionPatterns
from .base import ParseResult

name = "terraform"


def parse_terraform(repo_dir: Path, patterns: DetectionPatterns) -> list[dict]:
    refs = []
    for tf_file in find_files(repo_dir, ["*.tf"]):
        content = read_text_capped(tf_file)
        if content is None:
            continue
        rel = str(tf_file.relative_to(repo_dir))
        for m in patterns.tf_ref_re.finditer(content):
            key = "source" if m.group(1) == "source" else "backend"
            refs.append({key: m.group(2), "file": rel})
    return refs


def parse(repo_dir: Path, patterns: DetectionPatterns) -> ParseResult:
    result = ParseResult()
    tf_refs = parse_terraform(repo_dir, patterns)
    if tf_refs:
        result.ecosystems.append(name)
        for ref in tf_refs:
            result.internal.append({
                "target": ref.get("source", ref.get("backend", "")),
                "type": "terraform",
                "source": ref["file"],
            })
    return result
