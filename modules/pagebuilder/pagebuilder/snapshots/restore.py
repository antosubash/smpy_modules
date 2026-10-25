"""The restore approval gate: stage, reject, approve.

Split from ``service.py`` (300-line cap, #133); composed into
``SnapshotService``, whose members it reaches for are declared on
:class:`~pagebuilder.snapshots._host.SnapshotHost`. The two rules worth
stating here rather than burying:

* approving a restore takes a ``pre_restore`` snapshot *first*, so every
  restore is reversible and "Approve & apply" stops being a one-way door;
* at most one import is pending at a time, because a plan computed against
  content that has since changed no longer describes what applying would do.

Contributed sections (#80) are planned beside the pages and applied after
them, through this request's one session: a section that fails rolls
pagebuilder's part back too, and the import stays pending.
"""

from __future__ import annotations

import asyncio
import json
import shutil
from datetime import UTC, datetime
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from pagebuilder.models import ContentSnapshot, ImportStatus, PendingImport, SnapshotSource
from pagebuilder.snapshots._host import HostBase
from pagebuilder.snapshots.apply import apply_bundle
from pagebuilder.snapshots.format import MEDIA_DIR, MEDIA_INDEX_NAME, is_readable
from pagebuilder.snapshots.manifest import PAGEBUILDER_SECTION
from pagebuilder.snapshots.match import RestoreConflictError, match_live
from pagebuilder.snapshots.media_match import preview_urls
from pagebuilder.snapshots.plan import build_plan, read_documents
from pagebuilder.snapshots.plan_views import split_items, write_details
from pagebuilder.snapshots.section_restore import apply_sections, plan_sections
from pagebuilder.snapshots.sections import present, revalidate
from pagebuilder.snapshots.validate import BundleError

_PRE_RESTORE_NOTE = "Automatic snapshot taken before restoring"
_ALREADY_PENDING = "An import is already awaiting approval"


def _refusal(exc: Exception) -> HTTPException:
    """409 for what cannot land here as it stands, 422 for what cannot be read."""
    if isinstance(exc, RestoreConflictError):
        return HTTPException(status.HTTP_409_CONFLICT, str(exc))
    return HTTPException(status_code=422, detail=str(exc))


class RestoreMixin(HostBase):
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
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=_ALREADY_PENDING)
        snapshot = await self.get(snapshot_id)
        if not is_readable(snapshot.format_version):
            raise HTTPException(
                status_code=422,
                detail=f"Snapshot uses unsupported format version {snapshot.format_version}",
            )
        bundle = self.dir_for(snapshot.id)
        rows = await self.media_rows(snapshot.id)
        # Straight to `media_match.preview_urls` so the plan and the apply
        # cannot drift into matching by different rules — matching more
        # loosely here would resolve a sentinel to a URL the apply then
        # declines to reuse, telling an approver a page is unchanged while
        # its image is about to change underneath them.
        name_to_url = await preview_urls(self.db, self.settings, rows)
        manifest = snapshot.manifest or {}
        try:
            await self._revalidate(snapshot)
            plan = await build_plan(self.db, bundle, name_to_url)
            plan |= await plan_sections(
                self.db, self.sections, manifest, bundle, name_to_url, self.access
            )
        except (RestoreConflictError, BundleError) as exc:
            raise _refusal(exc) from exc

        # Contributed sections' items (their rows' titles and slugs) stay out
        # of the audited column; `readable` serves them to who may see them.
        stored, details = split_items(plan)
        staged = PendingImport(snapshot_id=snapshot.id, plan=stored)
        self.db.add(staged)
        try:
            await self.db.flush()
        except IntegrityError as exc:
            # The check above is not atomic with this insert; the partial
            # unique index on `status` is the real backstop, and this turns the
            # race's loser into the same 409 instead of a raw 500.
            await self.db.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail=_ALREADY_PENDING
            ) from exc
        await asyncio.to_thread(write_details, self.root, staged.id or 0, details)
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

    async def _revalidate(self, snapshot: ContentSnapshot) -> None:
        """Hold the bundle to the sections registered *now* (see ``revalidate``)."""
        await asyncio.to_thread(
            lambda: revalidate(
                snapshot.manifest or {},
                self.sections,
                self.dir_for(snapshot.id),
                self._index_for(snapshot.id),
            )
        )

    async def _recheck(self, snapshot: ContentSnapshot, denied: frozenset[str]) -> None:
        """Re-run every matcher, so a refusal at approval writes nothing.

        Not trusted from staging: pages and contributed rows move in between.
        A section left out at staging (*denied*) is not re-planned: it will not
        be applied, so it must not be able to block the pages with a 409.
        """
        bundle = self.dir_for(snapshot.id)
        manifest = snapshot.manifest or {}
        try:
            await self._revalidate(snapshot)
            documents = await read_documents(bundle)
            await match_live(self.db, documents.pages)
            if present(manifest, self.sections):
                rows = await self.media_rows(snapshot.id)
                urls = await preview_urls(self.db, self.settings, rows)
                await plan_sections(
                    self.db, self.sections, manifest, bundle, urls, self.access, denied
                )
        except (RestoreConflictError, BundleError) as exc:
            raise _refusal(exc) from exc

    async def approve(self, import_id: int, actor: str | None) -> dict[str, Any]:
        staged = await self._decide(import_id, actor, ImportStatus.APPROVED)
        snapshot = await self.get(staged.snapshot_id)
        # Before the pre-restore snapshot, so a refusal writes nothing and the
        # import stays pending.
        denied_at_staging = frozenset(d["section"] for d in (staged.plan or {}).get("denied") or [])
        await self._recheck(snapshot, denied_at_staging)
        # Before anything is overwritten, so the previous state is one click
        # away — contributed sections included, since `take` captures them.
        pre_restore = await self.take(_PRE_RESTORE_NOTE, source=SnapshotSource.PRE_RESTORE)

        try:
            bundle = self.dir_for(snapshot.id)
            result = await apply_bundle(
                self.db,
                self.settings,
                bundle,
                self.blobs,
                self._index_for(snapshot.id),
                note=f"Restored snapshot #{snapshot.id}",
            )
            # Pagebuilder first: every contributor may reference its media.
            # A section left out at staging stays out; one the approver may not
            # apply now is skipped too. Pages restore either way.
            contributed, denied = await apply_sections(
                self.db,
                self.sections,
                snapshot.manifest or {},
                bundle,
                result.pop("name_to_url"),
                self.access,
                denied_at_staging,
            )
            result["sections"] = {name: done["counts"] for name, done in contributed.items()}
            result["denied_sections"] = denied
            # By identity, keyed by section, on the import's own audit row:
            # `history.py` reads the page markers from here. Reassigned so the
            # JSON column sees it.
            applied = {PAGEBUILDER_SECTION: result.pop("applied")}
            applied |= {name: done["applied"] for name, done in contributed.items()}
            # Items stripped again: the audited value never names a section's rows.
            staged.plan = split_items(
                {**(staged.plan or {}), "applied": applied, "denied": denied}
            )[0]
            await self.db.flush()
        except Exception as exc:
            # `take` guards its own capture; this covers the apply below. The
            # raise still rolls the request's transaction back — pages, layout,
            # redirects, every section's rows and `_decide`'s status alike.
            shutil.rmtree(self.dir_for(pre_restore.id), ignore_errors=True)
            # A section that cannot apply after all — a conflict, or a version
            # this host stopped reading since the re-check — is a refusal, not a 500.
            if isinstance(exc, (RestoreConflictError, BundleError)):
                raise _refusal(exc) from exc
            raise
        return result
