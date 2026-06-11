"""What counts as "internal"? — compiled detection patterns, built from config.

All knowledge about the organization's hosts lives here: which domains mark a
URL as internal, which hosts serve git remotes and container images, and which
npm scopes are first-party. Everything is data-driven from ``config/untangle.yml``
(``detection:`` section) with defaults derived from the configured origins, so
the analyzer itself contains no org-specific strings.

The instance is built once (see ``cli.py``) and passed explicitly to the code
that needs it — no module-level globals.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from dataclasses import dataclass
from functools import cached_property

logger = logging.getLogger(__name__)

# Hosts that are never implied as "internal domains": matching them would flag
# every public URL in source code as an internal reference.
PUBLIC_HOSTS = frozenset({"github.com", "www.github.com", "gitlab.com", "www.gitlab.com"})

# A regex that can never match — used when a pattern list is empty so callers
# don't need None checks.
_NEVER = re.compile(r"(?!x)x")


def _alternation(values: Iterable[str]) -> str:
    return "|".join(re.escape(v) for v in values)


@dataclass(frozen=True)
class DetectionPatterns:
    """Org-specific hosts/scopes, with compiled regex helpers.

    ``internal_domains``  domains whose URLs count as internal references
                          (e.g. ``acme.dev`` matches ``api.acme.dev/...``).
    ``git_hosts``         hosts serving internal git remotes (git deps, terraform).
    ``registry_hosts``    container registries serving first-party images.
    ``npm_scopes``        npm scopes (``@acme``) for first-party packages.
    ``infer_service_calls``  opt-in: guess service-call edges from loose internal
                          URLs by matching their path against discovered routes.
                          A best-effort heuristic that can mis-attribute shared
                          gateway/path-routed URLs, so it is off by default.
    """

    internal_domains: tuple[str, ...] = ()
    git_hosts: tuple[str, ...] = ()
    registry_hosts: tuple[str, ...] = ()
    npm_scopes: tuple[str, ...] = ()
    infer_service_calls: bool = False

    @classmethod
    def from_config(
        cls, detection: dict | None, origin_hosts: Iterable[str] = ()
    ) -> DetectionPatterns:
        """Build patterns from the ``detection:`` config mapping plus origin hosts.

        Defaulting rules:
        - ``git_hosts`` default to the hostnames of the configured origins.
        - ``internal_domains`` default to the origin hostnames *minus* public
          SaaS hosts (github.com/gitlab.com) — matching those would classify
          every public URL as internal.
        - ``registry_hosts`` and ``npm_scopes`` have no safe default: explicit only.
        """
        detection = detection or {}
        hosts = [h.strip().lower() for h in origin_hosts if h and h.strip()]

        git_hosts = tuple(detection.get("git_hosts") or hosts)
        internal_domains = tuple(
            detection.get("internal_domains") or [h for h in hosts if h not in PUBLIC_HOSTS]
        )
        registry_hosts = tuple(detection.get("registry_hosts") or ())
        npm_scopes = tuple(
            s if s.startswith("@") else f"@{s}" for s in (detection.get("npm_scopes") or ())
        )
        infer_service_calls = bool(detection.get("infer_service_calls", False))

        if not internal_domains:
            logger.info(
                "No internal domains configured or derivable from origins — "
                "URL-based dependency detection is disabled. Set "
                "`detection.internal_domains` in config/untangle.yml to enable it."
            )
        return cls(
            internal_domains=internal_domains,
            git_hosts=git_hosts,
            registry_hosts=registry_hosts,
            npm_scopes=npm_scopes,
            infer_service_calls=infer_service_calls,
        )

    # --- compiled regexes (cached per instance) ---

    @cached_property
    def internal_url_re(self) -> re.Pattern:
        """Match a URL-ish token on any internal domain (scheme optional)."""
        if not self.internal_domains:
            return _NEVER
        return re.compile(
            rf"""(?:https?://)?(?:[\w.-]+\.)?(?:{_alternation(self.internal_domains)})(?:[:/]\S*)?""",
            re.IGNORECASE,
        )

    @cached_property
    def registry_re(self) -> re.Pattern:
        """Match an image reference on any internal container registry."""
        if not self.registry_hosts:
            return _NEVER
        return re.compile(rf"""(?:{_alternation(self.registry_hosts)})/[\w./-]+""", re.IGNORECASE)

    @cached_property
    def git_url_re(self) -> re.Pattern:
        """Match a git dependency URL on any internal git host."""
        if not self.git_hosts:
            return _NEVER
        return re.compile(
            rf"""git(?:\+https?|@|::https?)://[^/]*(?:{_alternation(self.git_hosts)})[/:](\S+?)(?:\.git)?(?:\s|"|'|$)""",
            re.IGNORECASE,
        )

    @cached_property
    def tf_ref_re(self) -> re.Pattern:
        """Match terraform ``source =`` / ``address =`` values on internal git hosts."""
        if not self.git_hosts:
            return _NEVER
        return re.compile(
            rf'''(source|address)\s*=\s*"([^"]*(?:{_alternation(self.git_hosts)})[^"]*)"'''
        )

    # --- substring helpers ---

    def contains_internal_domain(self, value: str) -> bool:
        return any(d in value for d in self.internal_domains)

    def matches_git_host(self, value: str) -> bool:
        v = value.lower()
        return any(h in v for h in self.git_hosts)

    def matches_registry_host(self, value: str) -> bool:
        v = value.lower()
        return any(h in v for h in self.registry_hosts)

    def is_internal_npm(self, name: str) -> bool:
        return any(name.startswith(f"{scope}/") for scope in self.npm_scopes)

    def strip_registry_prefix(self, image_ref: str) -> str | None:
        """Return the repo-ish path of an internal image ref (no host, no tag)."""
        m = self.registry_re.search(image_ref)
        if not m:
            return None
        path = m.group(0)
        for host in self.registry_hosts:
            prefix = f"{host}/"
            if path.lower().startswith(prefix.lower()):
                path = path[len(prefix):]
                break
        return path.split(":")[0]
