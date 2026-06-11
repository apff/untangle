"""DetectionPatterns construction, defaulting rules, and regex helpers."""

from __future__ import annotations

from untangle.patterns import DetectionPatterns


def test_git_hosts_default_to_origin_hosts():
    p = DetectionPatterns.from_config({}, ["gitlab.acme.dev"])
    assert p.git_hosts == ("gitlab.acme.dev",)
    assert p.internal_domains == ("gitlab.acme.dev",)


def test_internal_domains_exclude_public_saas_hosts():
    p = DetectionPatterns.from_config({}, ["github.com", "gitlab.acme.dev"])
    assert p.internal_domains == ("gitlab.acme.dev",)
    # but github.com is still a git host (its repos are configured origins)
    assert p.git_hosts == ("github.com", "gitlab.acme.dev")


def test_explicit_config_overrides_defaults():
    p = DetectionPatterns.from_config(
        {"internal_domains": ["acme.dev"], "registry_hosts": ["registry.acme.dev"], "npm_scopes": ["acme"]},
        ["gitlab.acme.dev"],
    )
    assert p.internal_domains == ("acme.dev",)
    assert p.registry_hosts == ("registry.acme.dev",)
    assert p.npm_scopes == ("@acme",)  # @-normalized


def test_empty_patterns_never_match():
    p = DetectionPatterns()
    assert p.internal_url_re.search("https://anything.example.com/x") is None
    assert p.registry_re.search("registry.example.com/img") is None
    assert p.git_url_re.search("git+https://gitlab.example.com/a/b.git") is None
    assert not p.is_internal_npm("@acme/pkg")


def test_internal_url_re_matches_subdomains_and_bare_domains():
    p = DetectionPatterns(internal_domains=("acme.dev",))
    assert p.internal_url_re.search('x = "https://api.acme.dev/v1/things"')
    assert p.internal_url_re.search("acme.dev/path")
    assert p.internal_url_re.search("https://other.com/x") is None


def test_registry_strip_prefix():
    p = DetectionPatterns(registry_hosts=("registry.acme.dev",))
    assert p.strip_registry_prefix("registry.acme.dev/core/api:latest") == "core/api"
    assert p.strip_registry_prefix("docker.io/library/postgres:16") is None


def test_git_url_re_extracts_repo_path():
    p = DetectionPatterns(git_hosts=("gitlab.acme.dev",))
    m = p.git_url_re.search("git+https://gitlab.acme.dev/shared-libs/utils.git ")
    assert m and m.group(1) == "shared-libs/utils"


def test_is_internal_npm_requires_scope_prefix():
    p = DetectionPatterns(npm_scopes=("@acme",))
    assert p.is_internal_npm("@acme/ui-kit")
    assert not p.is_internal_npm("@acmeish/ui-kit")
    assert not p.is_internal_npm("left-pad")
