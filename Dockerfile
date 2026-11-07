# ---- Node, for the Claude Code CLI ----
FROM node:24-bookworm-slim@sha256:55fb5f5a527ea2c5c4a95f963e48ef90aa38c7b346054fdc8ee9957a2b55d205 AS node

# ---- Web app: built when ui/package.json exists ----
FROM node:24-bookworm-slim@sha256:55fb5f5a527ea2c5c4a95f963e48ef90aa38c7b346054fdc8ee9957a2b55d205 AS ui
WORKDIR /src
COPY . .
RUN if [ -f ui/package.json ]; then \
        cd ui && (if [ -f package-lock.json ]; then npm ci; else npm install; fi) && npm run build && test -f dist/index.html; \
    else \
        mkdir -p ui/dist; \
    fi

# ---- Python dependencies ----
FROM python:3.12-slim-bookworm@sha256:935c3c5b12357a7e10caa9c1e6ca5692344d97cf229832ef584be2cec9fc03df AS deps
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /src
COPY pyproject.toml ./
COPY desk/__init__.py desk/__init__.py
RUN python -m venv /opt/venv && /opt/venv/bin/pip install .

# ---- Runtime ----
FROM python:3.12-slim-bookworm@sha256:935c3c5b12357a7e10caa9c1e6ca5692344d97cf229832ef584be2cec9fc03df AS runtime
ARG CLAUDE_CODE_VERSION=2.1.308
COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates sqlite3 \
    && rm -rf /var/lib/apt/lists/* \
    && npm install -g "@anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}" \
    && npm cache clean --force \
    && groupadd -g 568 apps \
    && useradd -u 568 -g 568 -d /data/home -M -s /usr/sbin/nologin apps
COPY --from=deps /opt/venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOME=/data/home \
    DESK_DATA_DIR=/data \
    DISABLE_AUTOUPDATER=1 \
    DISABLE_TELEMETRY=1 \
    TZ=America/New_York
WORKDIR /app
COPY desk ./desk
COPY --from=ui /src/ui/dist ./ui/dist
COPY deploy/crontab ./deploy/crontab
COPY pyproject.toml ./
RUN /opt/venv/bin/pip install --no-deps --no-cache-dir . && python -m compileall -q desk
ARG DESK_BUILD=dev
ENV DESK_BUILD=$DESK_BUILD
LABEL org.opencontainers.image.revision=$DESK_BUILD \
      org.opencontainers.image.source=https://github.com/inzodious/vektor-desk
USER 568:568
VOLUME ["/data"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=4).status == 200 else 1)"
CMD ["sh", "-c", "mkdir -p /data/home /data/inbox/fidelity /data/run && exec uvicorn desk.api.app:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips '*'"]
