"""Orchestration for the snapshot store and the approval gate.

Owns the DB rows and the directory layout; the real work lives in the modules
this one composes. The two rules worth stating here rather than burying:

* approving a restore takes a ``pre_restore`` snapshot *first*, so every
  restore is reversible and "Approve & apply" stops being a one-way door;
* at most one import is pending at a time, because a plan computed against
  content that has since changed no longer describes what applying would do.
"""

from __future__ import annotations

import asyncio
import json
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import delete as sa_delete
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from pagebuilder.media_files import resolve_media_root
from pagebuilder.models import (
    ContentSnapshot,
    ImportStatus,
    PendingImport,
    SnapshotMedia,
    SnapshotSource,
)
from pagebuilder.settings import PagebuilderSettings
from pagebuilder.snapshots.apply import apply_bundle
from pagebuilder.snapshots.archive import BundleError, read_zip, write_zip
from pagebuilder.snapshots.blobs import BLOBS_DIR, BlobStore, tenant_store
from pagebuilder.snapshots.capture import capture
from pagebuilder.snapshots.format import FORMAT_VERSION, MEDIA_DIR, MEDIA_INDEX_NAME, is_readable
from pagebuilder.snapshots.media_match import preview_urls
from pagebuilder.snapshots.plan import build_plan

_SNAPSHOTS_DIR = "snapshots"
_PRE_RESTORE_NOTE = "Automatic snapshot taken before restoring"


class SnapshotService:
    def __init__(self, db: AsyncSession, settings: PagebuilderSettings) -> None:
        self.db = db
        self.settings = settings

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
        result = await self.db.execute(
            select(ContentSnapshot).order_by(ContentSnapshot.id.desc())
        )
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
        snapshot = ContentSnapshot(
            note=note, source=source, format_version=FORMAT_VERSION
        )
        self.db.add(snapshot)
        await self.db.flush()

        try:
            result = await capture(
                self.db, self.settings, self.dir_for(snapshot.id), self.blobs
            )
            snapshot.manifest = result.manifest
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

        snapshot.manifest = manifest
        snapshot.size_bytes = len(data)
        for bundle_name, entry in index.items():
            self.db.add(
                SnapshotMedia(
                    snapshot_id=snapshot.id,
                    bundle_name=bundle_name,
                    sha256=entry["sha256"],
                    original_filename=entry.get("original_filename", bundle_name),
                    content_type=entry.get("content_type", "application/octet-stream"),
                    folder=entry.get("folder"),
                )
            )
        await self.db.flush()
        return snapshot

    async def download(self, snapshot_id: int, target: Path) -> int:
        snapshot = await self.get(snapshot_id)
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
        await asyncio.to_thread(
            self.blobs.delete_unreferenced, keep={sha for (sha,) in result}
        )

    async def pending(self) -> PendingImport | None:
        result = await self.db.execute(
            select(PendingImport).where(PendingImport.status == ImportStatus.PENDING)
        )
        return result.scalars().first()

    def _index_for(self, snapshot_id: int) -> dict[str, Any]:
        path = self.dir_for(snapshot_id) / MEDIA_DIR / MEDIA_INDEX_NAME
        return json.loads(path.read_text()) if path.is_file() else {}

    async def request_restore(self, snapshot_id: int) -> PendingImport:
        if await self.pending() is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="An import is already awaiting approval",
            )
        snapshot = await self.get(snapshot_id)
        if not is_readable(snapshot.format_version):
            raise HTTPException(
                status_code=422,
                detail=f"Snapshot uses unsupported format version "
                f"{snapshot.format_version}",
            )
        bundle = self.dir_for(snapshot.id)
        rows = await self.media_rows(snapshot.id)
        # Straight to `media_match.preview_urls` so the plan and the apply
        # cannot drift into matching by different rules — matching more
        # loosely here would resolve a sentinel to a URL the apply then
        # declines to reuse, telling an approver a page is unchanged while
        # its image is about to change underneath them.
        name_to_url = await preview_urls(self.db, self.settings, rows)
        plan = await build_plan(self.db, bundle, name_to_url)

        staged = PendingImport(snapshot_id=snapshot.id, plan=plan)
        self.db.add(staged)
        try:
            await self.db.flush()
        except IntegrityError as exc:
            # The check above is not atomic with this insert: two concurrent
            # requests can both see no pending import. The partial unique
            # index on `status` is the real backstop — this turns the race's
            # loser into the same 409 the check above gives the common case,
            # instead of a raw 500.
            await self.db.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="An import is already awaiting approval",
            ) from exc
        return staged

    async def _decide(
        self, import_id: int, actor: str | None, status_value: ImportStatus
    ) -> PendingImport:
        staged = await self.db.get(PendingImport, import_id)
        if staged is None:
            raise HTTPException(status_code=404, detail="Import not found")
        if staged.status is not ImportStatus.PENDING:
            raise HTTPException(status_code=409, detail="Import already decided")
        staged.status = status_value
        staged.decided_at = datetime.now(UTC)
        staged.decided_by = actor
        return staged

    async def reject(
        self, import_id: int, actor: str | None, note: str | None = None
    ) -> PendingImport:
        staged = await self._decide(import_id, actor, ImportStatus.REJECTED)
        staged.note = note
        await self.db.flush()
        return staged

    async def approve(self, import_id: int, actor: str | None) -> dict[str, Any]:
        staged = await self._decide(import_id, actor, ImportStatus.APPROVED)
        # Before anything is overwritten, so the previous state is one click
        # away rather than gone.
        pre_restore = await self.take(
            _PRE_RESTORE_NOTE, source=SnapshotSource.PRE_RESTORE
        )

        try:
            snapshot = await self.get(staged.snapshot_id)
            result = await apply_bundle(
                self.db,
                self.settings,
                self.dir_for(snapshot.id),
                self.blobs,
                self._index_for(snapshot.id),
                note=f"Restored snapshot #{snapshot.id}",
            )
            await self.db.flush()
        except Exception:
            # `take` guards its own capture; this covers the apply below.
            shutil.rmtree(self.dir_for(pre_restore.id), ignore_errors=True)
            raise
        return result
