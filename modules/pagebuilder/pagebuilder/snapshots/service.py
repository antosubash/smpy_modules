"""Orchestration for the snapshot store and the approval gate.

Owns the DB rows and the directory layout; the real work lives in the modules
this one composes. The approval gate — staging, rejecting and approving a
restore — is :class:`~pagebuilder.snapshots.restore.RestoreMixin`, where its
two rules are stated.

Sections other modules contribute (#80, ``snapshots/sections.py``) ride every
step through this same session: captured into each snapshot, validated on
upload, planned beside the pages, and applied after them in one transaction.
"""

from __future__ import annotations

import asyncio
import shutil
from pathlib import Path

from fastapi import HTTPException, status
from simple_module_core.permission_denied import PermissionDenied
from sqlalchemy import delete as sa_delete
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from pagebuilder.contracts.schemas import PendingImportRead
from pagebuilder.media_files import resolve_media_root
from pagebuilder.models import ContentSnapshot, PendingImport, SnapshotMedia, SnapshotSource
from pagebuilder.settings import PagebuilderSettings
from pagebuilder.snapshots import written
from pagebuilder.snapshots.access import (
    DOWNLOAD_PERMISSIONS_KEY,
    SYSTEM,
    SectionAccess,
    download_needs,
    download_record,
)
from pagebuilder.snapshots.archive import BundleError, index_rows, read_zip, write_zip
from pagebuilder.snapshots.blobs import BLOBS_DIR, BlobStore, tenant_store
from pagebuilder.snapshots.capture import capture
from pagebuilder.snapshots.format import FORMAT_VERSION
from pagebuilder.snapshots.plan_views import for_reader, read_details, remove_details
from pagebuilder.snapshots.registry import SectionRegistry
from pagebuilder.snapshots.restore import RestoreMixin

_SNAPSHOTS_DIR = "snapshots"


class SnapshotService(RestoreMixin):
    def __init__(
        self,
        db: AsyncSession,
        settings: PagebuilderSettings,
        sections: SectionRegistry | None = None,
        access: SectionAccess = SYSTEM,
    ) -> None:
        self.db = db
        self.settings = settings
        self.sections = sections if sections is not None else SectionRegistry()
        self.access = access
        """What the acting principal may do with contributed sections; ``SYSTEM``
        (everything) when no request stands behind the service."""

    @property
    def root(self) -> Path:
        # Same anchoring as media_root: a cwd-relative default is what let two
        # differently-launched processes disagree about where files live.
        return resolve_media_root(self.settings.snapshot_root)

    @property
    def blobs(self) -> BlobStore:
        return tenant_store(self.root / BLOBS_DIR)

    def dir_for(self, snapshot_id: int) -> Path:
        return self.root / _SNAPSHOTS_DIR / str(snapshot_id)

    async def list(self) -> list[ContentSnapshot]:
        result = await self.db.execute(select(ContentSnapshot).order_by(ContentSnapshot.id.desc()))
        return list(result.scalars().all())

    async def get(self, snapshot_id: int) -> ContentSnapshot:
        snapshot = await self.db.get(ContentSnapshot, snapshot_id)
        if snapshot is None:
            raise HTTPException(status_code=404, detail="Snapshot not found")
        return snapshot

    async def media_rows(self, snapshot_id: int) -> list[SnapshotMedia]:
        result = await self.db.execute(
            select(SnapshotMedia).where(SnapshotMedia.snapshot_id == snapshot_id)
        )
        return list(result.scalars().all())

    async def take(
        self, note: str | None = None, source: SnapshotSource = SnapshotSource.MANUAL
    ) -> ContentSnapshot:
        snapshot = ContentSnapshot(note=note, source=source, format_version=FORMAT_VERSION)
        self.db.add(snapshot)
        await self.db.flush()
        if source is SnapshotSource.PRE_RESTORE:
            # Tracked before the capture writes anything, so a cancellation
            # inside it (which `except Exception` below misses) still removes
            # the directory with the rolled-back row (#250).
            written.track(self.db, [self.dir_for(snapshot.id)])

        # `pre_restore` is the system's own snapshot, not the approver's: it
        # captures every section, so the restore it guards stays reversible.
        access = SYSTEM if source is SnapshotSource.PRE_RESTORE else self.access
        try:
            result = await capture(
                self.db, self.settings, self.dir_for(snapshot.id), self.blobs, self.sections, access
            )
            snapshot.manifest = self._with_record(result.manifest)
            snapshot.size_bytes = result.size_bytes
            for row in result.media:
                self.db.add(SnapshotMedia(snapshot_id=snapshot.id, **row))
            await self.db.flush()
        except Exception:
            # The row naming this directory rolls back with the request, so
            # the partial bundle has to go with it. `upload` guards the same.
            shutil.rmtree(self.dir_for(snapshot.id), ignore_errors=True)
            raise
        return snapshot

    async def upload(self, data: bytes, note: str | None = None) -> ContentSnapshot:
        if len(data) > self.settings.snapshot_max_upload_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"Bundle exceeds {self.settings.snapshot_max_upload_bytes} bytes",
            )
        snapshot = ContentSnapshot(
            note=note, source=SnapshotSource.UPLOAD, format_version=FORMAT_VERSION
        )
        self.db.add(snapshot)
        await self.db.flush()

        target = self.dir_for(snapshot.id)
        try:
            # Off the event loop: unzipping, hashing and writing up to
            # `snapshot_max_upload_bytes` would otherwise stall every other
            # request on this worker for the whole extraction.
            manifest, index = await asyncio.to_thread(
                read_zip,
                data,
                target,
                self.blobs,
                self.settings.snapshot_max_extracted_bytes,
                self.sections,
            )
        except BundleError as exc:
            shutil.rmtree(target, ignore_errors=True)
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except Exception:
            # Anything else is a bug rather than a bad bundle, but the
            # half-extracted directory has to go either way: the row is about
            # to be rolled back, and on SQLite its integer id is reused, so a
            # directory left behind is one a later snapshot would inherit.
            shutil.rmtree(target, ignore_errors=True)
            raise

        snapshot.manifest = self._with_record(manifest)  # never the bundle's own claim
        snapshot.format_version = manifest["format_version"]  # the bundle's, not ours
        snapshot.size_bytes = len(data)
        for row in index_rows(index):
            self.db.add(SnapshotMedia(snapshot_id=snapshot.id, **row))
        await self.db.flush()
        return snapshot

    def _with_record(self, manifest: dict) -> dict:
        """*manifest* with this host's record of what each section needs to download."""
        return {**manifest, DOWNLOAD_PERMISSIONS_KEY: download_record(manifest, self.sections)}

    def _check_download(self, snapshot: ContentSnapshot) -> None:
        """403 unless the principal may take every section the bundle carries.

        Fails closed: see :func:`~pagebuilder.snapshots.access.download_needs`.
        """
        missing = self.access.lacking(download_needs(snapshot.manifest or {}, self.sections))
        if missing:
            raise PermissionDenied(missing[0])

    async def readable(self, staged: PendingImport) -> PendingImportRead:
        """*staged* as this principal may read it — every response with a plan uses this."""
        details = await asyncio.to_thread(read_details, self.root, staged.id or 0)
        read = PendingImportRead.model_validate(staged)
        plan = for_reader(
            staged.plan or {}, details, self.sections, self.access, import_id=staged.id
        )
        return read.model_copy(update={"plan": plan})

    async def download(self, snapshot_id: int, target: Path) -> int:
        snapshot = await self.get(snapshot_id)
        self._check_download(snapshot)
        rows = await self.media_rows(snapshot.id)
        try:
            # Off the event loop: DEFLATE over the whole media library.
            return await asyncio.to_thread(
                write_zip,
                self.dir_for(snapshot.id),
                self.blobs,
                [{"sha256": row.sha256} for row in rows],
                target,
            )
        except BundleError as exc:
            # The store has lost bytes this snapshot still names. Failing the
            # download says so; the alternative is handing someone a bundle
            # that every host will reject on import for reasons invisible here.
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)
            ) from exc

    async def delete(self, snapshot_id: int) -> None:
        snapshot = await self.get(snapshot_id)
        shutil.rmtree(self.dir_for(snapshot.id), ignore_errors=True)
        # The rows cascade on Postgres, but SQLite does not enforce the
        # constraint unless PRAGMA foreign_keys is on (see PagesService.purge
        # for the same gotcha) — so both dependents are cleared explicitly
        # rather than trusted to `ondelete="CASCADE"`. Left behind, a stale
        # SnapshotMedia row would poison delete_unreferenced's keep-set
        # forever, and a stale PENDING PendingImport would 404 on approve
        # while still blocking every future restore.
        imports = await self.db.execute(
            select(PendingImport.id).where(PendingImport.snapshot_id == snapshot.id)
        )
        await asyncio.to_thread(remove_details, self.root, [i for (i,) in imports])
        await self.db.execute(
            sa_delete(PendingImport).where(PendingImport.snapshot_id == snapshot.id)
        )
        await self.db.execute(
            sa_delete(SnapshotMedia).where(SnapshotMedia.snapshot_id == snapshot.id)
        )
        await self.db.delete(snapshot)
        await self.db.flush()
        # Reference-counted: only bytes no surviving snapshot names are dropped.
        result = await self.db.execute(select(SnapshotMedia.sha256))
        # Off the event loop: a scan of the whole shared blob store.
        await asyncio.to_thread(self.blobs.delete_unreferenced, keep={sha for (sha,) in result})
