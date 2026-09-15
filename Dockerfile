# ml-party server image: web UI + read API + authenticated sync ingest.
#   docker build -t ml-party .
#   docker run -d -p 127.0.0.1:7327:7327 -v mlparty-data:/data \
#       -e ML_PARTY_TOKEN=<token> ml-party
# TLS/reverse-proxy guidance: docs/deploy.md (never expose plain HTTP
# beyond localhost/trusted networks — reads are unauthenticated until R6).

FROM node:24-slim AS ui
WORKDIR /build
COPY ui/package.json ui/package-lock.json ./
RUN npm ci
COPY ui/ .
RUN npm run build

FROM python:3.12-slim AS runtime
RUN useradd --create-home --uid 1000 mlparty
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src/ src/
RUN pip install --no-cache-dir .
COPY --from=ui /build/dist /app/ui/dist
COPY deploy/docker-entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh && mkdir /data && chown mlparty:mlparty /data

USER mlparty
ENV ML_PARTY_UI_DIST=/app/ui/dist
VOLUME /data
EXPOSE 7327
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:7327/api/health', timeout=3)"
ENTRYPOINT ["/app/entrypoint.sh"]
