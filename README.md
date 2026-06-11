# untangle

<img src="webapp/img/logo.png" alt="untangle logo" width="140" align="right">

Map and explore the dependencies **between** your repositories — including the
ones nobody documented.

untangle clones every repo from your configured origins (a GitLab instance, a
GitHub org/user, an explicit list of git URLs — or any mix), statically maps
the dependencies between them, and serves an interactive visualization:

- **Declared dependencies**: scoped npm packages, git dependencies in
  pyproject/requirements/package.json, internal container images in
  Dockerfiles/compose files, GitLab CI includes/components, Terraform module
  sources.
- **Undocumented dependencies**: hardcoded internal URLs found in source code
  and env templates, resolved to the repos that *serve* those routes by
  extracting route definitions (React Router, Express, FastAPI/Flask, C#
  WebAPI, ASP.NET) from every repo.
- **Shared infrastructure**: databases hinted in env templates, shared compose
  networks, registry images.

The result is an explorable graph of systems → repos → edges, with collapsible
groups, per-node hiding, edge-type filters, and shareable view URLs.

## Quickstart

Requirements: Docker + Compose. Point untangle at some repos and start it:

```bash
cp .env.example .env
# edit .env — one line is enough, e.g.:
#   GIT_REPOS=https://github.com/pallets/click.git,https://github.com/psf/requests.git
# or GITHUB_ORG=my-org (+ GITHUB_TOKEN), or GITLAB_URL=… + GITLAB_API_TOKEN=…

docker compose up -d --build
```

Open <http://localhost:8080>. The analyzer clones and analyzes in the
background (watch with `docker compose logs -f analyzer`), publishes the
report to a shared volume, and re-runs daily (`RUN_INTERVAL`). The webapp
serves whatever the latest successful run produced.

### Without Docker

Requirements: Python 3.12+, [uv](https://github.com/astral-sh/uv), git.

```bash
cp .env.example .env                                  # configure an origin
uv sync
WEBAPP_DATA_DIR=webapp/data uv run untangle all       # clone -> analyze -> report
python3 -m http.server 8080 --directory webapp        # http://localhost:8080
```

## Architecture

Two workloads joined by JSON over a shared volume:

```
analyzer (heavy, periodic)                    webapp (tiny, always-on)
  untangle all ──┐
   ├─ clone (shallow, all origins)            ┌─ nginx serves static app + graph.json
   ├─ analyze (parsers + route extraction)    │
   ├─ report  (markdown/mermaid/graphml)      │   single-screen interactive graph:
   └─ graph.json (frontend contract) ─────────┘   blast-radius, shared-components
  writes to ─────┴──── shared volume ─────────┘   cluster, consumer bundles
```

- **Analyzer** — needs `git`, network, and disk; ephemeral. The clone cache is
  persistent and shallow (`CLONE_DEPTH=1`), so re-runs transfer only deltas. It
  writes `dependency_report.json` (the full internal artifact, also feeding the
  markdown/mermaid/graphml outputs) **and** `graph.json` — a trimmed projection
  that is the frontend's data contract (schema: `src/untangle/graph.schema.json`).
- **Webapp** — a static nginx container (vanilla JS + Cytoscape, no build step,
  no external CDN). One full-viewport graph screen with a details panel: a
  central Shared Components cluster, per-system consumer bundles, hover
  path-tracing, click-to-focus, and blast-radius highlighting ("if this breaks,
  what else breaks?"), in the Midnight Refined theme (dark + light). Reads only
  `graph.json`; as an alternative to the shared volume it can **pull** a
  published `graph.json` from a URL (`REPORT_URL`) — useful when the analyzer
  runs in CI instead (see `examples/gitlab-ci.yml`).

Details and rationale: [docs/architecture.md](docs/architecture.md).

## Configuration

Zero config works: with only an origin in `.env`, systems are synthesized from
top-level repo groups and detection patterns derive from the origin hosts.

For more, copy `config.example/` to `config/` (gitignored) and edit — or mount
your config dir to `/app/config` in Docker:

| File | Purpose |
|---|---|
| `untangle.yml` | Title, multiple mixed origins (with include/exclude filters), detection patterns (internal domains, git hosts, registry hosts, npm scopes), and the `shared:` include/exclude overrides for the Shared Components cluster |
| `systems.yml` | Curated system groupings, names, colors for the graph's clusters |
| `languages.yml` | Per-language colors for the graph legend and node orbs |
| `prefixes.yml` | Manual URL-prefix → owning-repo hints where route extraction can't see |

Environment variables are documented in [.env.example](.env.example); the
private-overlay pattern for keeping org config out of a public deployment repo
is in [docs/deployment.md](docs/deployment.md).

## Documentation

| Doc | What's in it |
|---|---|
| [docs/local-development.md](docs/local-development.md) | Dev loop, running each step, serving the webapp |
| [docs/deployment.md](docs/deployment.md) | Compose deployment, the config overlay pattern, CI-based analyzer |
| [docs/operations.md](docs/operations.md) | Troubleshooting, staleness badge, config-drift warnings |
| [docs/architecture.md](docs/architecture.md) | The JSON contract, URL→repo resolution, design rationale |
| [docs/extending.md](docs/extending.md) | Adding an ecosystem parser or route extractor |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Setup, lint/test, conventions |

## License

[MIT](LICENSE)
