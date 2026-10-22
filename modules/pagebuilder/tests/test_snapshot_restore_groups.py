"""What a restore does to translation groups and temporary slugs (#205 review).

A page the bundle finds only by its address keeps the live row's group: the
bundle's group would regroup it and detach the live translations that are not
in the bundle. And the scratch slug a moving page passes through must not be
one a page already holds, nor one the restore is about to give a page.
"""

from __future__ import annotations

import pytest
from pagebuilder.models import Page
from pagebuilder.snapshots.match import match_pages
from test_snapshot_rename import _page, _pages, _rename, _restore, _snapshot


@pytest.mark.asyncio
async def test_a_slug_matched_page_keeps_its_live_group_and_siblings(bilingual_snapshot_db):
    session = bilingual_snapshot_db.session
    en = await _page(session, "about", title="Snapshot")
    snapshot_group = en.translation_group
    snapshot_id = await _snapshot(bilingual_snapshot_db)
    # The page at /about is now a different document — another host's, or a
    # replacement — with its own German translation the bundle knows nothing of.
    en.translation_group = "live-group"
    en.title = "Live"
    de = await _page(session, "ueber", locale="de", translation_group="live-group")
    await session.flush()
    assert snapshot_group != "live-group"

    plan, _ = await _restore(bilingual_snapshot_db, snapshot_id)

    assert [e["slug"] for e in plan["pages"]["overwritten"]] == ["about"]
    by_locale = {p.locale: p for p in await _pages(session)}
    assert by_locale["en"].id == en.id
    assert by_locale["en"].title == "Snapshot"
    assert by_locale["en"].translation_group == "live-group"
    assert (by_locale["de"].id, by_locale["de"].translation_group) == (de.id, "live-group")


def test_the_match_says_which_rows_were_found_by_address():
    live = Page(id=3, slug="about", title="About", locale="en", translation_group="live")
    bundled = {("en", "about"): {"slug": "about", "translation_group": "bundle"}}
    match = match_pages(bundled, [live])
    assert match.rows == {("en", "about"): live}
    assert match.by_slug == {("en", "about")}


@pytest.mark.asyncio
async def test_the_temporary_slug_avoids_one_a_page_already_holds(snapshot_db):
    session = snapshot_db.session
    page = await _page(session, "old")
    # A bundle's slugs are not run through the slug pattern, so an imported
    # page can hold an address shaped like the restore's scratch slug.
    squatter = await _page(session, f"~restoring-{page.id}")
    snapshot_id = await _snapshot(snapshot_db)
    await _rename(session, page, "newer")

    _, result = await _restore(snapshot_db, snapshot_id)

    assert result["pages_created"] == 0
    slugs = {p.id: p.slug for p in await _pages(session)}
    assert slugs == {page.id: "old", squatter.id: f"~restoring-{page.id}"}


@pytest.mark.asyncio
async def test_the_plan_does_not_count_a_group_the_restore_keeps(snapshot_db):
    session = snapshot_db.session
    page = await _page(session, "about")
    snapshot_id = await _snapshot(snapshot_db)
    page.translation_group = "live-group"
    await session.flush()

    plan, _ = await _restore(snapshot_db, snapshot_id)

    assert [e["slug"] for e in plan["pages"]["unchanged"]] == ["about"]
    assert plan["applied"]["overwritten"] == []
