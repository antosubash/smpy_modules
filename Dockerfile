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

ARG PYTHON_VERSION=3.12
ARG NODE_VERSION=24
# Same uv as CI (UV_VERSION in .github/workflows/ci.yml); bump them together.
ARG UV_VERSION=0.13.4

FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv

# ---------------------------------------------------------------------------
FROM node:${NODE_VERSION}-bookworm-slim AS ui
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
FROM python:${PYTHON_VERSION}-slim-bookworm AS runtime
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
    UV_PYTHON=/usr/local/bin/python3 \
    PATH=/app/.venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    SM_ENVIRONMENT=production \
    SM_DATABASE_URL=sqlite+aiosqlite:////app/var/app.db \
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
