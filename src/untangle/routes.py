"""Route registry: extract route definitions from each repo and resolve URL refs.

Builds a mapping of URL path prefixes -> owning repos based on:
- React Router definitions (<Route path={`${process.env.PUBLIC_URL}/...`}>)
- Express.js mounts and endpoints (app.use/get/post, router.use/get/post)
- C# WebAPI controllers (class name + method name routing)
- ASP.NET .aspx file paths
- FastAPI/Flask routes (@router.get, @app.get)
- Manual prefix hints (well-known service paths -> repo)

Then resolves undocumented URL references by longest-prefix matching.
"""

from __future__ import annotations

import re
from pathlib import Path
from urllib.parse import urlparse

from .fswalk import find_by_extensions as find_by_ext
from .fswalk import read_text_capped

# Manual URL-prefix -> repo hints live in config/prefixes.yml; the caller loads
# them (static_config.load_prefixes) and passes them to build_prefix_index. They
# supplement automatic route extraction and serve as a fallback when extraction
# isn't possible (e.g. .NET projects we don't fully parse).


# ---------------------------------------------------------------------------
# React Router extraction
# ---------------------------------------------------------------------------

REACT_ROUTE_RE = re.compile(
    r"""<Route\s+[^>]*?\bpath=\{?\s*[`'"]"""  # opener
    r"""(?:\$\{[^}]*\})?"""                     # optional ${process.env.PUBLIC_URL} or similar
    r"""([^`'"\}]+)"""                          # the path
    r"""[`'"]""",
    re.IGNORECASE,
)


def extract_react_routes(repo_dir: Path) -> list[str]:
    routes = []
    for f in find_by_ext(repo_dir, {".js", ".jsx", ".tsx", ".ts"}):
        # Heuristic: only scan files likely to contain routes
        name = f.name.lower()
        if "router" not in name and "route" not in name and "app." not in name and "index." not in name:
            continue
        content = read_text_capped(f)
        if content is None:
            continue
        if "<Route" not in content:
            continue
        for m in REACT_ROUTE_RE.finditer(content):
            path = m.group(1).strip()
            if path and not path.startswith("http"):
                # Normalize: strip leading/trailing slashes, drop :params
                routes.append(_normalize_path(path))
    return list({r for r in routes if r})


# ---------------------------------------------------------------------------
# Express.js extraction
# ---------------------------------------------------------------------------

EXPRESS_ROUTE_RE = re.compile(
    r"""(?:app|router)\s*\.\s*(use|get|post|put|delete|patch)\s*\(\s*['"]([^'"]+)['"]""",
    re.IGNORECASE,
)


def extract_express_routes(repo_dir: Path) -> list[str]:
    routes = []
    for f in find_by_ext(repo_dir, {".js", ".ts"}):
        content = read_text_capped(f)
        if content is None:
            continue
        if "app." not in content and "router." not in content:
            continue
        for m in EXPRESS_ROUTE_RE.finditer(content):
            path = m.group(2).strip()
            if path and path != "/" and not path.startswith("http"):
                routes.append(_normalize_path(path))
    return list({r for r in routes if r})


# ---------------------------------------------------------------------------
# C# WebAPI extraction (controller name + method name)
# ---------------------------------------------------------------------------

CS_CONTROLLER_RE = re.compile(
    r"""(?:public\s+)?(?:partial\s+)?class\s+(\w+?)Controller\b""",
)
CS_METHOD_RE = re.compile(
    r"""\[\s*Http(?:Get|Post|Put|Delete|Patch)[^\]]*\]\s*"""  # attribute
    r"""(?:\[[^\]]*\]\s*)*"""                                   # other attributes (Route, etc.)
    r"""public\s+(?:async\s+)?\w+(?:<[\w\s,]+>)?\s+(\w+)\s*\(""",
    re.IGNORECASE,
)
CS_ROUTE_ATTR_RE = re.compile(
    r"""\[\s*Route\s*\(\s*"([^"]+)"\s*\)\s*\]""",
    re.IGNORECASE,
)


def extract_csharp_routes(repo_dir: Path) -> list[str]:
    routes = []
    for f in find_by_ext(repo_dir, {".cs"}):
        content = read_text_capped(f)
        if content is None:
            continue
        controller_match = CS_CONTROLLER_RE.search(content)
        if not controller_match:
            continue
        controller_name = controller_match.group(1)
        # Each method becomes a route: /<ControllerName>/<MethodName>
        for m in CS_METHOD_RE.finditer(content):
            method_name = m.group(1)
            routes.append(_normalize_path(f"{controller_name}/{method_name}"))
        # Also any explicit [Route("...")] attributes
        for m in CS_ROUTE_ATTR_RE.finditer(content):
            routes.append(_normalize_path(m.group(1)))
    return list({r for r in routes if r})


# ---------------------------------------------------------------------------
# ASP.NET .aspx files
# ---------------------------------------------------------------------------

def extract_aspx_routes(repo_dir: Path) -> list[str]:
    routes = []
    for f in find_by_ext(repo_dir, {".aspx", ".ashx", ".asmx"}):
        rel = f.relative_to(repo_dir)
        # Use the file path relative to the repo root as the route
        routes.append(_normalize_path(str(rel)))
    return list({r for r in routes if r})


# ---------------------------------------------------------------------------
# FastAPI / Flask
# ---------------------------------------------------------------------------

FASTAPI_ROUTE_RE = re.compile(
    r"""@(?:router|app)\s*\.\s*(get|post|put|delete|patch)\s*\(\s*['"]([^'"]+)['"]""",
    re.IGNORECASE,
)
FASTAPI_PREFIX_RE = re.compile(
    r"""APIRouter\s*\([^)]*?prefix\s*=\s*['"]([^'"]+)['"]""",
    re.IGNORECASE,
)
FLASK_ROUTE_RE = re.compile(
    r"""@(?:app|bp|blueprint)\s*\.\s*route\s*\(\s*['"]([^'"]+)['"]""",
    re.IGNORECASE,
)


def extract_python_routes(repo_dir: Path) -> list[str]:
    routes = []
    for f in find_by_ext(repo_dir, {".py"}):
        content = read_text_capped(f)
        if content is None:
            continue
        prefix_match = FASTAPI_PREFIX_RE.search(content)
        prefix = prefix_match.group(1).rstrip("/") if prefix_match else ""
        for m in FASTAPI_ROUTE_RE.finditer(content):
            path = m.group(2).strip()
            full = (prefix + path) if path.startswith("/") else f"{prefix}/{path}"
            routes.append(_normalize_path(full))
        for m in FLASK_ROUTE_RE.finditer(content):
            routes.append(_normalize_path(m.group(1)))
    return list({r for r in routes if r})


# ---------------------------------------------------------------------------
# Normalization
# ---------------------------------------------------------------------------

def _normalize_path(path: str) -> str:
    """Normalize a route path to a comparable form: lowercase, no params, no extension."""
    p = path.strip()
    p = p.strip("/")
    # Drop query params and fragments
    p = p.split("?")[0].split("#")[0]
    # Strip parameter placeholders: :idEvent, {idEvent}, <idEvent>
    p = re.sub(r":[\w_]+", ":x", p)
    p = re.sub(r"\{[^}]*\}", ":x", p)
    p = re.sub(r"<[^>]*>", ":x", p)
    return p.lower()


# ---------------------------------------------------------------------------
# URL resolution
# ---------------------------------------------------------------------------

def normalize_url_to_path(url: str, internal_hosts: tuple[str, ...] | list[str]) -> str | None:
    """Extract the URL path component, normalized for matching."""
    u = url.strip().lower()
    # Strip quoting artifacts
    u = u.rstrip("\"'`,);]}>")
    # Skip image/static-asset references
    if any(u.endswith(ext) for ext in (".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico", ".css", ".js", ".woff", ".woff2", ".ttf")):
        return None
    if not any(h in u for h in internal_hosts):
        return None
    try:
        parsed = urlparse(u if u.startswith("http") else f"http://{u}")
    except Exception:
        return None
    path = parsed.path.strip("/")
    if not path:
        return None
    # Drop common dead-end segments
    path = path.split("?")[0].split("#")[0]
    return _normalize_path(path)


def build_route_registry(repo_dirs: dict[str, Path]) -> dict[str, list[tuple[str, str]]]:
    """Build a registry mapping each repo to its discovered routes.

    Returns dict {repo_path: [(route, source_kind), ...]}.
    Also returns a prefix lookup table for fast resolution.
    """
    registry: dict[str, list[tuple[str, str]]] = {}
    for repo_path, repo_dir in repo_dirs.items():
        if not repo_dir.exists():
            continue
        all_routes: list[tuple[str, str]] = []
        for route in extract_react_routes(repo_dir):
            all_routes.append((route, "react"))
        for route in extract_express_routes(repo_dir):
            all_routes.append((route, "express"))
        for route in extract_csharp_routes(repo_dir):
            all_routes.append((route, "csharp"))
        for route in extract_aspx_routes(repo_dir):
            all_routes.append((route, "aspx"))
        for route in extract_python_routes(repo_dir):
            all_routes.append((route, "python"))
        if all_routes:
            registry[repo_path] = all_routes
    return registry


# Single-segment route prefixes too generic to identify a repo on their own:
# almost every backend mounts `/api`, `/admin`, `/v1`… so a bare one of these
# would capture every `host/api/...` URL (e.g. the GitLab API `gitlab.host/api/v4`)
# and pin it to whichever repo happened to declare that route. Auto-discovered
# routes matching these are dropped from the index; multi-segment routes
# (`api/users`) and operator-supplied prefixes.yml hints are unaffected.
GENERIC_PREFIXES = frozenset({
    "api", "admin", "v1", "v2", "v3", "v4", "public", "static", "assets",
    "auth", "login", "logout", "health", "healthz", "status", "ping",
    "metrics", "docs", "swagger", "graphql", "ws", "internal",
})


def build_prefix_index(registry: dict[str, list[tuple[str, str]]], prefixes: dict[str, str]) -> dict[str, str]:
    """Build a flat prefix -> repo index for longest-prefix matching.

    Each route in the registry becomes a possible prefix. When multiple repos
    declare the same prefix, prefer the one whose route is longer (more specific).
    """
    prefix_to_repo: dict[str, tuple[str, int]] = {}
    # First, seed with manual hints (config/prefixes.yml). These are operator
    # intent, so they are kept even when generic.
    for prefix, repo in prefixes.items():
        prefix_to_repo[_normalize_path(prefix)] = (repo, len(prefix))
    # Then merge in discovered routes (overrides hints if more specific),
    # skipping bare generic prefixes that can't identify a repo on their own.
    for repo, routes in registry.items():
        for route, _kind in routes:
            if route in GENERIC_PREFIXES:
                continue
            existing = prefix_to_repo.get(route)
            if existing is None or len(route) > existing[1]:
                prefix_to_repo[route] = (repo, len(route))
    return {p: r for p, (r, _) in prefix_to_repo.items()}


def resolve_url_to_repo(url: str, prefix_index: dict[str, str], internal_hosts: tuple[str, ...] | list[str]) -> str | None:
    """Resolve a URL to an owning repo using longest-prefix match."""
    path = normalize_url_to_path(url, internal_hosts)
    if not path:
        return None
    # Longest-prefix match by walking down path segments. Bare generic segments
    # (`api`, `admin`, …) are kept out of the index at build time unless an
    # operator pinned one in prefixes.yml, so a generic key here is intentional.
    segments = path.split("/")
    for i in range(len(segments), 0, -1):
        candidate = "/".join(segments[:i])
        if candidate in prefix_index:
            return prefix_index[candidate]
    return None
