# Contributing

A small tool with a small maintainer team — keep changes simple and tested.

## Setup

Requirements: Python 3.12+, [uv](https://github.com/astral-sh/uv), git.

```bash
uv sync                  # install package + dev tools
cp .env.example .env     # configure an origin for steps that clone
```

See [docs/local-development.md](docs/local-development.md) for the full dev
loop and the token-free inner loop.

## Before you push

```bash
uv run ruff check .      # lint (ruff config in pyproject.toml; `--fix` to autofix)
uv run pytest -q         # unit tests
```

Both run in CI on every push and pull request, so a green local run means a
green pipeline.

## Conventions

- **Python**: 3.12+, ruff-clean (line length 100, rules `E,F,I,UP,B`). Match the
  surrounding style. Parsers must be defensive — warn and return empty on
  malformed input, never raise, so one bad repo can't abort a whole-org run.
- **Config, not code**: org-specific data (hosts, scopes, systems, prefixes)
  lives in the `config/` YAMLs and `DetectionPatterns`, never hardcoded.
- **Tests**: add a case for new parsers, providers, resolution logic, or drift
  behavior. Fixture-based tests write samples to `tmp_path`; use the neutral
  `patterns` fixture from `tests/conftest.py`.
- **Frontend**: vanilla JS native ES modules, no build step. The webapp is
  data-driven from the report JSON; don't hardcode repo/system data in JS.
- **Report shape**: `src/untangle/report_schema.py` is the contract — document
  changes there and bump `SCHEMA_VERSION` on breaking changes.

## Where things live

| Change | Files |
|---|---|
| New ecosystem parser | one module in `src/untangle/parsers/` + registry entry — see [docs/extending.md](docs/extending.md) |
| New origin type | one module in `src/untangle/providers/` + `build_providers` |
| Route extraction for a framework | `src/untangle/routes.py` |
| What counts as "internal" | `src/untangle/patterns.py` + `config.example/untangle.yml` |
| Repo/system mappings | deploy-time `config/*.yml` (templates in `config.example/`) |
| Webapp UI | `webapp/js/` (state/data/graph/ui modules + `pages/`) |
| CI | `.github/workflows/ci.yml`; GitLab example in `examples/gitlab-ci.yml` |

## Commits & PRs

- Branch off `main`; keep PRs focused.
- Note any change to the report JSON shape — the webapp and any external
  consumers depend on it.
