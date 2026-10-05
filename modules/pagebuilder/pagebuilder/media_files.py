"""Media file serving: root resolution, cache headers, integrity check.

Extracted from ``module.py`` (which sits near the size cap) and shared with
:class:`~pagebuilder.media_service.MediaService` so the mount that *serves*
files and the service that *writes* them can never disagree about where the
media library lives (issue #14).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi.staticfiles import StaticFiles
from simple_module_db import current_tenant_id, is_valid_tenant_id
from starlette.exceptions import HTTPException
from starlette.responses import PlainTextResponse, Response
from starlette.types import Scope

from pagebuilder.tenancy import DEFAULT_TENANT, TenancyMode, mode_of

if TYPE_CHECKING:
    from collections.abc import Callable

    from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# Same override + sentinels the hosting package uses to find the project
# root, so a host and this module always agree on the anchor. Duplicated
# rather than imported: modules depend on core, not hosting.
_ENV_PROJECT_ROOT = "SM_PROJECT_ROOT"
_PROJECT_ROOT_SENTINELS = ("pyproject.toml", ".env", "alembic.ini")


def _project_root() -> Path:
    override = os.environ.get(_ENV_PROJECT_ROOT)
    if override:
        return Path(override)
    cwd = Path.cwd().resolve()
    for candidate in (cwd, *cwd.parents):
        if any((candidate / s).exists() for s in _PROJECT_ROOT_SENTINELS):
            return candidate
    return cwd


def resolve_media_root(configured: Path | str) -> Path:
    """Anchor a relative ``media_root`` to the project root, not the cwd.

    A cwd-relative default meant every process with a different working
    directory read and wrote a *different* media directory while sharing one
    database — rows silently outlived their files (issue #14). Absolute
    paths pass through untouched.
    """
    root = Path(configured)
    if not root.is_absolute():
        root = _project_root() / root
    return root.resolve()


def bound_tenant() -> str:
    """The tenant bound to the running context; refuses to guess.

    Every caller is inside a router that bound one (``bind_admin``) or a scope
    that set one explicitly. Falling back to :data:`DEFAULT_TENANT` would file
    a MULTI-mode upload under another tenant's directory.
    """
    tenant = current_tenant_id.get()
    if not is_valid_tenant_id(tenant):
        raise RuntimeError("pagebuilder media: no tenant is bound")
    return tenant


def tenant_media_dir(media_root: Path, tenant_id: str | None = None) -> Path:
    """``media_root/<tenant>`` — where one tenant's files live (issue #38).

    *tenant_id* is the row's own tenant when a row is at hand, else the bound
    one. Validated, because it becomes a path segment.
    """
    tenant = tenant_id or bound_tenant()
    if not is_valid_tenant_id(tenant):
        raise ValueError(f"not a tenant id: {tenant!r}")
    return media_root / tenant


def media_url(prefix: str, filename: str, tenant_id: str | None = None) -> str:
    """``<prefix>/<tenant>/<filename>``, the URL a file is served at."""
    return f"{prefix.rstrip('/')}/{tenant_id or bound_tenant()}/{filename}"


def legacy_media_url(prefix: str, filename: str) -> str:
    """The flat ``<prefix>/<filename>`` URL content stored before #38.

    Still served (see :class:`MediaFiles`), so it still counts as a reference
    to the asset wherever "is this used" or "rewrite this URL" is asked.
    """
    return f"{prefix.rstrip('/')}/{filename}"


def adopt_legacy_files(
    root: Path, *, accept: Callable[[str], bool] | None = None, label: str = "media"
) -> int:
    """Move files sitting directly in *root* into ``root/default/``.

    Anything directly under *root* predates per-tenant directories, and every
    pre-tenancy row was filed under :data:`DEFAULT_TENANT` by the migration.
    Idempotent: directories are never touched, and a file whose target already
    exists is left where it is rather than overwriting it. Returns the count.
    """
    if not root.is_dir():
        return 0
    dest = root / DEFAULT_TENANT
    moved = 0
    for path in sorted(root.iterdir()):
        if path.is_dir() or not path.is_file():
            continue
        if accept is not None and not accept(path.name):
            continue
        target = dest / path.name
        if target.exists():
            continue
        dest.mkdir(parents=True, exist_ok=True)
        path.rename(target)
        moved += 1
    if moved:
        logger.info("pagebuilder.%s: moved %d legacy file(s) into %s", label, moved, dest)
    return moved


def _serving_tenant(scope: Scope) -> str | None:
    """The tenant whose directory this request may read.

    ``StaticFiles`` is a bare ASGI mount, so no router dependency binds a
    tenant: the mode comes off the app and the tenant off the context var that
    ``TenantMiddleware`` binds around the whole stack.
    """
    app = scope.get("app")
    if app is None or mode_of(app) is TenancyMode.SINGLE:
        return DEFAULT_TENANT
    tenant = current_tenant_id.get()
    return tenant if is_valid_tenant_id(tenant) else None


def _tenant_path(path: str, scope: Scope) -> str | None:
    """*path* rewritten into the serving tenant's directory, or ``None`` (404).

    ``<tenant>/<file>`` is served only for the request's own tenant, so tenant
    A's host never serves tenant B's files. A bare ``<file>`` is a URL stored
    before #38 and is served from the request's tenant's directory.
    """
    tenant = _serving_tenant(scope)
    parts = [p for p in path.replace(os.sep, "/").split("/") if p not in ("", ".")]
    if tenant is None:
        return None
    if len(parts) == 1:
        return f"{tenant}/{parts[0]}"
    if len(parts) == 2 and parts[0] == tenant:
        return f"{tenant}/{parts[1]}"
    return None


class MediaFiles(StaticFiles):
    """StaticFiles with immutable caching and an honest 404.

    Media filenames are content-addressed at upload (a fresh UUID hex per
    file, variants included), so a URL never serves different bytes —
    long-lived immutable caching is as safe here as for hashed Vite assets
    (issue #13). Missing files answer with a plain-text 404 instead of
    falling through to the HTML app shell, which hid broken images behind
    ``text/html`` responses (issue #14).
    """

    _CACHE_CONTROL = "public, max-age=31536000, immutable"

    async def get_response(self, path: str, scope: Scope) -> Response:
        scoped = _tenant_path(path, scope)
        if scoped is None:
            return PlainTextResponse("Not Found", status_code=404)
        try:
            response = await super().get_response(scoped, scope)
        except HTTPException as exc:
            if exc.status_code == 404:
                return PlainTextResponse("Not Found", status_code=404)
            raise
        if response.status_code in (200, 304):
            response.headers.setdefault("Cache-Control", self._CACHE_CONTROL)
        return response


async def count_missing_media_files(session: AsyncSession, media_root: Path) -> int:
    """Rows in the media library whose file (or a variant) is gone from disk."""
    from sqlmodel import select

    from pagebuilder.models import MediaAsset

    result = await session.execute(
        select(MediaAsset.tenant_id, MediaAsset.filename, MediaAsset.variants)
    )
    missing = 0
    for tenant_id, filename, variants in result.all():
        names = [filename] + [
            meta["filename"] for meta in (variants or {}).values() if meta.get("filename")
        ]
        folder = tenant_media_dir(media_root, tenant_id)
        if any(not (folder / name).is_file() for name in names):
            missing += 1
    return missing


async def warn_on_orphaned_media(
    session_factory: Callable[[], AsyncSession], media_root: Path
) -> int:
    """Log a warning when media rows point at files that don't exist.

    Runs once at startup. This drift is otherwise invisible until a visitor
    sees broken images: the DB says the asset exists, the picker lists it,
    and only the file request fails. Failures of the check itself (e.g. the
    table doesn't exist yet on a fresh database) are logged at debug and
    never block startup.
    """
    from simple_module_db import all_tenants

    try:
        # Deliberately cross-tenant: one scan at boot over every tenant's rows.
        # Outside a request nothing is bound, and a strict host refuses an
        # unscoped read. Each row is checked in its own tenant's directory.
        with all_tenants():
            async with session_factory() as session:
                missing = await count_missing_media_files(session, media_root)
    except Exception:  # pragma: no cover - defensive: never break boot
        logger.debug("pagebuilder.media integrity check skipped", exc_info=True)
        return 0
    if missing:
        logger.warning(
            "pagebuilder.media: %d media row(s) have no file under %s — "
            "uploads from a different working directory or a missing volume. "
            "Re-upload the assets or point the pagebuilder media_root setting at the "
            "directory that holds them.",
            missing,
            media_root,
        )
    return missing
