"""GitHub origin: enumerate an org's or user's repositories via the REST API.

Supports github.com (default) and GitHub Enterprise via ``api_url``.
A token is optional for public repos but recommended (rate limits).
"""

from __future__ import annotations

import httpx

from .base import RemoteRepo, host_of, http_auth_env

DEFAULT_API_URL = "https://api.github.com"
DEFAULT_WEB_HOST = "github.com"


class GitHubProvider:
    def __init__(
        self,
        org: str | None = None,
        user: str | None = None,
        token: str = "",
        api_url: str = DEFAULT_API_URL,
        include: tuple[str, ...] = (),
        exclude: tuple[str, ...] = (),
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if bool(org) == bool(user):
            raise SystemExit("ERROR: a github origin needs exactly one of `org` or `user`.")
        self.owner = org or user
        self.owner_kind = "orgs" if org else "users"
        self.token = token
        self.api_url = api_url.rstrip("/")
        self.include = include
        self.exclude = exclude
        self.name = f"github:{self.owner}"
        self._transport = transport

    def _client(self) -> httpx.Client:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return httpx.Client(headers=headers, timeout=30.0, transport=self._transport)

    def discover(self) -> list[RemoteRepo]:
        repos = []
        url = f"{self.api_url}/{self.owner_kind}/{self.owner}/repos"
        params: dict | None = {"per_page": 100, "type": "all"}
        with self._client() as client:
            while url:
                resp = client.get(url, params=params)
                resp.raise_for_status()
                for r in resp.json():
                    if r.get("archived") or r.get("disabled"):
                        continue
                    repos.append(
                        RemoteRepo(
                            path=r["full_name"],
                            name=r["name"],
                            clone_url=r["clone_url"],
                            web_url=r["html_url"],
                            default_branch=r.get("default_branch"),
                            description=r.get("description") or "",
                            topics=tuple(r.get("topics") or ()),
                            last_activity_at=r.get("pushed_at"),
                            origin=self.name,
                            id=r.get("id"),
                            empty=r.get("size") == 0,
                        )
                    )
                # RFC 5988 pagination; params only apply to the first request.
                next_link = resp.links.get("next")
                url = next_link["url"] if next_link else None
                params = None
        return repos

    def git_env(self, repo: RemoteRepo) -> dict[str, str]:
        if not self.token:
            return {}
        host = host_of(repo.clone_url) or DEFAULT_WEB_HOST
        return http_auth_env(f"https://{host}", "x-access-token", self.token)

    def hosts(self) -> list[str]:
        if self.api_url == DEFAULT_API_URL:
            return [DEFAULT_WEB_HOST]
        host = host_of(self.api_url)
        return [host] if host else []
