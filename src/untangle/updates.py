"""Optional "newer release available" check against the project's GitHub repo.

Runs server-side in the analyzer (never in the browser), so viewers make no
external calls and airgapped deployments keep working. Every failure mode —
disabled in config, offline, no releases published yet, rate-limited, malformed
response — degrades silently to ``None`` and the footer simply omits the update
hint. The version comparison itself lives in the frontend (it has both strings).
"""

from __future__ import annotations

import logging

import httpx

logger = logging.getLogger(__name__)

# The canonical Untangle repository; overridable via untangle.yml > update_check.repo.
DEFAULT_REPO = "apff/untangle"


def latest_release(repo: str = DEFAULT_REPO, timeout: float = 5.0) -> dict | None:
    """Return ``{"version", "url"}`` for the repo's latest GitHub release, or None.

    ``version`` has any leading ``v`` stripped so it compares cleanly against
    ``__version__``. Never raises — returns ``None`` on any network/HTTP/parse
    issue (including a repo with no releases yet, which GitHub answers with 404).
    """
    url = f"https://api.github.com/repos/{repo}/releases/latest"
    try:
        resp = httpx.get(
            url,
            timeout=timeout,
            headers={"Accept": "application/vnd.github+json", "User-Agent": "untangle"},
            follow_redirects=True,
        )
    except httpx.HTTPError as exc:
        logger.debug("update check: request failed: %s", exc)
        return None
    if resp.status_code != 200:
        logger.debug("update check: HTTP %s for %s", resp.status_code, url)
        return None
    try:
        data = resp.json()
    except ValueError:
        return None
    tag = (data.get("tag_name") or "").lstrip("vV")
    if not tag:
        return None
    return {"version": tag, "url": data.get("html_url") or f"https://github.com/{repo}/releases"}
