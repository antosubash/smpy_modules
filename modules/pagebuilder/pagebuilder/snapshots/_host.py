"""What :class:`~pagebuilder.snapshots.restore.RestoreMixin` needs from its host.

The restore gate was split out of ``SnapshotService`` when the contributed
sections (#80) pushed that file past the 300-line cap. It reaches for the
store's session, settings, sections and directory layout, and for ``take``
(the ``pre_restore`` snapshot) — this Protocol writes that down, the same way
``pagebuilder/service/_host.py`` does for ``PagesService``, and
``tests/test_snapshot_host.py`` enforces it. Add a member here before the
mixin starts using it.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from sqlalchemy.ext.asyncio import AsyncSession

from pagebuilder.models import ContentSnapshot, SnapshotMedia, SnapshotSource
from pagebuilder.settings import PagebuilderSettings
from pagebuilder.snapshots.blobs import BlobStore
from pagebuilder.snapshots.registry import SectionRegistry


@runtime_checkable
class SnapshotHost(Protocol):
    db: AsyncSession
    settings: PagebuilderSettings
    sections: SectionRegistry

    @property
    def blobs(self) -> BlobStore: ...

    def dir_for(self, snapshot_id: int) -> Path: ...

    async def get(self, snapshot_id: int) -> ContentSnapshot: ...

    async def media_rows(self, snapshot_id: int) -> list[SnapshotMedia]: ...

    async def take(
        self, note: str | None = None, source: SnapshotSource = SnapshotSource.MANUAL
    ) -> ContentSnapshot: ...


if TYPE_CHECKING:
    HostBase = SnapshotHost
else:
    HostBase = object
