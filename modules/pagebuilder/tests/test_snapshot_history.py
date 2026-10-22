"""A page's history says when a bulk snapshot restore wrote it (#79).

Read-side only: the marker comes from the approved import's audit row, so
these tests drive the real restore flow and then read the history endpoint.
"""

from __future__ import annotations

import pytest
from page_helpers import create_draft

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
