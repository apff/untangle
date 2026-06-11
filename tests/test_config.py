from __future__ import annotations

from untangle.config import Settings


def test_derived_paths(tmp_path):
    s = Settings(data_dir=tmp_path)
    assert s.repos_dir == tmp_path / "repos"
    assert s.analysis_dir == tmp_path / "analysis"
    assert s.manifest_path == tmp_path / "repos" / "manifest.json"
    assert s.report_path == tmp_path / "analysis" / "dependency_report.json"


def test_from_env_defaults(monkeypatch, tmp_path):
    for key in ("WEBAPP_DATA_DIR", "CLONE_DEPTH", "BRANCH_PRIORITY", "MAX_CLONE_FAILURE_RATIO"):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("DATA_DIR", str(tmp_path))

    s = Settings.from_env()
    assert s.data_dir == tmp_path.resolve()
    assert s.clone_depth == 1
    assert s.branch_priority == ("develop", "main", "master")
    assert s.webapp_data_dir is None
    assert s.max_clone_failure_ratio == 0.15


def test_from_env_overrides(monkeypatch, tmp_path):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("CLONE_DEPTH", "0")
    monkeypatch.setenv("BRANCH_PRIORITY", "main, master")
    monkeypatch.setenv("MAX_CLONE_FAILURE_RATIO", "0.5")

    s = Settings.from_env()
    assert s.clone_depth == 0
    assert s.branch_priority == ("main", "master")
    assert s.max_clone_failure_ratio == 0.5
