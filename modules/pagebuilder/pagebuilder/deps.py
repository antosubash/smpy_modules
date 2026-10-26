"""FastAPI dependencies for the pagebuilder module.

Centralised here so admin views and the JSON API share one source of
truth for resolving module-scoped state without underscore-prefixed
imports across endpoint files.
"""

from __future__ import annotations

from fastapi import Depends, Request
from simple_module_db import get_db
from sqlalchemy.ext.asyncio import AsyncSession

from pagebuilder.media_service import MediaService
from pagebuilder.settings import PagebuilderSettings
from pagebuilder.snapshots.access import SectionAccess
from pagebuilder.snapshots.service import SnapshotService


def get_settings(request: Request) -> PagebuilderSettings:
    return request.app.state.pagebuilder.settings


def get_media_service(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> MediaService:
    return MediaService(db, request.app.state.pagebuilder.settings)


async def get_snapshot_service(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> SnapshotService:
    """The snapshot store, acting as the request's principal.

    Its permissions decide which contributed sections a capture includes, a
    download may carry and a restore applies (``snapshots/access.py``).
    """
    services = request.app.state.pagebuilder
    access = await SectionAccess.for_request(request)
    return SnapshotService(db, services.settings, services.bundle_sections, access)
