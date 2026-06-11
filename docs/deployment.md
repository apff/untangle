# Deployment

The default topology is **compose-first**: one host runs both services from
`docker-compose.yml`, joined by a shared report volume.

```bash
cp .env.example .env      # configure origins (+ optional RUN_INTERVAL, WEB_PORT)
docker compose up -d --build
```

- **analyzer** clones/analyzes on start, then re-runs every `RUN_INTERVAL`
  seconds (default 86400 = daily; `0` = run once and exit). A failed run keeps
  the previous report in place — the webapp never regresses to empty.
- **webapp** serves <http://localhost:8080> straight from the volume. Put your
  usual reverse proxy (Traefik/Caddy/nginx) in front for TLS/auth — the app
  itself has no authentication.
- The clone cache persists on the `analyzer-data` volume, so daily runs are
  cheap `git fetch` deltas.

## The private config overlay pattern

Keep org-specific data (systems, prefixes, detection patterns, tokens) out of
any public repo by treating it as a deploy-time overlay:

1. Create a small **private** repo containing your `config/` dir
   (`untangle.yml`, `systems.yml`, `prefixes.yml`), your `.env`, and a
   `docker-compose.override.yml`:

   ```yaml
   services:
     analyzer:
       volumes:
         - ./config:/app/config:ro
   ```

2. On the deploy host, check out the public untangle repo (or just its
   `docker-compose.yml` + published images), copy the overlay files next to
   it, and `docker compose up -d`. Compose merges the override automatically.

The public images ship only the generic `config.example` defaults; everything
org-specific arrives via the mount and environment.

## Scheduling with an external scheduler

If you prefer host cron / systemd timers over the sleep loop, set
`RUN_INTERVAL=0` (run-once) and remove `restart: unless-stopped` from the
analyzer, then:

```bash
# crontab
0 3 * * * cd /srv/untangle && docker compose run --rm analyzer
```

## CI-scheduled analyzer + pull-mode webapp

For orgs that already run CI (e.g. self-hosted GitLab), the analyzer can run as
a scheduled CI job that publishes `graph.json` to an artifact store; the webapp
then **pulls** it instead of sharing a volume:

```bash
docker run -d -p 8080:80 \
  -e REPORT_URL="https://git.example.com/api/v4/projects/<ID>/packages/generic/untangle/latest/graph.json" \
  -e REPORT_TOKEN="<read_package_registry deploy token>" \
  -e REPORT_TOKEN_HEADER="Deploy-Token" \
  untangle-webapp
```

- The entrypoint pulls on start and every `REFRESH_INTERVAL` (default 6h); the
  token stays server-side — the browser only fetches same-origin JSON.
- A complete GitLab pipeline (lint/test, image builds, scheduled analyze +
  registry publish, failure webhook) is in
  [`examples/gitlab-ci.yml`](../examples/gitlab-ci.yml). Give the heavy
  `analyze` job a dedicated runner with a persistent `DATA_DIR` host path so
  the clone cache survives between runs (CI `cache:` zips are too slow once
  the cache is multi-GB).

## Running the analyzer ad hoc

The analyzer image runs anywhere with disk + credentials:

```bash
docker run --rm \
  -v untangle-data:/data \
  -e GIT_REPOS="https://github.com/pallets/click.git" \
  -e RUN_INTERVAL=0 \
  untangle-analyzer
```

Mount a config overlay with `-v ./config:/app/config:ro`, and add
`-e WEBAPP_DATA_DIR=/report -v <report-volume>:/report` to publish where a
webapp container can serve it.
