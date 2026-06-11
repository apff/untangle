"""Safe file-tree walking over cloned (untrusted) repo contents.

Every walk skips vendored/build directories, symlinks, files that resolve
outside the repo (symlinked paths), and — for content reads — files above a
size cap. The repos being scanned are arbitrary third-party content; a huge or
hostile file must degrade to a warning, never an OOM or a hang.
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

SKIP_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build",
    ".next", ".nuxt", "vendor", ".terraform", ".tox", "coverage", "bin", "obj",
}

# Source files larger than this are skipped with a warning. Real manifests and
# code are far smaller; anything bigger is generated output or a data blob.
MAX_SCAN_FILE_SIZE = 10 * 1024 * 1024  # 10 MB


def _is_safe(f: Path, repo_dir: Path) -> bool:
    if any(part in SKIP_DIRS for part in f.parts):
        return False
    if f.is_symlink():
        return False
    try:
        # Guard against symlinked parents pointing outside the clone.
        return f.resolve().is_relative_to(repo_dir.resolve())
    except OSError:
        return False


def find_files(repo_dir: Path, names: list[str]) -> list[Path]:
    """Find files by glob name patterns, deduplicated across overlapping patterns."""
    found: list[Path] = []
    seen: set[Path] = set()
    for name in names:
        for match in repo_dir.rglob(name):
            if match in seen or not match.is_file() or not _is_safe(match, repo_dir):
                continue
            seen.add(match)
            found.append(match)
    return found


def find_by_extensions(repo_dir: Path, extensions: set[str]) -> list[Path]:
    return [
        f
        for f in repo_dir.rglob("*")
        if f.suffix in extensions and f.is_file() and _is_safe(f, repo_dir)
    ]


def read_text_capped(path: Path) -> str | None:
    """Read a file's text, or return None (with a warning) if oversized/unreadable."""
    try:
        if path.stat().st_size > MAX_SCAN_FILE_SIZE:
            logger.warning("[WARN] %s: exceeds %d MB, skipping", path, MAX_SCAN_FILE_SIZE // 2**20)
            return None
        return path.read_text(errors="replace")
    except OSError as exc:
        logger.warning("[WARN] %s: unreadable — %s", path, exc)
        return None
