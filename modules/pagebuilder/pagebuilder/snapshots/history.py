"""Which bulk restores touched a page, read back from the import audit trail.

A restore deliberately writes no ``PageRevision`` per page (see the design's
§Out: the ``pre_restore`` snapshot already holds every page's before-state,
once). The cost was that a page's history panel could not explain a change a
restore made. This closes that gap without a new table: an approved
``PendingImport`` already records who applied which snapshot and when, and
since the apply also writes ``plan["applied"]`` — the pages it created and
overwrote, worked out from the pages themselves at apply time and named by
:func:`~pagebuilder.snapshots.pages.page_identity` (id plus ``created_at``) —
the marker is read from that row by identity.

Matching by identity is what makes the marker trustworthy. A slug is reused
after a purge and rewritten by a rename, and a later restore replaces the
redirect table a rename left behind; an identity is none of those things. And recording at
apply time rather than reading the staged plan means a page edited between
staging and approval is credited, because the apply did overwrite it.

**Older records are best-effort.** An import approved before ``applied`` was
recorded has only its staged plan, which names pages by ``(locale, slug)``.
For those rows the marker is inferred as it always was: the plan's ``new`` and
``overwritten`` buckets, matched against the page's slug and the slugs its
redirects still remember, with :data:`_CREATION_SLACK` keeping a page created
long after the restore from being credited with it. That inference can miss a
page (a rename whose redirect a later restore dropped; an edit between staging
and approval) and can, within the slack, credit the wrong one — it is the
best those rows allow, and no new row is ever read that way.

Deleting a snapshot deletes the imports that point at it, and with them the
markers — the audit row is the only record there is.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from pagebuilder.models import ImportStatus, Page, PageRedirect, PendingImport
from pagebuilder.snapshots.pages import as_utc, page_identity

APPLIED_KEY = "applied"
"""The key under ``PendingImport.plan`` the apply writes its outcome to."""

# The plan lists that mean "the restore wrote this page". ``unchanged`` and
# ``untouched`` pages were left exactly as they were, so they get no marker.
_CHANGES = {"new": "created", "overwritten": "overwritten"}

_CREATION_SLACK = timedelta(hours=1)
"""Legacy rows only: how far a page's ``created_at`` may trail the restore.

``decided_at`` is stamped before the apply runs, so a page the restore itself
created is always a little younger than the decision. A page born more than
this after it was made by someone else.
"""


async def _slugs_of(db: AsyncSession, page: Page) -> set[str]:
    """Every slug this page has answered to in its own language."""
    result = await db.execute(
        select(PageRedirect.from_slug).where(
            PageRedirect.page_id == page.id, PageRedirect.locale == page.locale
        )
    )
    return {page.slug, *(slug for (slug,) in result)}


def _recorded(applied: Any, page: Page) -> str | None:
    """The outcome an import recorded for *page*, by identity."""
    if not isinstance(applied, dict):
        return None
    identity = page_identity(page)
    for change in ("created", "overwritten"):
        entries = applied.get(change)
        if isinstance(entries, list) and identity in entries:
            return change
    return None


def _inferred(
    plan: dict[str, Any], page: Page, slugs: set[str], restored_at: datetime
) -> str | None:
    """Best-effort outcome for an import that predates ``applied``."""
    pages = plan.get("pages") or {}
    created = as_utc(page.created_at)
    for bucket, change in _CHANGES.items():
        hit = any(
            entry.get("locale") == page.locale and entry.get("slug") in slugs
            for entry in pages.get(bucket) or []
            if isinstance(entry, dict)
        )
        if not hit:
            continue
        if change == "created" and created - restored_at > _CREATION_SLACK:
            return None
        if change == "overwritten" and created > restored_at:
            return None
        return change
    return None


async def restore_markers(db: AsyncSession, page: Page) -> list[dict[str, Any]]:
    """Approved restores that wrote *page*, newest first."""
    result = await db.execute(
        select(PendingImport)
        .where(PendingImport.status == ImportStatus.APPROVED)
        .order_by(PendingImport.id.desc())
    )
    slugs: set[str] | None = None
    markers: list[dict[str, Any]] = []
    for staged in result.scalars().all():
        if staged.decided_at is None:
            continue
        restored_at = as_utc(staged.decided_at)
        plan = staged.plan or {}
        if APPLIED_KEY in plan:
            change = _recorded(plan[APPLIED_KEY], page)
        else:
            if slugs is None:
                slugs = await _slugs_of(db, page)
            change = _inferred(plan, page, slugs, restored_at)
        if change is None:
            continue
        markers.append(
            {
                "import_id": staged.id,
                "snapshot_id": staged.snapshot_id,
                "change": change,
                "restored_at": restored_at,
                "restored_by": staged.decided_by,
            }
        )
    return markers
