"""A page's history says when a bulk snapshot restore wrote it (#79).

The marker comes from the approved import's audit row — what the apply
recorded, by page identity — so these tests drive the real restore flow and
then read the history endpoint.
"""

from __future__ import annotations

import pytest
from page_helpers import create_draft
from pagebuilder.models import PendingImport

pytestmark = pytest.mark.asyncio

_SNAPSHOTS = "/api/pagebuilder/snapshots"
_PAGES = "/api/pagebuilder/pages"


async def _snapshot(client) -> int:
    response = await client.post(_SNAPSHOTS, json={})
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def _stage(client, snapshot_id: int) -> int:
    staged = await client.post(f"{_SNAPSHOTS}/{snapshot_id}/restore")
    assert staged.status_code == 201, staged.text
    return staged.json()["id"]


async def _restore(client, snapshot_id: int) -> int:
    import_id = await _stage(client, snapshot_id)
    applied = await client.post(f"/api/pagebuilder/imports/{import_id}/approve")
    assert applied.status_code == 200, applied.text
    return import_id


async def _restores(client, page_id: int) -> list[dict]:
    response = await client.get(f"{_PAGES}/{page_id}/revisions")
    assert response.status_code == 200, response.text
    return response.json()["restores"]


async def test_an_overwritten_page_names_the_snapshot(authed_client):
    page = await create_draft(authed_client, slug="home", title="Before")
    snapshot_id = await _snapshot(authed_client)
    await authed_client.put(f"{_PAGES}/{page['id']}", json={"title": "After"})

    import_id = await _restore(authed_client, snapshot_id)

    [marker] = await _restores(authed_client, page["id"])
    assert marker["snapshot_id"] == snapshot_id
    assert marker["import_id"] == import_id
    assert marker["change"] == "overwritten"
    assert marker["restored_at"]
    # Revisions are untouched: the restore still writes none per page.
    response = await authed_client.get(f"{_PAGES}/{page['id']}/revisions")
    assert response.json()["items"] == []


async def test_an_unchanged_page_gets_no_marker(authed_client):
    page = await create_draft(authed_client, slug="home", title="Same")
    snapshot_id = await _snapshot(authed_client)
    await _restore(authed_client, snapshot_id)
    assert await _restores(authed_client, page["id"]) == []


async def test_a_rejected_restore_leaves_no_marker(authed_client):
    page = await create_draft(authed_client, slug="home", title="Before")
    snapshot_id = await _snapshot(authed_client)
    await authed_client.put(f"{_PAGES}/{page['id']}", json={"title": "After"})
    import_id = await _stage(authed_client, snapshot_id)
    rejected = await authed_client.post(
        f"/api/pagebuilder/imports/{import_id}/reject", json={"note": "no"}
    )
    assert rejected.status_code == 200, rejected.text
    assert await _restores(authed_client, page["id"]) == []


async def test_a_page_the_restore_created_is_marked_created(authed_client):
    page = await create_draft(authed_client, slug="about", title="About")
    snapshot_id = await _snapshot(authed_client)
    # Gone for good, so the bundle's "about" is absent and restore creates it.
    assert (await authed_client.delete(f"{_PAGES}/{page['id']}")).status_code == 204
    purged = await authed_client.delete(f"{_PAGES}/{page['id']}/purge")
    assert purged.status_code == 204, purged.text

    await _restore(authed_client, snapshot_id)

    listing = (await authed_client.get(_PAGES)).json()["items"]
    recreated = next(p for p in listing if p["slug"] == "about")
    [marker] = await _restores(authed_client, recreated["id"])
    assert marker["change"] == "created"


async def test_a_page_younger_than_the_restore_is_not_credited(authed_client):
    page = await create_draft(authed_client, slug="home", title="Before")
    snapshot_id = await _snapshot(authed_client)
    await authed_client.put(f"{_PAGES}/{page['id']}", json={"title": "After"})
    await _restore(authed_client, snapshot_id)

    # Binned and purged after the restore, then made again by hand under the
    # same slug: a different page the restore never wrote.
    assert (await authed_client.delete(f"{_PAGES}/{page['id']}")).status_code == 204
    purged = await authed_client.delete(f"{_PAGES}/{page['id']}/purge")
    assert purged.status_code == 204, purged.text
    fresh = await create_draft(authed_client, slug="home", title="Fresh")
    assert await _restores(authed_client, fresh["id"]) == []


async def test_a_page_renamed_after_the_restore_keeps_its_marker(authed_client):
    page = await create_draft(authed_client, slug="home", title="Before")
    snapshot_id = await _snapshot(authed_client)
    await authed_client.put(f"{_PAGES}/{page['id']}", json={"title": "After"})
    await _restore(authed_client, snapshot_id)

    # The plan names the page by its old slug; the rename's redirect links it.
    renamed = await authed_client.put(f"{_PAGES}/{page['id']}", json={"slug": "start"})
    assert renamed.status_code == 200, renamed.text
    [marker] = await _restores(authed_client, page["id"])
    assert marker["snapshot_id"] == snapshot_id


async def test_markers_are_newest_first(authed_client):
    page = await create_draft(authed_client, slug="home", title="One")
    first = await _snapshot(authed_client)
    await authed_client.put(f"{_PAGES}/{page['id']}", json={"title": "Two"})
    second = await _snapshot(authed_client)

    await _restore(authed_client, first)
    await _restore(authed_client, second)

    markers = await _restores(authed_client, page["id"])
    assert [m["snapshot_id"] for m in markers] == [second, first]


# --- recorded at apply time, matched by page identity (Codex review) -------


def _factory(client):
    return client._transport.app.state.sm.db.session_factory


async def _applied(client, import_id: int) -> dict:
    async with _factory(client)() as db:
        staged = await db.get(PendingImport, import_id)
        return dict(staged.plan["applied"]["pagebuilder"])


async def _purge(client, page_id: int) -> None:
    assert (await client.delete(f"{_PAGES}/{page_id}")).status_code == 204
    purged = await client.delete(f"{_PAGES}/{page_id}/purge")
    assert purged.status_code == 204, purged.text


async def _by_slug(client, slug: str) -> dict:
    listing = (await client.get(_PAGES)).json()["items"]
    return next(p for p in listing if p["slug"] == slug)


async def test_the_apply_records_what_it_wrote_by_page(authed_client):
    home = await create_draft(authed_client, slug="home", title="Before")
    await create_draft(authed_client, slug="same", title="Same")
    gone = await create_draft(authed_client, slug="gone", title="Gone")
    snapshot_id = await _snapshot(authed_client)
    await authed_client.put(f"{_PAGES}/{home['id']}", json={"title": "After"})
    await _purge(authed_client, gone["id"])

    import_id = await _restore(authed_client, snapshot_id)

    applied = await _applied(authed_client, import_id)
    recreated = await _by_slug(authed_client, "gone")
    assert [e["id"] for e in applied["created"]] == [recreated["id"]]
    assert [e["id"] for e in applied["overwritten"]] == [home["id"]]
    assert all(e["created_at"] for e in applied["created"] + applied["overwritten"])


async def test_a_page_recreated_by_hand_soon_after_is_not_credited(authed_client):
    # Codex #1: purge the page the restore created and make the same
    # locale/slug again within the hour. Slug and time window both match —
    # SQLite even hands it the same id — but it is not that page.
    page = await create_draft(authed_client, slug="about", title="About")
    snapshot_id = await _snapshot(authed_client)
    await _purge(authed_client, page["id"])
    await _restore(authed_client, snapshot_id)

    restored = await _by_slug(authed_client, "about")
    assert [m["change"] for m in await _restores(authed_client, restored["id"])] == ["created"]
    await _purge(authed_client, restored["id"])

    by_hand = await create_draft(authed_client, slug="about", title="By hand")
    assert await _restores(authed_client, by_hand["id"]) == []


async def test_a_later_restore_does_not_erase_a_renamed_pages_marker(authed_client):
    # Codex #3: the old match went through the rename's redirect, which a
    # later restore replaces along with the rest of the redirect table.
    other = await create_draft(authed_client, slug="other", title="Other")
    without_home = await _snapshot(authed_client)
    page = await create_draft(authed_client, slug="home", title="Before")
    first = await _snapshot(authed_client)
    await authed_client.put(f"{_PAGES}/{page['id']}", json={"title": "After"})
    first_import = await _restore(authed_client, first)

    renamed = await authed_client.put(f"{_PAGES}/{page['id']}", json={"slug": "start"})
    assert renamed.status_code == 200, renamed.text
    await authed_client.put(f"{_PAGES}/{other['id']}", json={"title": "Changed"})
    # `without_home` carries no redirects, so restoring it empties the table
    # — the home→start redirect included — and leaves "start" untouched.
    second_import = await _restore(authed_client, without_home)

    markers = await _restores(authed_client, page["id"])
    assert [m["import_id"] for m in markers] == [first_import]
    [other_marker] = await _restores(authed_client, other["id"])
    assert other_marker["import_id"] == second_import


async def test_an_edit_between_staging_and_approval_is_credited(authed_client):
    # Codex #4: staged while identical (the plan says unchanged), edited,
    # then approved — the apply overwrote the edit, so history says so.
    page = await create_draft(authed_client, slug="home", title="Same")
    snapshot_id = await _snapshot(authed_client)
    import_id = await _stage(authed_client, snapshot_id)
    await authed_client.put(f"{_PAGES}/{page['id']}", json={"title": "Edited"})
    approved = await authed_client.post(f"/api/pagebuilder/imports/{import_id}/approve")
    assert approved.status_code == 200, approved.text

    [marker] = await _restores(authed_client, page["id"])
    assert (marker["import_id"], marker["change"]) == (import_id, "overwritten")


async def test_a_record_without_applied_falls_back_to_the_plan(authed_client):
    # Imports approved before `applied` was recorded are read the old,
    # best-effort way: by (locale, slug) from the staged plan.
    page = await create_draft(authed_client, slug="home", title="Before")
    snapshot_id = await _snapshot(authed_client)
    await authed_client.put(f"{_PAGES}/{page['id']}", json={"title": "After"})
    import_id = await _restore(authed_client, snapshot_id)

    async with _factory(authed_client)() as db:
        staged = await db.get(PendingImport, import_id)
        staged.plan = {k: v for k, v in staged.plan.items() if k != "applied"}
        await db.commit()

    [marker] = await _restores(authed_client, page["id"])
    assert (marker["import_id"], marker["change"]) == (import_id, "overwritten")


async def test_a_record_in_the_flat_applied_shape_still_marks(authed_client):
    # Imports approved before #80 hold pagebuilder's lists at the top level of
    # `applied`; the keyed shape (`{"pagebuilder": ...}`) must not hide them.
    page = await create_draft(authed_client, slug="home", title="Before")
    snapshot_id = await _snapshot(authed_client)
    await authed_client.put(f"{_PAGES}/{page['id']}", json={"title": "After"})
    import_id = await _restore(authed_client, snapshot_id)

    async with _factory(authed_client)() as db:
        staged = await db.get(PendingImport, import_id)
        flat = staged.plan["applied"]["pagebuilder"]
        staged.plan = {**staged.plan, "applied": flat}
        await db.commit()

    [marker] = await _restores(authed_client, page["id"])
    assert (marker["import_id"], marker["change"]) == (import_id, "overwritten")
