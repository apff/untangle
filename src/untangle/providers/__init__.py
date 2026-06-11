"""Build configured origin providers and run filtered discovery across them.

Origins come from ``config/untangle.yml``:

    origins:
      - type: gitlab
        url: https://gitlab.acme.dev
        token_env: GITLAB_API_TOKEN      # name of the env var holding the token
        include: []                      # optional path regexes
        exclude: ["^sandbox/"]
      - type: github
        org: acme-co                     # or `user: someone`
        token_env: GITHUB_TOKEN
      - type: static
        repos:
          - https://github.com/pallets/flask.git

Env-only fallback when no ``origins`` key exists (zero-config deployments):
``GITLAB_URL`` + ``GITLAB_API_TOKEN``/``GITLAB_TOKEN`` -> one gitlab origin;
``GITHUB_ORG`` or ``GITHUB_USER`` (+ ``GITHUB_TOKEN``) -> one github origin;
``GIT_REPOS`` (comma/whitespace-separated URLs) -> one static origin.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping

from .base import Provider, RemoteRepo, RepoFilter, pick_branch
from .github import GitHubProvider
from .gitlab import GitLabProvider
from .static import StaticProvider

__all__ = ["Provider", "RemoteRepo", "build_providers", "discover_all", "origin_hosts", "pick_branch"]

logger = logging.getLogger(__name__)


def _token(origin: dict, env: Mapping[str, str], *fallback_vars: str) -> str:
    token_env = origin.get("token_env")
    if token_env:
        return env.get(token_env, "")
    for var in fallback_vars:
        if env.get(var):
            return env[var]
    return ""


def _from_origin(origin: dict, env: Mapping[str, str]) -> Provider:
    kind = origin.get("type")
    include = tuple(origin.get("include") or ())
    exclude = tuple(origin.get("exclude") or ())
    if kind == "gitlab":
        url = origin.get("url")
        if not url:
            raise SystemExit("ERROR: gitlab origin needs `url`.")
        token = _token(origin, env, "GITLAB_API_TOKEN", "GITLAB_TOKEN")
        if not token:
            raise SystemExit(f"ERROR: gitlab origin {url}: no token (set `token_env` or GITLAB_API_TOKEN).")
        return GitLabProvider(url, token, include=include, exclude=exclude)
    if kind == "github":
        return GitHubProvider(
            org=origin.get("org"),
            user=origin.get("user"),
            token=_token(origin, env, "GITHUB_TOKEN"),
            api_url=origin.get("api_url") or "https://api.github.com",
            include=include,
            exclude=exclude,
        )
    if kind == "static":
        repos = origin.get("repos") or []
        if not repos:
            raise SystemExit("ERROR: static origin needs a non-empty `repos` list.")
        return StaticProvider(
            repos,
            token=_token(origin, env),
            token_user=origin.get("token_user") or "oauth2",
            include=include,
            exclude=exclude,
        )
    raise SystemExit(f"ERROR: unknown origin type {kind!r} (expected gitlab|github|static).")


def _from_env(env: Mapping[str, str]) -> list[Provider]:
    providers: list[Provider] = []
    if env.get("GITLAB_URL"):
        token = env.get("GITLAB_API_TOKEN") or env.get("GITLAB_TOKEN") or ""
        if not token:
            raise SystemExit("ERROR: GITLAB_URL is set but no GITLAB_API_TOKEN/GITLAB_TOKEN.")
        providers.append(GitLabProvider(env["GITLAB_URL"], token))
    if env.get("GITHUB_ORG") or env.get("GITHUB_USER"):
        providers.append(
            GitHubProvider(
                org=env.get("GITHUB_ORG") or None,
                user=env.get("GITHUB_USER") or None,
                token=env.get("GITHUB_TOKEN", ""),
            )
        )
    if env.get("GIT_REPOS"):
        urls = [u for u in re.split(r"[,\s]+", env["GIT_REPOS"]) if u]
        providers.append(StaticProvider(urls, token=env.get("GIT_REPOS_TOKEN", "")))
    return providers


def build_providers(app_config: dict, env: Mapping[str, str]) -> list[Provider]:
    """Providers for every configured origin ([] when nothing is configured)."""
    origins = app_config.get("origins")
    if origins:
        return [_from_origin(o, env) for o in origins]
    return _from_env(env)


def origin_hosts(providers: list[Provider]) -> list[str]:
    hosts: list[str] = []
    for provider in providers:
        for host in provider.hosts():
            if host not in hosts:
                hosts.append(host)
    return hosts


def discover_all(providers: list[Provider]) -> list[tuple[Provider, RemoteRepo]]:
    """Discover repos from every origin, filtered, with cross-origin dedup.

    Two origins claiming the same repo path would collide as graph node ids;
    the first origin wins and the duplicate is skipped with a warning.
    """
    found: list[tuple[Provider, RemoteRepo]] = []
    seen: dict[str, str] = {}
    for provider in providers:
        repo_filter = RepoFilter(provider.include, provider.exclude)
        for repo in provider.discover():
            if not repo_filter.matches(repo.path):
                continue
            if repo.path in seen:
                logger.warning(
                    "[WARN] %s: path %r already provided by %s — skipping duplicate",
                    provider.name, repo.path, seen[repo.path],
                )
                continue
            seen[repo.path] = provider.name
            found.append((provider, repo))
    return found
