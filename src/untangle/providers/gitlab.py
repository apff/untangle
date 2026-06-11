"""GitLab origin: enumerate all non-archived projects via the REST v4 API.

Works identically for self-hosted instances and gitlab.com (set ``url``).
"""

from __future__ import annotations

import httpx

from .base import RemoteRepo, host_of, http_auth_env


def get_all_pages(client: httpx.Client, path: str, params: dict | None = None) -> list:
    results: list = []
    page = 1
    while True:
        req_params = {"page": page, "per_page": 100, **(params or {})}
        resp = client.get(path, params=req_params)
        resp.raise_for_status()
        data = resp.json()
        if not data:
            break
        results.extend(data)
        next_page = resp.headers.get("x-next-page", "")
        if not next_page:
            break
        page = int(next_page)
    return results


class GitLabProvider:
    def __init__(
        self,
        url: str,
        token: str,
        include: tuple[str, ...] = (),
        exclude: tuple[str, ...] = (),
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.url = url.rstrip("/")
        self.token = token
        self.include = include
        self.exclude = exclude
        self.name = f"gitlab:{host_of(self.url)}"
        self._transport = transport

    def _client(self) -> httpx.Client:
        return httpx.Client(
            base_url=f"{self.url}/api/v4",
            headers={"PRIVATE-TOKEN": self.token},
            timeout=30.0,
            transport=self._transport,
        )

    def discover(self) -> list[RemoteRepo]:
        with self._client() as client:
            projects = get_all_pages(client, "/projects", {"archived": "false"})
        repos = []
        for p in projects:
            repos.append(
                RemoteRepo(
                    path=p["path_with_namespace"],
                    name=p["name"],
                    clone_url=f"{self.url}/{p['path_with_namespace']}.git",
                    web_url=p["web_url"],
                    default_branch=p.get("default_branch"),
                    description=p.get("description") or "",
                    topics=tuple(p.get("topics") or ()),
                    last_activity_at=p.get("last_activity_at"),
                    origin=self.name,
                    id=p.get("id"),
                    empty=bool(p.get("empty_repo")),
                )
            )
        return repos

    def git_env(self, repo: RemoteRepo) -> dict[str, str]:
        return http_auth_env(self.url, "oauth2", self.token)

    def hosts(self) -> list[str]:
        host = host_of(self.url)
        return [host] if host else []
