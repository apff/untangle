"""The origin-provider contract: discover repos + supply git credentials.

A provider knows how to enumerate the repositories of one configured origin
(a GitLab instance, a GitHub org/user, or a static URL list) and how to
authenticate ``git`` against it. Clone mechanics live in ``clone.py`` and are
identical for every provider; branch discovery uses ``git ls-remote`` so
providers don't need per-host branch APIs.
"""

from __future__ import annotations

import base64
import re
from dataclasses import dataclass, field
from typing import Protocol
from urllib.parse import urlparse


@dataclass(frozen=True)
class RemoteRepo:
    """One discovered repository, origin-agnostic.

    ``clone_url`` is always credential-FREE: tokens travel via ``git_env()``
    HTTP headers, never inside URLs (which git would persist to .git/config
    on the long-lived clone-cache volume).
    """

    path: str                            # unique node id, e.g. "group/repo"
    name: str
    clone_url: str
    web_url: str
    default_branch: str | None = None
    description: str = ""
    topics: tuple[str, ...] = ()
    last_activity_at: str | None = None
    origin: str = ""                     # owning provider's name
    id: int | None = None                # origin-native id, when one exists
    empty: bool = False                  # known-empty repo: skip without contacting it


class Provider(Protocol):
    """One configured origin."""

    name: str
    include: tuple[str, ...]
    exclude: tuple[str, ...]

    def discover(self) -> list[RemoteRepo]:
        """Enumerate the origin's repositories (unfiltered)."""
        ...

    def git_env(self, repo: RemoteRepo) -> dict[str, str]:
        """Extra environment for git subprocesses touching ``repo``."""
        ...

    def hosts(self) -> list[str]:
        """Hostnames this origin serves repos from (feeds detection defaults)."""
        ...


def http_auth_env(base_url: str, username: str, token: str) -> dict[str, str]:
    """Git auth via an extraheader scoped to ``base_url`` — token stays off disk.

    Uses ``GIT_CONFIG_*`` environment configs (git >= 2.31): the Authorization
    header applies to every URL under ``base_url`` for that one subprocess and
    is never written to argv or any config file.
    """
    cred = base64.b64encode(f"{username}:{token}".encode()).decode()
    return {
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": f"http.{base_url.rstrip('/')}/.extraheader",
        "GIT_CONFIG_VALUE_0": f"Authorization: Basic {cred}",
    }


def pick_branch(
    branch_priority: tuple[str, ...], branches: list[str], default_branch: str | None
) -> str | None:
    """Choose the branch to analyze: priority list, then default, then first."""
    for candidate in branch_priority:
        if candidate in branches:
            return candidate
    if default_branch and default_branch in branches:
        return default_branch
    return branches[0] if branches else None


@dataclass
class RepoFilter:
    """Per-origin include/exclude regex filtering on repo paths."""

    include: tuple[str, ...] = ()
    exclude: tuple[str, ...] = ()
    _include_res: list[re.Pattern] = field(init=False)
    _exclude_res: list[re.Pattern] = field(init=False)

    def __post_init__(self) -> None:
        self._include_res = [re.compile(p) for p in self.include]
        self._exclude_res = [re.compile(p) for p in self.exclude]

    def matches(self, path: str) -> bool:
        if self._include_res and not any(p.search(path) for p in self._include_res):
            return False
        return not any(p.search(path) for p in self._exclude_res)


def host_of(url: str) -> str | None:
    return urlparse(url).hostname
