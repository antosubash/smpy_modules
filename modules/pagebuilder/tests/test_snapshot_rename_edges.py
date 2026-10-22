"""The harder corners of restoring onto renamed pages (#205).

Other languages, slug swaps, parents and redirects resolving through restored
slugs, the audit markers, and the approval-time refusal over HTTP — which is
where the rollback of a refused approval is actually observable.
"""

from __future__ import annotations

import pytest
from page_helpers import create_draft
from pagebuilder.models import Page
from pagebuilder.snapshots.match import RestoreConflictError, match_pages
from test_snapshot_rename import _page, _pages, _redirects, _rename, _restore, _snapshot

_SNAPSHOTS = "/api/pagebuilder/snapshots"
_PAGES = "/api/pagebuilder/pages"


async def test_a_renamed_translation_moves_back_without_touching_its_sibling(
    bilingual_snapshot_db,
):
    session = bilingual_snapshot_db.session
    en = await _page(session, "about")
    # Same group, same slug, other language: identity is the pair, not either half.
    de = await _page(session, "about", locale="de", translation_group=en.translation_group)
    await _rename(session, en, "en-old")
    await _rename(session, en, "about")  # leaves an English redirect behind
    snapshot_id = await _snapshot(bilingual_snapshot_db)
    await _rename(session, de, "ueber-uns")

    plan, _ = await _restore(bilingual_snapshot_db, snapshot_id)

    assert [(e["locale"], e["renamed_from"]) for e in plan["pages"]["overwritten"]] == [
        ("de", "ueber-uns")
    ]
    assert [e["locale"] for e in plan["pages"]["unchanged"]] == ["en"]
    by_locale = {p.locale: p for p in await _pages(session)}
    assert (by_locale["en"].id, by_locale["en"].slug) == (en.id, "about")
    assert (by_locale["de"].id, by_locale["de"].slug) == (de.id, "about")
    assert await _redirects(session) == {
        ("en", "en-old"): en.id,
        ("de", "ueber-uns"): de.id,
    }


async def test_a_sibling_added_after_the_snapshot_is_untouched(bilingual_snapshot_db):
    session = bilingual_snapshot_db.session
    en = await _page(session, "about")
    snapshot_id = await _snapshot(bilingual_snapshot_db)
    de = await _page(session, "ueber", locale="de", translation_group=en.translation_group)
    await _rename(session, en, "about-us")

    plan, _ = await _restore(bilingual_snapshot_db, snapshot_id)

    assert [(e["locale"], e["slug"]) for e in plan["pages"]["untouched"]] == [("de", "ueber")]
    await session.refresh(de)
    assert (de.slug, de.translation_group) == ("ueber", en.translation_group)


async def test_two_pages_that_swapped_slugs_swap_back(snapshot_db):
    session = snapshot_db.session
    first = await _page(session, "x", title="First")
    second = await _page(session, "y", title="Second")
    snapshot_id = await _snapshot(snapshot_db)
    await _rename(session, first, "tmp")
    await _rename(session, second, "x")
    await _rename(session, first, "y")

    _, result = await _restore(snapshot_db, snapshot_id)

    assert result["pages_created"] == 0
    slugs = {p.id: p.slug for p in await _pages(session)}
    assert slugs == {first.id: "x", second.id: "y"}
    # Each address is a page again, so neither redirects — and the scratch
    # one was not in the snapshot, whose redirect table the restore rebuilds.
    assert await _redirects(session) == {}


async def test_parents_and_redirects_resolve_through_restored_slugs(snapshot_db):
    session = snapshot_db.session
    parent = await _page(session, "docs")
    child = await _page(session, "intro", parent_id=parent.id)
    await _rename(session, parent, "legacy")
    await _rename(session, parent, "docs")
    snapshot_id = await _snapshot(snapshot_db)
    await _rename(session, parent, "guides")

    plan, _ = await _restore(snapshot_db, snapshot_id)

    assert sorted(plan["redirects"]["added"]) == ["guides"]
    assert plan["redirects"]["dropped"] == []
    await session.refresh(child)
    assert child.parent_id == parent.id
    redirects = await _redirects(session)
    assert redirects == {("en", "legacy"): parent.id, ("en", "guides"): parent.id}
    # No temporary address survives the flush.
    assert all(not p.slug.startswith("~") for p in await _pages(session))


def test_two_documents_in_one_group_and_language_are_a_conflict():
    pages = {
        ("en", "a"): {"slug": "a", "translation_group": "g"},
        ("en", "b"): {"slug": "b", "translation_group": "g"},
    }
    with pytest.raises(RestoreConflictError, match="same page"):
        match_pages(pages, [])


def test_a_bundle_without_groups_falls_back_to_the_slug():
    """Version 1 bundles carry no group: the address is all there is."""
    live = Page(id=7, slug="home", title="Home", locale="en")
    match = match_pages({("en", "home"): {"slug": "home"}}, [live])
    assert match.rows == {("en", "home"): live}
    assert match.creates == [] and match.untouched == []


# --- over HTTP: markers and the refused approval -----------------------------


async def _restores(client, page_id: int) -> list[dict]:
    response = await client.get(f"{_PAGES}/{page_id}/revisions")
    assert response.status_code == 200, response.text
    return response.json()["restores"]


async def _take(client) -> int:
    response = await client.post(_SNAPSHOTS, json={})
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def _stage(client, snapshot_id: int) -> int:
    staged = await client.post(f"{_SNAPSHOTS}/{snapshot_id}/restore")
    assert staged.status_code == 201, staged.text
    return staged.json()["id"]


async def test_a_slug_only_restore_is_marked_overwritten(authed_client):
    page = await create_draft(authed_client, slug="old", title="Same")
    snapshot_id = await _take(authed_client)
    renamed = await authed_client.put(f"{_PAGES}/{page['id']}", json={"slug": "newer"})
    assert renamed.status_code == 200, renamed.text
    bystander = await create_draft(authed_client, slug="later", title="Later")

    import_id = await _stage(authed_client, snapshot_id)
    applied = await authed_client.post(f"/api/pagebuilder/imports/{import_id}/approve")
    assert applied.status_code == 200, applied.text

    [marker] = await _restores(authed_client, page["id"])
    assert marker["change"] == "overwritten"
    assert await _restores(authed_client, bystander["id"]) == []


async def test_a_refused_approval_rolls_back_and_stays_pending(authed_client):
    page = await create_draft(authed_client, slug="old", title="Original")
    snapshot_id = await _take(authed_client)
    import_id = await _stage(authed_client, snapshot_id)
    await authed_client.put(f"{_PAGES}/{page['id']}", json={"slug": "newer"})
    squatter = await create_draft(authed_client, slug="old", title="Squatter")

    refused = await authed_client.post(f"/api/pagebuilder/imports/{import_id}/approve")

    assert refused.status_code == 409, refused.text
    assert "/old (en)" in refused.json()["detail"]
    pending = (await authed_client.get("/api/pagebuilder/imports/pending")).json()
    assert (pending["id"], pending["status"]) == (import_id, "pending")
    assert "applied" not in pending["plan"]
    listing = {p["id"]: p["slug"] for p in (await authed_client.get(_PAGES)).json()["items"]}
    assert listing == {page["id"]: "newer", squatter["id"]: "old"}
