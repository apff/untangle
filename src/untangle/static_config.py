"""Loaders for the deploy-time config files under ``config/``.

Three optional YAML files configure a deployment:

- ``untangle.yml``  app-level config: title, origins, detection patterns.
- ``systems.yml``   system groupings shown in the webapp.
- ``prefixes.yml``  manual URL-prefix → owning-repo hints (route-extraction fallback).

All are optional — with none present the tool still runs end-to-end (systems are
synthesized from repo groups, detection defaults derive from the origins).
They live as editable YAML outside the Python source so maintainers can update
them without touching code; ``analyze`` validates them for drift on every run.

Resolution order for the config directory:
1. ``UNTANGLE_CONFIG_DIR`` env var (tests, custom deployments, mounted overlays).
2. ``<repo-root>/config`` — the gitignored deploy-time overlay; also the layout
   inside the analyzer image (``/app/config``; see ``Dockerfile.analyzer``).
3. ``<repo-root>/config.example`` — the commented templates shipped with the
   repo, so a fresh checkout works with zero setup.
"""

from __future__ import annotations

import os
from pathlib import Path

import yaml


def config_dir() -> Path:
    """Locate the directory holding the config YAML files."""
    override = os.environ.get("UNTANGLE_CONFIG_DIR")
    if override:
        return Path(override).resolve()
    # src/untangle/static_config.py -> parents[2] == repo root (/app in image)
    root = Path(__file__).resolve().parents[2]
    config = root / "config"
    return config if config.is_dir() else root / "config.example"


def _load_yaml(name: str) -> dict:
    """Load a config YAML, tolerating a missing file (returns ``{}``)."""
    path = config_dir() / name
    if not path.exists():
        return {}
    data = yaml.safe_load(path.read_text()) or {}
    if not isinstance(data, dict):
        raise SystemExit(f"ERROR: {path} must contain a mapping, got {type(data).__name__}.")
    return data


def load_app_config() -> dict:
    """Return the app-level config from ``untangle.yml`` (``{}`` if absent)."""
    return _load_yaml("untangle.yml")


def load_prefixes() -> dict[str, str]:
    """Return the URL-prefix → repo-path hints from ``prefixes.yml``."""
    data = _load_yaml("prefixes.yml")
    prefixes = data.get("prefixes", data)  # tolerate a bare top-level map too
    return {str(k): str(v) for k, v in prefixes.items()}


def load_systems() -> dict[str, dict]:
    """Return the system groupings from ``systems.yml``."""
    data = _load_yaml("systems.yml")
    return data.get("systems", data)


def load_shared_config() -> dict[str, list[str]]:
    """Return the Shared-Components override lists from ``untangle.yml``.

    ``shared.include`` force-marks repos (path globs) as org-wide hubs and
    ``shared.exclude`` force-keeps them out, on top of the analyzer's
    cross-system heuristic. Absent file/key -> empty lists (heuristic only).
    """
    shared = load_app_config().get("shared", {}) or {}
    return {
        "include": [str(p) for p in (shared.get("include", []) or [])],
        "exclude": [str(p) for p in (shared.get("exclude", []) or [])],
    }


def load_update_check_config() -> dict:
    """Return the update-check settings from ``untangle.yml`` > ``update_check``.

    ``enabled`` (default True) toggles the server-side GitHub release check;
    ``repo`` (default ``apff/untangle``) is the ``owner/name`` to check.
    """
    cfg = load_app_config().get("update_check", {}) or {}
    return {
        "enabled": cfg.get("enabled", True),
        "repo": str(cfg.get("repo", "apff/untangle")),
    }


def load_language_palette() -> dict[str, str]:
    """Return language-id -> hex-color overrides from ``languages.yml``.

    Merged over ``graph_contract.DEFAULT_LANGUAGE_COLORS`` by the graph builder;
    absent file -> ``{}`` (defaults only).
    """
    data = _load_yaml("languages.yml")
    palette = data.get("languages", data)  # tolerate a bare top-level map too
    return {str(k): str(v) for k, v in palette.items()}
