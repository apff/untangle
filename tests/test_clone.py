"""Clone orchestration: manifest shape, skip rules, and the failure-ratio gate."""

from __future__ import annotations

import json

import pytest

from untangle import clone
from untangle.config import Settings
from untangle.providers.static import StaticProvider


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(data_dir=tmp_path, max_clone_failure_ratio=0.5)


def _provider(*urls: str) -> StaticProvider:
    return StaticProvider(list(urls))


def test_run_requires_providers(settings):
    with pytest.raises(SystemExit, match="no origins configured"):
        clone.run(settings, [])


def test_run_writes_manifest_with_origin(settings, monkeypatch):
    monkeypatch.setattr(clone, "ls_remote_branches", lambda url, env=None: (["main"], "main"))
    monkeypatch.setattr(clone, "clone_repo", lambda s, url, branch, dest, env: True)

    rc = clone.run(settings, [_provider("https://h.dev/a/b.git")])
    assert rc == 0
    manifest = json.loads(settings.manifest_path.read_text())
    assert len(manifest) == 1
    entry = manifest[0]
    assert entry["path"] == "a/b"
    assert entry["branch"] == "main"
    assert entry["origin"] == "static"
    assert entry["id"] is None
    assert entry["all_branches"] == ["main"]


def test_run_respects_branch_priority(settings, monkeypatch):
    monkeypatch.setattr(
        clone, "ls_remote_branches", lambda url, env=None: (["master", "develop"], "master")
    )
    monkeypatch.setattr(clone, "clone_repo", lambda s, url, branch, dest, env: True)

    clone.run(settings, [_provider("https://h.dev/a/b.git")])
    manifest = json.loads(settings.manifest_path.read_text())
    assert manifest[0]["branch"] == "develop"


def test_run_fails_when_failure_ratio_exceeded(settings, monkeypatch):
    monkeypatch.setattr(clone, "ls_remote_branches", lambda url, env=None: (["main"], "main"))
    # 2 of 3 fail -> 67% > 50% tolerance
    monkeypatch.setattr(
        clone, "clone_repo", lambda s, url, branch, dest, env: url.endswith("ok.git")
    )

    rc = clone.run(
        settings,
        [_provider("https://h.dev/a/ok.git", "https://h.dev/b/bad.git", "https://h.dev/c/bad2.git")],
    )
    assert rc == 1
    # the successful repo is still in the manifest
    manifest = json.loads(settings.manifest_path.read_text())
    assert [e["path"] for e in manifest] == ["a/ok"]


def test_run_tolerates_failures_below_ratio(settings, monkeypatch):
    monkeypatch.setattr(clone, "ls_remote_branches", lambda url, env=None: (["main"], "main"))
    # 1 of 3 fails -> 33% <= 50% tolerance
    monkeypatch.setattr(
        clone, "clone_repo", lambda s, url, branch, dest, env: not url.endswith("bad.git")
    )

    rc = clone.run(
        settings,
        [_provider("https://h.dev/a/x.git", "https://h.dev/b/bad.git", "https://h.dev/c/y.git")],
    )
    assert rc == 0


def test_run_skips_repos_without_branches_and_isolates_errors(settings, monkeypatch):
    def fake_ls_remote(url, env=None):
        if "boom" in url:
            raise RuntimeError("network exploded")
        if "bare" in url:
            return [], None
        return ["main"], "main"

    monkeypatch.setattr(clone, "ls_remote_branches", fake_ls_remote)
    monkeypatch.setattr(clone, "clone_repo", lambda s, url, branch, dest, env: True)

    rc = clone.run(
        settings,
        [_provider("https://h.dev/a/x.git", "https://h.dev/b/bare.git", "https://h.dev/c/boom.git")],
    )
    assert rc == 0  # 1 cloned, 1 failed -> 50%, equal to (not above) the tolerance
    manifest = json.loads(settings.manifest_path.read_text())
    assert [e["path"] for e in manifest] == ["a/x"]


def test_dry_run_lists_without_cloning(settings, monkeypatch):
    monkeypatch.setattr(clone, "ls_remote_branches", lambda url, env=None: (["main"], "main"))

    def explode(*a, **k):
        raise AssertionError("clone_repo must not run in dry-run")

    monkeypatch.setattr(clone, "clone_repo", explode)
    rc = clone.run(settings, [_provider("https://h.dev/a/b.git")], dry_run=True)
    assert rc == 0
    manifest = json.loads(settings.manifest_path.read_text())
    assert manifest[0]["path"] == "a/b"
