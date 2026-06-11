# Webapp image — a tiny always-on static server for the dependency explorer.
# It pulls the latest report itself (see docker-entrypoint.sh), so it can run
# anywhere: standalone, in docker-compose, or dropped into the DevDash stack.
#
# Build context is this directory:  docker build -t dep-explorer-web webapp
FROM nginx:alpine

# curl: pull the published report at runtime + HEALTHCHECK.
RUN apk add --no-cache curl

# Static frontend only (NOT data/, Dockerfile, entrypoint, nginx.conf — the
# entrypoint creates data/ and pulls the report at runtime).
COPY css    /usr/share/nginx/html/css
COPY js     /usr/share/nginx/html/js
COPY vendor /usr/share/nginx/html/vendor
COPY img    /usr/share/nginx/html/img
COPY fonts  /usr/share/nginx/html/fonts
COPY index.html /usr/share/nginx/html/

# gzip + cache headers.
COPY nginx.conf /etc/nginx/conf.d/default.conf

# Pull-on-start + background refresh, then exec nginx.
COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

# 6h default; override per deployment. REPORT_URL/REPORT_TOKEN are set at runtime.
ENV REFRESH_INTERVAL=21600

EXPOSE 80
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD curl -fsS http://localhost/ >/dev/null || exit 1

ENTRYPOINT ["/docker-entrypoint.sh"]
