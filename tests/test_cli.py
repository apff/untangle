"""CLI orchestration: the `all` pipeline aborts on upstream failures."""

from __future__ import annotations

import pytest

from untangle import cli


@pytest.fixture(autouse=True)
def _isolated_env(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("UNTANGLE_CONFIG_DIR", str(tmp_path / "no-config"))
    for var in ("GITLAB_URL", "GITLAB_API_TOKEN", "GITLAB_TOKEN", "GITHUB_ORG", "GITHUB_USER", "GITHUB_TOKEN", "GIT_REPOS"):
        monkeypatch.delenv(var, raising=False)


def test_all_aborts_when_clone_fails(monkeypatch):
    calls = []
    monkeypatch.setattr(cli.clone, "run", lambda settings, providers, dry_run=False: calls.append("clone") or 1)
    monkeypatch.setattr(cli.analyze, "run", lambda settings, patterns: calls.append("analyze") or 0)

    assert cli.main(["all"]) == 1
    assert calls == ["clone"]


def test_all_runs_full_pipeline_on_success(monkeypatch):
    calls = []
    monkeypatch.setattr(cli.clone, "run", lambda settings, providers, dry_run=False: calls.append("clone") or 0)
    monkeypatch.setattr(cli.analyze, "run", lambda settings, patterns: calls.append("analyze") or 0)
    monkeypatch.setattr(cli.report, "run", lambda settings: calls.append("report") or 0)

    assert cli.main(["all"]) == 0
    assert calls == ["clone", "analyze", "report"]


def test_all_skip_report(monkeypatch):
    calls = []
    monkeypatch.setattr(cli.clone, "run", lambda settings, providers, dry_run=False: calls.append("clone") or 0)
    monkeypatch.setattr(cli.analyze, "run", lambda settings, patterns: calls.append("analyze") or 0)
    monkeypatch.setattr(cli.report, "run", lambda settings: calls.append("report") or 0)

    assert cli.main(["all", "--skip-report"]) == 0
    assert calls == ["clone", "analyze"]
