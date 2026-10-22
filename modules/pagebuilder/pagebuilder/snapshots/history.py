"""Which bulk restores touched a page, read back from the import audit trail.

A restore deliberately writes no ``PageRevision`` per page (see the design's
§Out: the ``pre_restore`` snapshot already holds every page's before-state,
once). The cost was that a page's history panel could not explain a change a
restore made. This closes that gap without writing anything: an approved
``PendingImport`` already records who applied which snapshot and when, and its
plan names every page it created or overwrote, so the marker is derived from
that row on read.

Three edges are worth knowing, all consequences of reading rather than writing:

* the plan names pages by ``(locale, slug)``, so a page renamed afterwards is
  matched through the redirects its rename left behind;
* deleting a snapshot deletes the imports that point at it, and with them the
  markers — the audit row is the only record there is;
* a page created long after a restore that happened to reuse a slug the
  restore created is not credited with it (see :data:`_CREATION_SLACK`).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from pagebuilder.models import ImportStatus, Page, PageRedirect, PendingImport

# The plan lists that mean "the restore wrote this page". ``unchanged`` and
# ``untouched`` pages were left exactly as they were, so they get no marker.
_CHANGES = {"new": "created", "overwritten": "overwritten"}

_CREATION_SLACK = timedelta(hours=1)
"""How far a page's ``created_at`` may trail the restore that created it.

``decided_at`` is stamped before the apply runs, so a page the restore itself
created is always a little younger than the decision — by however long the
apply took, media uploads included. A page born more than this after the
decision was made by someone else, after the restored one was deleted, and
the marker would credit the restore with a page it never wrote.
"""


def _aware(value: datetime) -> datetime:
    # SQLite hands back naive datetimes for timezone-aware columns.
    return value if value.tzinfo else value.replace(tzinfo=UTC)


async def _slugs_of(db: AsyncSession, page: Page) -> set[str]:
    """Every slug this page has answered to in its own language."""
    result = await db.execute(
        select(PageRedirect.from_slug).where(
            PageRedirect.page_id == page.id, PageRedirect.locale == page.locale
        )
    )
    return {page.slug, *(slug for (slug,) in result)}


async def restore_markers(db: AsyncSession, page: Page) -> list[dict[str, Any]]:
    """Approved restores that wrote *page*, newest first."""
    slugs = await _slugs_of(db, page)
    result = await db.execute(
        select(PendingImport)
        .where(PendingImport.status == ImportStatus.APPROVED)
        .order_by(PendingImport.id.desc())
    )
    created = _aware(page.created_at)
    markers: list[dict[str, Any]] = []
    for staged in result.scalars().all():
        if staged.decided_at is None:
            continue
        restored_at = _aware(staged.decided_at)
        pages = (staged.plan or {}).get("pages") or {}
        for bucket, change in _CHANGES.items():
            hit = any(
                entry.get("locale") == page.locale and entry.get("slug") in slugs
                for entry in pages.get(bucket) or []
                if isinstance(entry, dict)
            )
            if not hit:
                continue
            if change == "created" and created - restored_at > _CREATION_SLACK:
                break
            if change == "overwritten" and created > restored_at:
                break
            markers.append(
                {
                    "import_id": staged.id,
                    "snapshot_id": staged.snapshot_id,
                    "change": change,
                    "restored_at": restored_at,
                    "restored_by": staged.decided_by,
                }
            )
            break
    return markers
