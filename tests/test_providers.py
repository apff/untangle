"""Origin providers: discovery, pagination, filtering, auth env, and env fallback."""

from __future__ import annotations

import json

import httpx
import pytest

from untangle.providers import build_providers, discover_all, origin_hosts
from untangle.providers.base import RepoFilter, pick_branch
from untangle.providers.github import GitHubProvider
from untangle.providers.gitlab import GitLabProvider
from untangle.providers.static import StaticProvider, repo_path_from_url

# --- static ---

def test_repo_path_from_url_https_and_ssh():
    assert repo_path_from_url("https://github.com/pallets/flask.git") == ("pallets/flask", "github.com")
    assert repo_path_from_url("https://gitlab.acme.dev/core/sub/api/") == ("core/sub/api", "gitlab.acme.dev")
    assert repo_path_from_url("git@gitlab.acme.dev:core/api.git") == ("core/api", "gitlab.acme.dev")


def test_static_provider_discovers_and_authenticates():
    p = StaticProvider(
        ["https://github.com/pallets/flask.git", " git@host.dev:a/b.git "],
        token="sekret",
    )
    repos = p.discover()
    assert [r.path for r in repos] == ["pallets/flask", "a/b"]
    assert repos[0].web_url == "https://github.com/pallets/flask"
    # token never lands in the clone URL; https hosts get a header env
    assert "sekret" not in repos[0].clone_url
    env = p.git_env(repos[0])
    assert env["GIT_CONFIG_KEY_0"] == "http.https://github.com/.extraheader"
    assert "sekret" not in json.dumps(env)  # base64-encoded, not raw
    # ssh urls get no header env
    assert p.git_env(repos[1]) == {}
    assert p.hosts() == ["github.com", "host.dev"]


# --- gitlab ---

def _gitlab_transport(pages: list[list[dict]]) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        page = int(request.url.params.get("page", "1"))
        data = pages[page - 1] if page <= len(pages) else []
        headers = {"x-next-page": str(page + 1) if page < len(pages) else ""}
        return httpx.Response(200, json=data, headers=headers)

    return httpx.MockTransport(handler)


def test_gitlab_provider_paginates_and_maps_fields():
    pages = [
        [{
            "id": 7,
            "path_with_namespace": "core/api",
            "name": "API",
            "web_url": "https://gitlab.acme.dev/core/api",
            "default_branch": "develop",
            "topics": ["svc"],
            "last_activity_at": "2026-01-01",
            "empty_repo": False,
        }],
        [{
            "id": 8,
            "path_with_namespace": "core/empty",
            "name": "Empty",
            "web_url": "https://gitlab.acme.dev/core/empty",
            "empty_repo": True,
        }],
    ]
    p = GitLabProvider(
        "https://gitlab.acme.dev", "tok", transport=_gitlab_transport(pages)
    )
    repos = p.discover()
    assert [r.path for r in repos] == ["core/api", "core/empty"]
    api = repos[0]
    assert api.id == 7 and api.default_branch == "develop" and api.topics == ("svc",)
    assert api.clone_url == "https://gitlab.acme.dev/core/api.git"
    assert "tok" not in api.clone_url
    assert repos[1].empty is True
    assert p.git_env(api)["GIT_CONFIG_KEY_0"] == "http.https://gitlab.acme.dev/.extraheader"
    assert p.hosts() == ["gitlab.acme.dev"]


# --- github ---

def _github_transport() -> httpx.MockTransport:
    page1 = [
        {"id": 1, "full_name": "acme/app", "name": "app",
         "clone_url": "https://github.com/acme/app.git",
         "html_url": "https://github.com/acme/app",
         "default_branch": "main", "archived": False, "disabled": False,
         "topics": [], "pushed_at": "2026-01-01", "size": 10},
        {"id": 2, "full_name": "acme/old", "name": "old",
         "clone_url": "https://github.com/acme/old.git",
         "html_url": "https://github.com/acme/old",
         "default_branch": "main", "archived": True, "disabled": False, "size": 5},
    ]
    page2 = [
        {"id": 3, "full_name": "acme/lib", "name": "lib",
         "clone_url": "https://github.com/acme/lib.git",
         "html_url": "https://github.com/acme/lib",
         "default_branch": "master", "archived": False, "disabled": False, "size": 3},
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Bearer ghtok"
        if request.url.params.get("per_page"):
            return httpx.Response(
                200, json=page1,
                headers={"Link": '<https://api.github.com/orgs/acme/repos?page=2>; rel="next"'},
            )
        return httpx.Response(200, json=page2)

    return httpx.MockTransport(handler)


def test_github_provider_follows_link_pagination_and_filters_archived():
    p = GitHubProvider(org="acme", token="ghtok", transport=_github_transport())
    repos = p.discover()
    assert [r.path for r in repos] == ["acme/app", "acme/lib"]  # archived repo dropped
    assert repos[0].clone_url == "https://github.com/acme/app.git"
    assert p.git_env(repos[0])["GIT_CONFIG_KEY_0"] == "http.https://github.com/.extraheader"
    assert p.hosts() == ["github.com"]


def test_github_provider_requires_exactly_one_owner():
    with pytest.raises(SystemExit):
        GitHubProvider(org="a", user="b")
    with pytest.raises(SystemExit):
        GitHubProvider()


# --- filtering + cross-origin dedup ---

def test_repo_filter_include_exclude():
    f = RepoFilter(include=("^core/",), exclude=("-deprecated$",))
    assert f.matches("core/api")
    assert not f.matches("sandbox/api")
    assert not f.matches("core/api-deprecated")


def test_discover_all_skips_cross_origin_path_collisions(caplog):
    a = StaticProvider(["https://host-a.dev/acme/tool.git"])
    b = StaticProvider(["https://host-b.dev/acme/tool.git"])
    found = discover_all([a, b])
    assert len(found) == 1
    assert "skipping duplicate" in caplog.text


def test_discover_all_applies_per_origin_filters():
    p = StaticProvider(
        ["https://h.dev/keep/x.git", "https://h.dev/drop/y.git"], exclude=("^drop/",)
    )
    found = discover_all([p])
    assert [r.path for _, r in found] == ["keep/x"]


# --- build_providers config + env fallback ---

def test_build_providers_from_origins_config():
    config = {"origins": [
        {"type": "gitlab", "url": "https://gitlab.acme.dev", "token_env": "MY_GL_TOKEN"},
        {"type": "github", "org": "acme"},
        {"type": "static", "repos": ["https://h.dev/a/b.git"]},
    ]}
    env = {"MY_GL_TOKEN": "x", "GITHUB_TOKEN": "y"}
    providers = build_providers(config, env)
    assert [type(p).__name__ for p in providers] == [
        "GitLabProvider", "GitHubProvider", "StaticProvider",
    ]
    assert origin_hosts(providers) == ["gitlab.acme.dev", "github.com", "h.dev"]


def test_build_providers_env_fallback():
    env = {
        "GITLAB_URL": "https://gitlab.acme.dev", "GITLAB_API_TOKEN": "t",
        "GITHUB_ORG": "acme",
        "GIT_REPOS": "https://h.dev/a/b.git, https://h.dev/c/d.git",
    }
    providers = build_providers({}, env)
    assert len(providers) == 3
    static = providers[-1]
    assert [r.path for r in static.discover()] == ["a/b", "c/d"]


def test_build_providers_empty_when_nothing_configured():
    assert build_providers({}, {}) == []


def test_build_providers_gitlab_requires_token():
    with pytest.raises(SystemExit):
        build_providers({}, {"GITLAB_URL": "https://gitlab.acme.dev"})


# --- pick_branch ---

def test_pick_branch_priority_then_default_then_first():
    prio = ("develop", "main", "master")
    assert pick_branch(prio, ["main", "develop"], "main") == "develop"
    assert pick_branch(prio, ["feat", "prod"], "prod") == "prod"
    assert pick_branch(prio, ["feat"], None) == "feat"
    assert pick_branch(prio, [], None) is None
