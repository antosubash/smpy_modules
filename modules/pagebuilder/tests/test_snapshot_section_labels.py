"""What the screens need to name contributed sections (#80, PR 3).

The snapshot list and both Import / Export screens carry each registered
section's catalogue keys, so the client labels a row's counts without knowing
the contributor; and a page's restore marker counts what the same restore
wrote in each section — counts only, whoever reads the page's history.
"""

from __future__ import annotations

import pytest
from bundle_fake import NotesSection, notes_client, seed_note
from page_helpers import create_draft

pytestmark = pytest.mark.asyncio

_SNAPSHOTS = "/api/pagebuilder/snapshots"
_INERTIA = {"X-Inertia": "true"}
_NOTES_LABELS = {
    "section": "notes",
    "label_key": "notes.bundle.title",
    "count_label_keys": {"notes": "notes.bundle.counts.notes"},
}


@pytest.fixture
async def client(tmp_path):
    async for c in notes_client(tmp_path, NotesSection()):
        yield c


async def test_the_snapshot_list_names_each_registered_section(client):
    response = await client.get(_SNAPSHOTS)
    assert response.status_code == 200
    assert response.json()["sections"] == [_NOTES_LABELS]


async def test_a_host_without_contributors_lists_no_sections(authed_client):
    response = await authed_client.get(_SNAPSHOTS)
    assert response.json()["sections"] == []


async def test_both_screens_carry_the_section_labels(client):
    created = await client.post(_SNAPSHOTS, json={})
    await client.post(f"{_SNAPSHOTS}/{created.json()['id']}/restore")

    listing = await client.get("/pagebuilder/content", headers=_INERTIA)
    assert listing.json()["props"]["sections"] == [_NOTES_LABELS]
    review = await client.get("/pagebuilder/content/review", headers=_INERTIA)
    props = review.json()["props"]
    assert props["sections"] == [_NOTES_LABELS]
    assert props["pending"]["plan"]["sections"][0]["label_key"] == "notes.bundle.title"


async def test_a_restore_marker_counts_what_the_restore_wrote_in_each_section(client):
    page = await create_draft(client, slug="home", title="Before")
    await seed_note(client, "welcome", {"text": "hi"})
    await seed_note(client, "about", {"text": "us"})
    snapshot = (await client.post(_SNAPSHOTS, json={})).json()
    await client.put(f"/api/pagebuilder/pages/{page['id']}", json={"title": "After"})

    staged = (await client.post(f"{_SNAPSHOTS}/{snapshot['id']}/restore")).json()
    approved = await client.post(f"/api/pagebuilder/imports/{staged['id']}/approve")
    assert approved.status_code == 200, approved.text
    assert approved.json()["sections"] == {"notes": {"notes": 2}}

    history = await client.get(f"/api/pagebuilder/pages/{page['id']}/revisions")
    [marker] = history.json()["restores"]
    # The fake records each note it wrote under `applied.notes.written`.
    assert marker["sections"] == [
        {"section": "notes", "label_key": "notes.bundle.title", "count": 2}
    ]


async def test_a_pages_only_restore_marker_names_no_sections(authed_client):
    page = await create_draft(authed_client, slug="home", title="Before")
    snapshot = (await authed_client.post(_SNAPSHOTS, json={})).json()
    await authed_client.put(f"/api/pagebuilder/pages/{page['id']}", json={"title": "After"})
    staged = (await authed_client.post(f"{_SNAPSHOTS}/{snapshot['id']}/restore")).json()
    await authed_client.post(f"/api/pagebuilder/imports/{staged['id']}/approve")

    history = await authed_client.get(f"/api/pagebuilder/pages/{page['id']}/revisions")
    [marker] = history.json()["restores"]
    assert marker["sections"] == []
