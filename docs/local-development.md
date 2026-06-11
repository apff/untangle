# Local development

Everything runs from a normal Python checkout.

## Setup

Requirements: Python 3.12+, [uv](https://github.com/astral-sh/uv), git.

```bash
git clone <this repo> && cd untangle
cp .env.example .env          # configure at least one origin (see below)
uv sync                       # installs the package + dev tools (ruff, pytest)
```

`.env` is loaded automatically by the CLI (`cli.py` calls `load_dotenv()`); it's
gitignored. In CI/containers the same values come from environment variables, so
`.env` is a local-only convenience.

The fastest origin for hacking on the tool itself is a couple of public repos:

```bash
# .env
GIT_REPOS=https://github.com/pallets/click.git,https://github.com/psf/requests.git
```

## The pipeline, step by step

`untangle all` is just `clone → analyze → report`. Run them individually
while developing:

```bash
uv run untangle clone --dry-run   # list repos + chosen branches, clone nothing
uv run untangle clone             # shallow-clone/update every repo into data/repos
uv run untangle analyze           # parse repos -> dependency_report.json + graph.json
uv run untangle report            # render REPORT.md + architecture.mmd + .graphml
```

Outputs (all under `DATA_DIR`, default `./data`):

```
data/repos/manifest.json              repo list + chosen branch (written by clone)
data/repos/<group>/<repo>/            shallow working trees
data/analysis/graph.json              the graph the webapp consumes (contract)
data/analysis/dependency_report.json  full internal artifact (feeds report outputs)
data/analysis/REPORT.md               human-readable summary (incl. config drift)
data/analysis/architecture.mmd        Mermaid diagram
data/analysis/architecture.graphml    GraphML for Gephi/yEd
```

## Working without tokens

Only `clone` talks to the origins. Once `data/repos` exists, you can iterate on
the analysis offline:

```bash
uv run untangle analyze   # and report — no origin credentials required
```

This is the fast inner loop for changing parsers, route resolution, or the
config: re-run `analyze` against the repos you already cloned and diff the JSON.

## Serving the webapp locally

The frontend is static and reads `webapp/data/graph.json`:

```bash
WEBAPP_DATA_DIR=webapp/data uv run untangle analyze   # mirror graph.json into the web root
python3 -m http.server 8080 --directory webapp        # open http://localhost:8080
```

Or run the full containerized stack (analyzer loop + webapp on a shared volume):

```bash
docker compose up -d --build          # webapp on :8080, analyzer runs + sleeps
docker compose logs -f analyzer       # watch the first run
```

## Editing the deploy-time config

Copy `config.example/` to `config/` (gitignored) and edit:

- `config/untangle.yml` — title, origins, detection patterns.
- `config/prefixes.yml` — URL-prefix → owning-repo overrides used when a service
  URL can't be resolved from extracted routes.
- `config/systems.yml` — the system groupings (name, groups, tier, color) shown
  on the dashboard.

Edit the YAML (not the Python/JS), then re-run `analyze`. Every run prints a
**Config drift** section flagging entries that no longer match the live repos —
see [extending.md](extending.md) for what each warning means.

The loader resolves `UNTANGLE_CONFIG_DIR` → `<repo>/config` →
`<repo>/config.example`, in that order.

## Lint & tests

```bash
uv run ruff check .     # lint (and `ruff check --fix .` to autofix)
uv run pytest -q        # unit tests: config, patterns, providers, parsers, routes, clone, report
```

Both run in CI on every push/PR. Match the existing style (ruff config is in
`pyproject.toml`).
