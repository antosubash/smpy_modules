# syntax=docker/dockerfile:1
#
# The demo host as one image: the API (uvicorn) serving the pre-built UI.
# Development only, like the host itself — it is never published. Run it with
# compose.yaml (see the README, "Running in Docker").
#
# Two stages:
#   ui       Node + uv. Installs both workspaces, generates the module pages
#            manifest from the installed Python modules (`make gen-pages`) and
#            runs the Vite build into host/static/dist.
#   runtime  Slim Python + uv. Installs the Python workspace without dev
#            dependencies and copies the built UI in. Node is not shipped.
#
# Both stages work under /app: the generated pages files carry absolute paths
# to the module sources, so the tree has to sit at the same place in each.

# The base images are pinned to an exact release and digest in the FROM lines
# themselves (not through ARGs) so Dependabot's docker ecosystem can see and
# bump them (.github/dependabot.yml). PYTHON_VERSION is only the interpreter uv
# installs in the ui stage, which runs `gen-pages` and nothing else.
ARG PYTHON_VERSION=3.12
# Same uv as CI (UV_VERSION in .github/workflows/ci.yml); bump them together.
ARG UV_VERSION=0.13.4

FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv

# ---------------------------------------------------------------------------
FROM node:24.22.1-bookworm-slim@sha256:55fb5f5a527ea2c5c4a95f963e48ef90aa38c7b346054fdc8ee9957a2b55d205 AS ui
ARG PYTHON_VERSION
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_LINK_MODE=copy \
    UV_PYTHON=${PYTHON_VERSION} \
    UV_PYTHON_INSTALL_DIR=/opt/uv-python
WORKDIR /app
COPY . .
RUN --mount=type=cache,target=/root/.npm \
    npm ci --no-audit --no-fund
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --all-packages
# The Makefile's sync-module-deps, gen-pages and build targets, minus make.
RUN uv run --no-sync --project host python -m simple_module_hosting sync-js-deps \
        --host-client-app=host/client_app \
 && uv run --no-sync --project host python -m simple_module_hosting gen-pages \
        --host-dir=host/client_app \
 && npm run build

# ---------------------------------------------------------------------------
FROM python:3.12.15-slim-bookworm@sha256:6a0e06f5ba0b373d051aabd3fffb9b873f27f9a2a3a14bcbe37dee6f0e3bbc70 AS runtime
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
    UV_PYTHON=/usr/local/bin/python3 \
    PATH=/app/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    SM_ENVIRONMENT=production \
    SM_DATABASE_URL=sqlite+aiosqlite:////app/var/app.db \
    SMPY_MIGRATE_ON_START=1 \
    PORT=8000
WORKDIR /app

# Dependencies first, so a source-only change reuses this layer. The members'
# pyproject.toml files are enough for uv to resolve them; the members
# themselves are installed (editable) once the sources are in.
COPY pyproject.toml uv.lock .python-version ./
COPY host/pyproject.toml host/
COPY modules/ai/pyproject.toml modules/ai/
COPY modules/billing/pyproject.toml modules/billing/
COPY modules/news/pyproject.toml modules/news/
COPY modules/pagebuilder/pyproject.toml modules/pagebuilder/
COPY modules/records/pyproject.toml modules/records/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --all-packages --no-install-workspace

COPY host host
COPY modules modules
COPY scripts scripts
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --all-packages
COPY --from=ui /app/host/static/dist host/static/dist
COPY docker/entrypoint.sh /usr/local/bin/smpy-entrypoint

# Unprivileged user. var/ (SQLite + pagebuilder media and snapshots) and
# uploads/ (file_storage's local backend) are the two volume mount points;
# creating them here, owned by that user, is what lets a fresh named volume
# inherit the ownership.
RUN groupadd --gid 10001 smpy \
 && useradd --uid 10001 --gid 10001 --no-create-home --home-dir /app --shell /usr/sbin/nologin smpy \
 && mkdir -p var uploads \
 && chown smpy:smpy var uploads
USER 10001:10001

EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=5s --start-period=60s --retries=6 \
    CMD ["python", "-c", "import os, urllib.request as u; u.urlopen('http://127.0.0.1:%s/health/live' % os.environ.get('PORT', '8000'), timeout=4)"]
ENTRYPOINT ["smpy-entrypoint"]
