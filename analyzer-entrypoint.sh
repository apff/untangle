#!/bin/sh
#
# Analyzer entrypoint: run `untangle all`, then re-run on an interval.
#
# Compose has no cron, so the simplest robust scheduler is a sleep loop with
# `restart: unless-stopped` behind it. A failed run logs and waits for the next
# interval — the webapp keeps serving the previous report (the analyzer only
# overwrites it on success).
#
# Config:
#   RUN_INTERVAL  seconds between runs (default: 86400 = daily).
#                 0 = run once and exit — use this with an external scheduler
#                 (host cron + `docker compose run --rm analyzer`, or CI).
set -u

RUN_INTERVAL="${RUN_INTERVAL:-86400}"

while :; do
  echo "[analyzer] starting run at $(date -u '+%Y-%m-%dT%H:%M:%SZ')"
  if uv run untangle all --skip-report; then
    echo "[analyzer] run completed"
  else
    echo "[analyzer] run FAILED (rc=$?) — previous report stays in place"
  fi
  [ "$RUN_INTERVAL" = "0" ] && exit 0
  echo "[analyzer] sleeping ${RUN_INTERVAL}s until the next run"
  sleep "$RUN_INTERVAL"
done
