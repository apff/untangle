"""Static origin: an explicit list of git URLs — works with any git host.

No discovery API: the list itself is the inventory. Default branches and
branch lists come from ``git ls-remote`` like every other provider.
"""

from __future__ import annotations

import re

from .base import RemoteRepo, host_of, http_auth_env

# git@host:group/repo.git
_SSH_RE = re.compile(r"^(?:ssh://)?(?:[\w.-]+@)?(?P<host>[\w.-]+)[:/](?P<path>.+?)(?:\.git)?/?$")


def repo_path_from_url(url: str) -> tuple[str, str | None]:
    """Derive (path, host) from an https or ssh git URL.

    https://github.com/pallets/flask.git -> ("pallets/flask", "github.com")
    git@gitlab.acme.dev:core/api.git     -> ("core/api", "gitlab.acme.dev")
    """
    u = url.strip()
    if u.startswith(("http://", "https://")):
        host = host_of(u)
        path = u.split("//", 1)[1].split("/", 1)[1] if "/" in u.split("//", 1)[1] else ""
        path = path.rstrip("/").removesuffix(".git")
        return path, host
    m = _SSH_RE.match(u)
    if m:
        return m.group("path").rstrip("/"), m.group("host")
    raise SystemExit(f"ERROR: cannot parse git URL: {url!r}")


class StaticProvider:
    def __init__(
        self,
        repos: list[str],
        token: str = "",
        token_user: str = "oauth2",
        include: tuple[str, ...] = (),
        exclude: tuple[str, ...] = (),
    ) -> None:
        self.urls = [u for u in (r.strip() for r in repos) if u]
        self.token = token
        self.token_user = token_user
        self.include = include
        self.exclude = exclude
        self.name = "static"

    def discover(self) -> list[RemoteRepo]:
        repos = []
        for url in self.urls:
            path, _host = repo_path_from_url(url)
            web_url = url.removesuffix(".git") if url.startswith("http") else ""
            repos.append(
                RemoteRepo(
                    path=path,
                    name=path.split("/")[-1],
                    clone_url=url,
                    web_url=web_url,
                    origin=self.name,
                )
            )
        return repos

    def git_env(self, repo: RemoteRepo) -> dict[str, str]:
        if not self.token or not repo.clone_url.startswith("http"):
            return {}
        host = host_of(repo.clone_url)
        if not host:
            return {}
        return http_auth_env(f"https://{host}", self.token_user, self.token)

    def hosts(self) -> list[str]:
        seen = []
        for url in self.urls:
            _, host = repo_path_from_url(url)
            if host and host not in seen:
                seen.append(host)
        return seen
