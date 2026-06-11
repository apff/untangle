# Operations & troubleshooting

Day-to-day signals and how to read them.

## Is the data fresh?

Every report carries `generated_at` (UTC). The webapp shows an **"Updated Nh ago"**
badge in the top nav; it turns red and reads **"Data … (stale)"** once the report
is older than 36h (the daily cadence plus headroom for one missed run). A red
badge means the analyzer hasn't published recently — check
`docker compose logs analyzer` (or the CI pipeline in pull mode).

## Failure behavior

- In compose mode a failed analyzer run logs `[analyzer] run FAILED` and waits
  for the next interval; **the previous report keeps being served** (the report
  is only overwritten on success).
- In CI mode, wire the example pipeline's `ALERT_WEBHOOK_URL` to a
  Slack/Mattermost-style webhook for failure pings, plus your CI's native
  notifications.
- A stale webapp badge is the last-resort signal if everything else is missed.

## Clone-failure threshold

`clone` tolerates a few broken repos but fails the whole run when the failure
**share** exceeds `MAX_CLONE_FAILURE_RATIO` (default `0.15`) — a likely origin
or network outage. When that happens the `all` command aborts *before* analyze,
so a degraded graph is never published.

- A handful of failures under the threshold → run continues, failures listed in
  the log under `=== Summary ===`.
- Over the threshold → `ERROR: clone failure ratio …` and a non-zero exit.
- Tune per environment with `MAX_CLONE_FAILURE_RATIO` (e.g. `0.30` if a chunk of
  repos are expected to be unreachable).

## Config-drift warnings

Each `analyze` run ends with a **Config drift** section (also in `REPORT.md`)
flagging hand-maintained hints that no longer match the live repos:

| Warning | Meaning | Fix |
|---|---|---|
| *prefix hints pointing at missing repos* | a target in `config/prefixes.yml` was renamed/deleted | update or remove the entry |
| *repo groups not mapped to any system* | a repo's top-level group isn't in any `config/systems.yml` system | add the group to a system |
| *system groups with no repos* | a group listed in `systems.yml` has no repos | remove the stale group |

These don't fail the run — they're a maintenance to-do list. See
[extending.md](extending.md).

## Common issues

| Symptom | Likely cause / fix |
|---|---|
| Webapp shows "No data yet" | the first analyzer run hasn't finished — `docker compose logs -f analyzer`. In pull mode: `REPORT_URL` unset/unreachable, or `REPORT_TOKEN`/`REPORT_TOKEN_HEADER` wrong — check `[entrypoint] …` logs. |
| `no origins configured` | set an origin in `.env` (`GITLAB_URL`+token, `GITHUB_ORG`/`GITHUB_USER`, or `GIT_REPOS`) or an `origins:` list in `config/untangle.yml`. |
| `analyze` says `manifest.json not found` | `clone` hasn't run for this `DATA_DIR`. Run `untangle clone` (or `all`). |
| GitHub discovery missing repos | private repos need `GITHUB_TOKEN`; archived/disabled repos are skipped by design. |
| Daily run slow / re-clones everything | the clone cache isn't persisting — verify the `analyzer-data` volume (or the runner's host path in CI mode). |
| A service URL resolves to the wrong repo | add/adjust a hint in `config/prefixes.yml` (longest prefix wins). |
| URL scanning finds nothing | no internal domains configured/derivable — set `detection.internal_domains` in `config/untangle.yml` (defaults exclude github.com/gitlab.com on purpose). |

## Manual run

```bash
docker compose run --rm -e RUN_INTERVAL=0 analyzer   # one off-schedule analysis
```

Useful right after adding repos or fixing config drift.
