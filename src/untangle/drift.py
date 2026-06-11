"""Config-drift detection: hand-maintained hints vs. the live repo set.

Catches the silent rot that hurts a small maintainer team: prefix hints that
point at renamed/deleted repos, repo groups not assigned to any system, and
configured system groups that no longer contain any repo.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def detect_config_drift(
    known_projects: set[str], systems: dict[str, dict], prefixes: dict[str, str]
) -> dict:
    repo_groups = {p.split("/")[0] for p in known_projects if "/" in p}
    mapped_groups = {g for sys in systems.values() for g in sys.get("groups", [])}

    stale_prefix_targets = sorted(
        {target for target in prefixes.values() if target not in known_projects}
    )
    unmapped_repo_groups = sorted(repo_groups - mapped_groups)
    empty_system_groups = sorted(mapped_groups - repo_groups)

    return {
        "stale_prefix_targets": stale_prefix_targets,
        "unmapped_repo_groups": unmapped_repo_groups,
        "empty_system_groups": empty_system_groups,
    }


def warn_config_drift(drift: dict) -> None:
    """Surface drifted config hints so the maintainers can reconcile them."""
    stale = drift.get("stale_prefix_targets", [])
    unmapped = drift.get("unmapped_repo_groups", [])
    empty = drift.get("empty_system_groups", [])
    if not (stale or unmapped or empty):
        return
    logger.warning("\n=== Config drift (review config/prefixes.yml + config/systems.yml) ===")
    if stale:
        logger.warning("  prefix hints pointing at missing repos (%d): %s", len(stale), ", ".join(stale))
    if unmapped:
        logger.warning("  repo groups not mapped to any system (%d): %s", len(unmapped), ", ".join(unmapped))
    if empty:
        logger.warning("  system groups with no repos (%d): %s", len(empty), ", ".join(empty))
