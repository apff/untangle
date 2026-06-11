#!/bin/sh
#
# Webapp entrypoint. The frontend is fully static and only reads
# data/graph.json (one same-origin fetch in js/data.js). This script pulls that
# graph from the analyzer's published location at startup, refreshes it on a
# timer, then hands off to nginx. Pulling here (not in the browser) keeps any
# registry token out of client JS and avoids CORS.
#
# Config (all optional):
#   REPORT_URL           where to GET the latest graph.json
#   REPORT_TOKEN         auth token for that URL (omit if public)
#   REPORT_TOKEN_HEADER  header to send the token in (default: PRIVATE-TOKEN, which
#                        suits GitLab; use "Deploy-Token" for a GitLab deploy token
#                        or "Authorization" style headers as your host requires)
#   REFRESH_INTERVAL     seconds between background refreshes (default: 21600 = 6h)
#
set -eu

DATA_DIR="/usr/share/nginx/html/data"
TARGET="$DATA_DIR/graph.json"

REPORT_URL="${REPORT_URL:-}"
REPORT_TOKEN="${REPORT_TOKEN:-}"
REPORT_TOKEN_HEADER="${REPORT_TOKEN_HEADER:-PRIVATE-TOKEN}"
REFRESH_INTERVAL="${REFRESH_INTERVAL:-21600}"

# Atomically replace the served report. Download to a temp file, sanity-check it
# looks like JSON, then mv into place so nginx never serves a half-written file.
fetch_report() {
  [ -z "$REPORT_URL" ] && return 1
  # Temp file lives in the data dir so the swap-in is an atomic same-filesystem
  # rename. Dot-prefixed so a transient name is never served.
  tmp="$(mktemp "$DATA_DIR/.report.XXXXXX")"
  if [ -n "$REPORT_TOKEN" ]; then
    set -- --header "$REPORT_TOKEN_HEADER: $REPORT_TOKEN"
  else
    set --
  fi
  if curl -fsSL "$@" -o "$tmp" "$REPORT_URL"; then
    first="$(tr -d '[:space:]' < "$tmp" | cut -c1)"
    if [ "$first" = "{" ]; then
      # mktemp makes the file 0600/root; nginx workers run as `nginx` and would
      # otherwise get 403. Make it world-readable before swapping in.
      chmod 644 "$tmp"
      mv "$tmp" "$TARGET"
      echo "[entrypoint] report updated ($(wc -c < "$TARGET" | tr -d ' ') bytes)"
      return 0
    fi
    echo "[entrypoint] fetched content did not look like JSON; keeping previous data"
  else
    echo "[entrypoint] fetch failed from $REPORT_URL"
  fi
  rm -f "$tmp"
  return 1
}

mkdir -p "$DATA_DIR"

# Placeholder so the page renders (empty graph + "waiting for data" banner)
# even before the first pull. Matches graph.schema.json's empty shape.
if [ ! -f "$TARGET" ]; then
  echo '{"version":1,"generatedAt":null,"languages":[],"systems":[],"nodes":[],"edges":[]}' > "$TARGET"
fi

if [ -n "$REPORT_URL" ]; then
  fetch_report || echo "[entrypoint] starting with placeholder/previous data; will retry in background"
  # Background refresh: the analyzer publishes daily, so re-pull periodically.
  (
    while true; do
      sleep "$REFRESH_INTERVAL"
      fetch_report || true
    done
  ) &
else
  echo "[entrypoint] REPORT_URL not set — serving the report from the data volume only"
fi

exec nginx -g 'daemon off;'
