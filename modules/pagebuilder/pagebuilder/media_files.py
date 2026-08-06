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
from starlette.exceptions import HTTPException
from starlette.responses import PlainTextResponse, Response
from starlette.types import Scope

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
        try:
            response = await super().get_response(path, scope)
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

    result = await session.execute(select(MediaAsset.filename, MediaAsset.variants))
    missing = 0
    for filename, variants in result.all():
        names = [filename] + [
            meta["filename"] for meta in (variants or {}).values() if meta.get("filename")
        ]
        if any(not (media_root / name).is_file() for name in names):
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
    try:
        async with session_factory() as session:
            missing = await count_missing_media_files(session, media_root)
    except Exception:  # pragma: no cover - defensive: never break boot
        logger.debug("pagebuilder.media integrity check skipped", exc_info=True)
        return 0
    if missing:
        logger.warning(
            "pagebuilder.media: %d media row(s) have no file under %s — "
            "uploads from a different working directory or a missing volume. "
            "Re-upload the assets or point SM_PAGEBUILDER_MEDIA_ROOT at the "
            "directory that holds them.",
            missing,
            media_root,
        )
    return missing
