# Architecture & design rationale

## The two-workload split

```
analyzer (periodic)                                webapp container
  untangle all ──write──▶ graph.json ─────────serve──▶ nginx (static)
  (clone→analyze→report)  (frontend contract,           + Cytoscape UI
                           shared volume or URL)         single-screen graph
                       └─▶ dependency_report.json
                           (full internal artifact)
```

The system is deliberately two processes joined by **JSON files**:

- **Analyzer** — heavy and stateful-ish (needs `git`, disk, tokens, minutes of
  runtime) but **ephemeral**: it runs, writes the outputs, and exits (or sleeps
  until the next interval).
- **Webapp** — tiny, always-on, stateless: it serves static files plus
  `graph.json`. No tokens in the browser, no CORS, no analysis load.

The frontend contract is **`graph.json`** — a node/edge graph model with a
JSON Schema at `src/untangle/graph.schema.json`, built by `graph_contract.py`
as a trimmed projection of the analysis. The richer `dependency_report.json`
(typed in `report_schema.py`, `schema_version`) stays the analyzer's full
internal artifact and still feeds the markdown/mermaid/graphml outputs and
drift checks. Either side can be replaced or moved — compose service → CI job,
nginx → embedded in another dashboard — without touching the other.

## Where the analyzer runs

Compose-first: the default `docker-compose.yml` runs the analyzer on a sleep
loop (`RUN_INTERVAL`, daily) next to the webapp, sharing a report volume.
That's the simplest deployment that keeps itself fresh.

Alternative — **CI-scheduled**: run the analyzer as a scheduled CI job that
publishes the report to an artifact store (e.g. the GitLab generic Package
Registry), and give the webapp `REPORT_URL` so it pulls on start + on a timer
(`webapp/docker-entrypoint.sh`). This suits orgs that already have CI runners
and don't want an always-restarting analyzer container; see
`examples/gitlab-ci.yml`. The clone cache then needs a persistent host path on
a dedicated runner (CI cache zips are too slow for a multi-GB cache).

## Origins: where repos come from

Repo discovery sits behind a small provider interface
(`src/untangle/providers/`): **gitlab** (REST v4, self-hosted or gitlab.com),
**github** (org/user, GitHub Enterprise via `api_url`), and **static** (an
explicit list of git URLs — works with any host). Multiple mixed origins run
in one deployment; per-origin `include`/`exclude` regexes filter paths, and
cross-origin path collisions are skipped with a warning.

Branch discovery is uniform (`git ls-remote --symref`), and credentials travel
as per-process git env headers — never inside clone URLs, argv, or the cached
`.git/config`.

## How dependencies are discovered

Two layers, because much of the real coupling is undocumented:

1. **Declared** — ecosystem parsers (`src/untangle/parsers/`) read
   `pyproject.toml`/`requirements*.txt`, `package.json`, Dockerfiles &
   compose files, `.gitlab-ci.yml` includes/components/images, and Terraform
   `source`/backends. References matching the configured **detection
   patterns** (internal domains, git hosts, registry hosts, npm scopes — see
   `config.example/untangle.yml`) become typed edges directly.
2. **Undocumented** — scan source + `.env.*` templates for URLs on the
   internal domains. Each hit is resolved to an owning repo by a **route
   registry**: routes extracted from every repo (React Router, Express, C#
   WebAPI, ASP.NET, FastAPI/Flask) plus the manual hints in
   `config/prefixes.yml`, indexed for **longest-prefix matching**. Resolved
   hits become `service_call` edges; the rest are reported as undocumented
   refs to review.

The output is a directed graph of typed edges (`ci_include`, `git_dependency`,
`internal_npm_package`, `terraform`, `service_call`, …), a system-level
roll-up (`system_graph`), and shared-infra summaries (networks, databases,
registry images).

## The config files

Things that can't be derived from any API live as deploy-time YAML (see
`config.example/`, mounted or copied to `config/`):

- `untangle.yml` — title, origins, detection patterns.
- `prefixes.yml` — URL-prefix → repo overrides (fallback when routes can't be
  parsed, e.g. legacy .NET).
- `systems.yml` — product groupings for the dashboard. The analyzer **embeds**
  this into the report (`systems`), so the webapp is fully data-driven; when
  the file is absent, one system per top-level repo group is synthesized.

Because these drift as repos are renamed/added, every `analyze` run validates
them and reports drift (see [operations.md](operations.md)).

## Report shape

`dependency_report.json` top-level keys (typed in `report_schema.py`):

| Key | Contents |
|---|---|
| `schema_version` | bumped on breaking shape changes |
| `title` | deployment branding |
| `generated_at` | UTC ISO-8601 stamp |
| `systems` | groupings from `systems.yml`, or synthesized |
| `projects` | per-repo ecosystems + manifest/internal/undocumented deps + infra |
| `internal_graph` | `nodes` + typed, deduped `edges` |
| `system_graph` | system→system edges with per-type counts |
| `shared_infrastructure` | networks, databases, registry images |
| `config_drift` | stale prefix targets, unmapped/empty groups |
| `route_registry_summary`, `summary` | counts |

## Graph contract (`graph.json`)

The frontend reads `graph.json`, a projection of the report built by
`graph_contract.build_graph` (JSON Schema: `src/untangle/graph.schema.json`,
`version`). Top-level: `version`, `generatedAt`, `languages[]`, `systems[]`,
`nodes[]`, `edges[]`. Key derivations:

- **`kind`** — `repo` (leaf, no dependents → bundled in the UI), `anchor`
  (depended on within one system), or `hub` (depended on across **≥2 systems**;
  moved into the central `"shared"` cluster). The `shared:` config block in
  `untangle.yml` can force repos in/out of `hub` by path glob.
- **`language`** — the repo's primary ecosystem; colored via `languages.yml`.
- **`type`** — the icon, inferred from the repo name (+ ecosystem hint).
- **`edges[]`** — parallel analyzer edges between the same pair collapse into
  one edge whose `reasons[]` map analyzer edge types to
  `package|api|database|function|pipeline|config`. Direction is
  `source → target` = "source depends on target"; blast radius is the
  transitive incoming closure.

The client adds a small *derive* step on top (degrees, sizes, colors, icons,
the bundleable flag) in `webapp/js/data.js`.

## Future: code search

The analyzer's clone cache (`DATA_DIR/repos` on the `analyzer-data` volume) is
a ready-made corpus for code search. A future optional compose profile could
run [Zoekt](https://github.com/sourcegraph/zoekt) (`zoekt-git-index` +
`zoekt-webserver`) over that volume to add cross-repo search without a second
mirroring pipeline. Out of scope for now; noted so the volume layout stays
indexing-friendly.
