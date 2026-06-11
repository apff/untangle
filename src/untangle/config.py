"""Runtime configuration, resolved from the environment.

All paths derive from a single ``DATA_DIR`` so the tool is container-friendly:
mount one volume, point ``DATA_DIR`` at it, and the clone cache + analysis
outputs live underneath. Origin URLs and credentials are NOT part of these
settings — the provider layer (``providers/``) resolves them from
``config/untangle.yml`` and the environment, so ``analyze``/``report`` run
without any tokens.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    """Resolved configuration for a single invocation."""

    data_dir: Path
    branch_priority: tuple[str, ...] = ("develop", "main", "master")
    clone_depth: int = 1  # 0 == full clone; >0 == shallow depth
    webapp_data_dir: Path | None = None
    # Tolerate a few broken repos, but fail the run (non-zero exit) when the
    # share of clone failures exceeds this — so a real GitLab/network outage
    # surfaces as a failed pipeline instead of a silently degraded report.
    max_clone_failure_ratio: float = 0.15

    @classmethod
    def from_env(cls) -> Settings:
        """Build settings purely from environment variables.

        (The CLI loads a local .env into the environment first; this stays a
        side-effect-free read so it's deterministic to test.)
        """
        priority = os.environ.get("BRANCH_PRIORITY", "develop,main,master")
        webapp = os.environ.get("WEBAPP_DATA_DIR")
        return cls(
            data_dir=Path(os.environ.get("DATA_DIR", "data")).resolve(),
            branch_priority=tuple(b.strip() for b in priority.split(",") if b.strip()),
            clone_depth=int(os.environ.get("CLONE_DEPTH", "1")),
            webapp_data_dir=Path(webapp).resolve() if webapp else None,
            max_clone_failure_ratio=float(os.environ.get("MAX_CLONE_FAILURE_RATIO", "0.15")),
        )

    # --- derived paths ---
    @property
    def repos_dir(self) -> Path:
        return self.data_dir / "repos"

    @property
    def analysis_dir(self) -> Path:
        return self.data_dir / "analysis"

    @property
    def manifest_path(self) -> Path:
        return self.repos_dir / "manifest.json"

    @property
    def report_path(self) -> Path:
        return self.analysis_dir / "dependency_report.json"

    @property
    def graph_path(self) -> Path:
        return self.analysis_dir / "graph.json"
