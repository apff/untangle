from __future__ import annotations

import pytest

from untangle.patterns import DetectionPatterns


@pytest.fixture
def patterns() -> DetectionPatterns:
    """Neutral org patterns used across parser/scanner/graph tests."""
    return DetectionPatterns(
        internal_domains=("example.dev", "example.org"),
        git_hosts=("gitlab.example.dev",),
        registry_hosts=("registry.example.dev",),
        npm_scopes=("@acme",),
    )
