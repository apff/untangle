"""Clone (or shallow-update) every discovered repo and write a manifest.

Shallow by default (``CLONE_DEPTH=1``): the analysis only ever reads the working
tree, so no git history is fetched. Updates are a depth-limited fetch + hard reset,
which transfers just the latest snapshot's deltas — cheap on the git hosts and
keeps the on-disk cache small. Set ``CLONE_DEPTH=0`` for full clones.

Repos come from the configured origin providers (``providers/``); branch lists
and default branches come from ``git ls-remote`` so the mechanics are identical
for every origin type. Credentials travel as per-process git env headers — they
never appear in URLs, argv, or the on-disk clone cache.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
from pathlib import Path

from .config import Settings
from .providers import Provider, RemoteRepo, discover_all, pick_branch

logger = logging.getLogger(__name__)


def _run_git(args: list[str], extra_env: dict[str, str] | None = None) -> subprocess.CompletedProcess:
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", **(extra_env or {})}
    return subprocess.run(["git", *args], capture_output=True, text=True, env=env)


def ls_remote_branches(clone_url: str, extra_env: dict[str, str] | None = None) -> tuple[list[str], str | None]:
    """Return (branch names, default branch) for a remote in one round-trip.

    ``--symref`` reports which branch HEAD points at; listing ``refs/heads/*``
    yields the branch names. Works uniformly for every provider — no per-host
    branch API needed.
    """
    result = _run_git(["ls-remote", "--symref", clone_url, "HEAD", "refs/heads/*"], extra_env)
    if result.returncode != 0:
        raise RuntimeError(f"ls-remote failed: {result.stderr.strip()}")
    branches: list[str] = []
    default: str | None = None
    for line in result.stdout.splitlines():
        if line.startswith("ref:"):
            # "ref: refs/heads/main\tHEAD"
            default = line.split("\t")[0].removeprefix("ref: refs/heads/").strip()
        else:
            _, _, ref = line.partition("\t")
            if ref.startswith("refs/heads/"):
                branches.append(ref.removeprefix("refs/heads/"))
    return branches, default


def clone_repo(
    settings: Settings, clone_url: str, branch: str, dest: Path, extra_env: dict[str, str]
) -> bool:
    """Clone a fresh repo or update an existing one to the tip of ``branch``."""
    depth = settings.clone_depth

    if dest.exists():
        logger.info("  already cloned, fetching latest...")
        fetch = ["-C", str(dest), "fetch"]
        if depth:
            fetch += ["--depth", str(depth)]
        fetch += ["origin", branch]
        result = _run_git(fetch, extra_env)
        if result.returncode != 0:
            logger.info("  fetch failed: %s", result.stderr.strip())
            return False
        # Hard-reset onto the fetched tip and drop stray files so the tree is
        # an exact, pristine snapshot of the remote branch.
        result = _run_git(["-C", str(dest), "reset", "--hard", "FETCH_HEAD"], extra_env)
        if result.returncode != 0:
            logger.info("  reset failed: %s", result.stderr.strip())
            return False
        _run_git(["-C", str(dest), "clean", "-fdx"], extra_env)  # non-fatal
        return True

    dest.parent.mkdir(parents=True, exist_ok=True)
    clone = ["clone"]
    if depth:
        clone += ["--depth", str(depth), "--single-branch"]
    clone += ["--branch", branch, clone_url, str(dest)]
    result = _run_git(clone, extra_env)
    if result.returncode != 0:
        logger.info("  clone failed: %s", result.stderr.strip())
        return False
    return True


def _manifest_entry(repo: RemoteRepo, branch: str, branches: list[str], default: str | None) -> dict:
    return {
        "id": repo.id,
        "path": repo.path,
        "name": repo.name,
        "web_url": repo.web_url,
        "branch": branch,
        "default_branch": repo.default_branch or default,
        "all_branches": branches,
        "description": repo.description,
        "topics": list(repo.topics),
        "last_activity_at": repo.last_activity_at,
        "origin": repo.origin,
    }


def run(settings: Settings, providers: list[Provider], dry_run: bool = False) -> int:
    if not providers:
        raise SystemExit(
            "ERROR: no origins configured. Add an `origins:` list to config/untangle.yml, "
            "or set GITLAB_URL (+token), GITHUB_ORG/GITHUB_USER, or GIT_REPOS in the environment."
        )
    logger.info("Origins: %s", ", ".join(p.name for p in providers))
    logger.info("Repos dir: %s", settings.repos_dir)
    logger.info(
        "Clone mode: %s\n",
        f"shallow depth={settings.clone_depth}" if settings.clone_depth else "full",
    )

    discovered = discover_all(providers)
    logger.info("Found %d repos across %d origin(s)\n", len(discovered), len(providers))

    manifest: list[dict] = []
    cloned = skipped = failed = 0
    failures: list[tuple[str, str]] = []

    for provider, repo in sorted(discovered, key=lambda pr: pr[1].path):
        dest = settings.repos_dir / repo.path

        # Isolate each repo: one network hiccup or clone failure must not abort
        # the whole run over the other repos.
        try:
            if repo.empty:
                logger.info("[SKIP] %s (empty repo)", repo.path)
                skipped += 1
                continue

            extra_env = provider.git_env(repo)
            branches, remote_default = ls_remote_branches(repo.clone_url, extra_env)
            if not branches:
                logger.info("[SKIP] %s (no branches)", repo.path)
                skipped += 1
                continue

            branch = pick_branch(
                settings.branch_priority, branches, repo.default_branch or remote_default
            )
            if not branch:
                logger.info("[SKIP] %s (no suitable branch)", repo.path)
                skipped += 1
                continue

            entry = _manifest_entry(repo, branch, branches, remote_default)

            if dry_run:
                logger.info("[DRY-RUN] %s -> branch: %s", repo.path, branch)
                manifest.append(entry)
                continue

            logger.info("[CLONE] %s -> branch: %s", repo.path, branch)
            if clone_repo(settings, repo.clone_url, branch, dest, extra_env):
                manifest.append(entry)
                cloned += 1
            else:
                failed += 1
                failures.append((repo.path, "clone/fetch failed"))
        except Exception as exc:  # noqa: BLE001 - keep going on per-repo errors
            logger.info("[ERROR] %s: %s", repo.path, exc)
            failed += 1
            failures.append((repo.path, str(exc)))
            continue

    settings.repos_dir.mkdir(parents=True, exist_ok=True)
    settings.manifest_path.write_text(json.dumps(manifest, indent=2, default=str))
    logger.info("\nManifest written to %s", settings.manifest_path)

    logger.info("\n=== Summary ===")
    if dry_run:
        logger.info("  projects found: %d", len(manifest))
        logger.info("  skipped: %d", skipped)
        return 0

    logger.info("  cloned/updated: %d", cloned)
    logger.info("  skipped: %d", skipped)
    logger.info("  failed: %d", failed)
    if failures:
        logger.info("\n  Failed repos:")
        for fpath, err in failures:
            logger.info("    - %s: %s", fpath, err)

    # Fail the run only on a *significant* share of failures (likely a host /
    # network outage), not on the odd broken repo — see Settings.max_clone_failure_ratio.
    attempted = cloned + failed
    ratio = failed / attempted if attempted else 0.0
    if ratio > settings.max_clone_failure_ratio:
        logger.error(
            "\nERROR: clone failure ratio %.0f%% exceeds %.0f%% (%d/%d) — failing the run.",
            ratio * 100, settings.max_clone_failure_ratio * 100, failed, attempted,
        )
        return 1
    if failed:
        logger.info(
            "\n  %d/%d failed (%.0f%%), within the %.0f%% tolerance — continuing.",
            failed, attempted, ratio * 100, settings.max_clone_failure_ratio * 100,
        )
    return 0
