from __future__ import annotations

from untangle.routes import (
    _normalize_path,
    build_prefix_index,
    normalize_url_to_path,
    resolve_url_to_repo,
)

HOSTS = ("example.dev", "example.org")


def test_normalize_path_strips_slashes_and_params():
    assert _normalize_path("/Foo/Bar/") == "foo/bar"
    assert _normalize_path("api/{idEvent}/x") == "api/:x/x"
    assert _normalize_path("api/:id/x") == "api/:x/x"
    assert _normalize_path("a?b=1#c") == "a"


def test_normalize_url_to_path():
    assert normalize_url_to_path("https://example.org/MaiaV4/SendEmail", HOSTS) == "maiav4/sendemail"
    # non-internal host -> None
    assert normalize_url_to_path("https://elsewhere.com/foo", HOSTS) is None
    # static assets -> None
    assert normalize_url_to_path("https://example.dev/static/logo.png", HOSTS) is None


def test_resolve_url_to_repo_uses_manual_prefix_hints():
    index = build_prefix_index({}, {"maiav4": "core/messaging/maia", "geotime": "core/geotime"})
    assert resolve_url_to_repo("https://example.org/maiav4/SendEmail", index, HOSTS) == "core/messaging/maia"
    assert resolve_url_to_repo("https://example.dev/geotime/api/zones", index, HOSTS) == "core/geotime"
    # unknown / external -> None
    assert resolve_url_to_repo("https://elsewhere.com/whatever", index, HOSTS) is None


def test_discovered_route_overrides_when_more_specific():
    index = build_prefix_index({"some/repo": [("widgets/list", "express")]}, {})
    assert resolve_url_to_repo("https://example.dev/widgets/list", index, HOSTS) == "some/repo"


def test_generic_discovered_route_does_not_resolve():
    # A bare `/api` route is too generic to identify a repo: the GitLab-API-style
    # URL `host/api/v4` must not get pinned to whichever repo mounted `/api`.
    index = build_prefix_index({"backup/backups_grid": [("api", "express")]}, {})
    assert "api" not in index
    assert resolve_url_to_repo("https://gitlab.example.dev/api/v4", index, HOSTS) is None
    # ...and a `/admin` route must not capture the forge admin panel.
    index2 = build_prefix_index({"core/wtm2": [("admin", "express")]}, {})
    assert resolve_url_to_repo("https://gitlab.example.dev/admin/applications", index2, HOSTS) is None


def test_nested_route_under_generic_segment_still_resolves():
    # Only the bare generic segment is dropped — multi-segment routes are kept.
    index = build_prefix_index({"some/repo": [("api/users", "express")]}, {})
    assert resolve_url_to_repo("https://example.dev/api/users/42", index, HOSTS) == "some/repo"


def test_manual_generic_prefix_hint_is_honored():
    # Operator intent wins: an explicit prefixes.yml hint keyed on a generic
    # segment is kept (unlike auto-discovered generic routes).
    index = build_prefix_index({}, {"api": "platform/gateway"})
    assert resolve_url_to_repo("https://example.dev/api/anything", index, HOSTS) == "platform/gateway"
