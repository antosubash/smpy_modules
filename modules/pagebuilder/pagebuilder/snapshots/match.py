"""Which live page each page in a bundle restores onto (#205).

One function, used by both the plan and the apply, so the screen an approver
reads and the write that follows cannot disagree about which row a document
lands on. They used to match independently, and both by ``(locale, slug)`` —
so a page renamed after the snapshot was taken looked like a page to create,
and inserting it tripped the ``(tenant, translation_group, locale)`` index the
renamed row still held.

A page's identity, in order of trust:

1. ``(translation_group, locale)``. The group is carried in every bundle this
   code writes and survives a rename, and the locale never changes — so this
   follows a renamed page, trashed included, to the row it actually is. Page
   ids are *not* used: they are host-local, and SQLite hands a purged page's id
   to the next insert, so an id match could overwrite an unrelated page.
2. ``(locale, slug)``, when the group finds nothing — a version 1 bundle with no
   group, a bundle from another host whose pages were made independently, or a
   page whose original was purged. This is the address the restore is about to
   write to, and overwriting what sits there is what restore has always done.

Every bundle page then has a final address, and the one thing that cannot be
resolved is a page the bundle does *not* claim already sitting at one of them:
the snapshot's page has to go back there, and taking the address would mean
silently overwriting, moving or deleting a page nobody asked about. That is a
:class:`RestoreConflictError`, raised before anything is written.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from pagebuilder.models import Page
from pagebuilder.snapshots.pages import PageKey


class RestoreConflictError(Exception):
    """A bundle that cannot land on this site as it stands; fit to show a user."""


@dataclass
class PageMatch:
    rows: dict[PageKey, Page] = field(default_factory=dict)
    """Bundle key → the live row it overwrites."""

    creates: list[PageKey] = field(default_factory=list)
    """Bundle keys with no live row: the restore inserts these."""

    renames: dict[PageKey, str] = field(default_factory=dict)
    """Bundle key → the matched row's slug today, where it differs from the
    bundle's. The restore moves the row back and redirects the newer slug."""

    untouched: list[Page] = field(default_factory=list)
    """Live rows nothing in the bundle claims, trashed ones included."""

    def final_keys(self) -> set[PageKey]:
        """Every ``(locale, slug)`` that will hold a page once the restore lands."""
        return (
            set(self.rows)
            | set(self.creates)
            | {(page.locale, page.slug) for page in self.untouched}
        )

    def rename_redirects(self) -> dict[PageKey, Page]:
        """``(locale, retired slug)`` → page, for every row the restore moves back.

        A retired slug that another page takes over in this same restore — two
        pages swapping addresses — gets no redirect: the address is a page again.
        """
        taken = self.final_keys()
        return {
            (key[0], old): self.rows[key]
            for key, old in self.renames.items()
            if (key[0], old) not in taken
        }


def _group(payload: dict[str, Any]) -> str | None:
    group = payload.get("translation_group")
    return group if isinstance(group, str) and group else None


def match_pages(bundled: dict[PageKey, dict[str, Any]], pages: Iterable[Page]) -> PageMatch:
    """Pair every bundle page with the live row it restores onto.

    *pages* is every page of the tenant, trashed included: a trashed page still
    holds both its slug and its group in the unique indexes, and restoring
    content onto it revives it. One-to-one by construction — a row claimed by
    its group is never also claimed by another document's slug.
    """
    pages = list(pages)
    by_group = {(page.translation_group, page.locale): page for page in pages}
    by_slug = {(page.locale, page.slug): page for page in pages}
    match = PageMatch()
    claimed: set[int | None] = set()

    groups: dict[tuple[str, str], PageKey] = {}
    for key in sorted(bundled):
        group = _group(bundled[key])
        if group is None:
            continue
        if (group, key[0]) in groups:
            # `validate` rejects this at upload; checked again because a
            # second document in one group and language has no row to land on.
            other = groups[(group, key[0])]
            raise RestoreConflictError(
                f"/{other[1]} and /{key[1]} ({key[0]}) are the same page in this snapshot"
            )
        groups[(group, key[0])] = key
        page = by_group.get((group, key[0]))
        if page is not None:
            match.rows[key] = page
            claimed.add(page.id)

    for key in sorted(bundled):
        if key in match.rows:
            continue
        page = by_slug.get(key)
        if page is not None and page.id not in claimed:
            match.rows[key] = page
            claimed.add(page.id)
        else:
            match.creates.append(key)

    match.untouched = [page for page in pages if page.id not in claimed]
    for page in match.untouched:
        key = (page.locale, page.slug)
        if key in bundled:
            raise RestoreConflictError(
                f"/{page.slug} ({page.locale}) now belongs to a different page than the "
                "one this snapshot restores there — rename or purge that page first"
            )
    match.renames = {key: page.slug for key, page in match.rows.items() if page.slug != key[1]}
    return match


async def match_live(db: AsyncSession, bundled: dict[PageKey, dict[str, Any]]) -> PageMatch:
    """:func:`match_pages` against this tenant's pages as they are right now.

    The plan's preflight, and run again at approval rather than trusted from
    the staged plan: pages are renamed, created and purged between staging and
    approval, and a match made against the old state would write onto the
    wrong row. Unfiltered by the trash on purpose; the tenant filter applies.
    """
    result = await db.execute(select(Page))
    return match_pages(bundled, result.scalars().all())
