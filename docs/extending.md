# Extending the analyzer

Three common changes: maintaining the config hints, teaching the analyzer a
new ecosystem, and adding route extraction for a framework.

## Maintaining `config/prefixes.yml`

Hints that map a URL prefix to the repo that owns it. They supplement automatic
route extraction and are the fallback when a route can't be parsed (e.g. legacy
.NET). Resolution is **longest-prefix wins**, and a discovered route overrides a
hint when it's more specific.

```yaml
prefixes:
  api/billing: platform/billing-service   # https://example.com/api/billing/... -> platform/billing-service
  shop: storefront/shop-frontend
```

Add an entry when an internal URL keeps showing up under "undocumented refs" but
should resolve to a known repo. Keys are matched after normalization (lowercased,
params stripped) — see `routes.py:_normalize_path`.

## Maintaining `config/systems.yml`

The product groupings shown on the dashboard. Each system bundles one or more
top-level repo groups (the part before the first `/` of a repo path):

```yaml
systems:
  platform:
    name: Core Platform
    groups: [platform, core-services]
    description: Shared services and orchestration
    tier: primary               # primary | secondary
    color: '#6c8ebf'
```

When a new top-level group appears, add it to a system (new or existing). The
analyzer embeds this file into the report, so the webapp updates with no JS
change. Without the file, untangle synthesizes one system per group.

## Reading the config-drift warnings

`analyze` validates both files against the live repo set on every run:

- **prefix hints pointing at missing repos** — the target was renamed/deleted;
  fix or drop the `prefixes.yml` entry.
- **repo groups not mapped to any system** — a repo's top-level group is missing
  from `systems.yml`; add it so the repo shows on the dashboard.
- **system groups with no repos** — a group in `systems.yml` is stale; remove it.

The logic lives in `src/untangle/drift.py`; the warnings print to the run log
and into `REPORT.md`. They never fail the run — they're a to-do list.

## Adding a new ecosystem parser

Parsers are pluggable: one module per ecosystem in `src/untangle/parsers/`,
registered in `parsers/__init__.py`. To support Go modules, Cargo, Maven, …:

1. **Create `src/untangle/parsers/<ecosystem>.py`** exposing two attributes
   (see `parsers/base.py` for the contract and `parsers/nodejs.py` for the
   smallest example):

   ```python
   name = "golang"

   def parse(repo_dir: Path, patterns: DetectionPatterns) -> ParseResult:
       ...
   ```

   Fill the `ParseResult`: `ecosystems` (tag the project), `manifest`
   (section → entries for display), and `internal` (typed internal dependency
   records). Use `fswalk.find_files`/`read_text_capped` for safe file access,
   and **warn, don't raise** on malformed input (`logger.warning`) so one bad
   repo can't abort the run.

2. **Register it**: add the module to `PARSERS` in `parsers/__init__.py`.

3. **Detect internal references** with the injected `patterns`
   (`patterns.matches_git_host(raw)`, `patterns.registry_re`,
   `patterns.is_internal_npm(name)`, …) — never hardcode hosts. Edge targets
   that name a known repo path (or an internal URL/image) are resolved into
   graph edges by `graph.py` automatically.

4. **Style the edge** (optional): add the new `type` to `EDGE_STYLES` in
   `webapp/js/config.js` and `edge_styles` in `report.py:generate_mermaid`
   so it renders distinctly.

5. **Test it**: add a fixture-based case to `tests/test_analyze.py` (write a
   sample manifest to `tmp_path`, assert parsed deps and the resolved edge
   type — the `patterns` fixture in `tests/conftest.py` provides neutral
   hosts).

## Adding route extraction for a new framework

To resolve undocumented URLs for a framework not yet covered, add an
`extract_<framework>_routes(repo_dir) -> list[str]` in `routes.py` and call it
from `build_route_registry`. Return normalized paths (`_normalize_path`). Keep
it heuristic and cheap — it runs over every file in every repo.

Heads-up on the existing heuristics: the C# extractor assumes
controller-name/method-name routing conventions and the ASP.NET extractor maps
`.aspx`/`.ashx` file paths to routes. They're intentionally approximate —
false negatives surface as "undocumented refs", which `prefixes.yml` can patch.
