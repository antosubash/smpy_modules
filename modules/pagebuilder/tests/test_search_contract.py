"""``pagebuilder.contracts.search_*`` — what news' admin search calls (#130).

Run with no tenant bound, which is a single-tenant host: the framework filters
nothing there, so the ``tenant_id`` pin inside the contract is the only thing
between one tenant's search and another's rows.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pagebuilder.contracts import (
    MediaSearchHit,
    PageSearchHit,
    search_media,
    search_pages,
)
from pagebuilder.models import MediaAsset, Page, PageStatus

pytestmark = [pytest.mark.asyncio, pytest.mark.unbound_tenant]


async def _page(db, slug: str, *, tenant: str = "default", locale: str = "en",
                status: PageStatus = PageStatus.PUBLISHED, trashed: bool = False) -> Page:
    page = Page(
        tenant_id=tenant, slug=slug, title=slug.title(), locale=locale, status=status,
        draft_data={"content": [{"type": "Text", "props": {"text": f"body of {slug}"}}]},
        deleted_at=datetime.now(UTC) if trashed else None,
    )
    db.add(page)
    await db.commit()
    await db.refresh(page)
    return page


async def _asset(db, name: str, *, tenant: str = "default") -> MediaAsset:
    asset = MediaAsset(
        tenant_id=tenant, filename=f"{tenant}-{name}", original_filename=name,
        content_type="image/png",
    )
    db.add(asset)
    await db.commit()
    await db.refresh(asset)
    return asset


async def test_pages_are_pinned_to_the_named_tenant(db) -> None:
    ours = await _page(db, "zircon-ours")
    await _page(db, "zircon-theirs", tenant="other")

    hits, total = await search_pages(
        db, "%zircon%", tenant_id="default", include_drafts=True, limit=10
    )

    assert [h.id for h in hits] == [ours.id]
    assert total == 1
    assert isinstance(hits[0], PageSearchHit)


async def test_pages_match_title_slug_and_body_newest_first(db) -> None:
    a = await _page(db, "alpha")
    b = await _page(db, "beta")

    hits, total = await search_pages(
        db, "%body of%", tenant_id="default", include_drafts=True, limit=1
    )

    # Limited rows, unlimited count.
    assert [h.id for h in hits] == [b.id]
    assert total == 2
    assert hits[0].draft_data == b.draft_data
    assert (await search_pages(db, "%alph%", tenant_id="default", include_drafts=True,
                               limit=5))[0][0].id == a.id


async def test_drafts_only_when_asked_and_trash_never(db) -> None:
    published = await _page(db, "p-one")
    draft = await _page(db, "p-two", status=PageStatus.DRAFT)
    await _page(db, "p-three", trashed=True)

    with_drafts, _ = await search_pages(
        db, "%p-%", tenant_id="default", include_drafts=True, limit=10
    )
    without, total = await search_pages(
        db, "%p-%", tenant_id="default", include_drafts=False, limit=10
    )

    assert {h.id for h in with_drafts} == {published.id, draft.id}
    assert [h.id for h in without] == [published.id]
    assert total == 1
    assert without[0].status is PageStatus.PUBLISHED


async def test_locale_narrows_only_when_given(db) -> None:
    en = await _page(db, "about", locale="en")
    de = await _page(db, "about", locale="de")

    every, _ = await search_pages(db, "%about%", tenant_id="default",
                                  include_drafts=True, limit=10)
    german, total = await search_pages(db, "%about%", tenant_id="default",
                                       include_drafts=True, limit=10, locale="de")

    assert {h.id for h in every} == {en.id, de.id}
    assert [(h.id, h.locale) for h in german] == [(de.id, "de")]
    assert total == 1


async def test_media_is_pinned_to_the_named_tenant(db) -> None:
    ours = await _asset(db, "hero.png")
    theirs = await _asset(db, "hero.png", tenant="other")

    hits, total = await search_media(db, "%hero%", tenant_id="default", limit=10)
    other, _ = await search_media(db, "%hero%", tenant_id="other", limit=10)

    assert [h.id for h in hits] == [ours.id]
    assert total == 1
    assert isinstance(hits[0], MediaSearchHit)
    assert [h.id for h in other] == [theirs.id]


async def test_media_matches_the_stored_name_too(db) -> None:
    asset = await _asset(db, "photo.png")

    hits, _ = await search_media(db, "%default-photo%", tenant_id="default", limit=10)

    assert [h.id for h in hits] == [asset.id]
