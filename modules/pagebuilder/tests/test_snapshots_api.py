from __future__ import annotations

import pytest
from conftest import create_draft

pytestmark = pytest.mark.asyncio

_SNAPSHOTS = "/api/pagebuilder/snapshots"
_PENDING = "/api/pagebuilder/imports/pending"


async def _take(client, note=None):
    response = await client.post(_SNAPSHOTS, json={"note": note})
    assert response.status_code == 201, response.text
    return response.json()


async def test_editor_cannot_take_a_snapshot(editor_client):
    response = await editor_client.post(_SNAPSHOTS, json={})
    assert response.status_code == 403


async def test_taking_and_listing(authed_client):
    await create_draft(authed_client, slug="home", title="Home")
    snapshot = await _take(authed_client, "before rework")
    assert snapshot["source"] == "manual"
    assert snapshot["manifest"]["counts"]["pages"] == 1
    assert snapshot["size_bytes"] > 0

    listing = await authed_client.get(_SNAPSHOTS)
    assert [s["note"] for s in listing.json()["items"]] == ["before rework"]


async def test_pending_is_null_when_idle(authed_client):
    response = await authed_client.get(_PENDING)
    assert response.status_code == 200
    assert response.json() is None


async def test_restore_stages_a_plan_without_touching_the_site(authed_client):
    await create_draft(authed_client, slug="home", title="Home")
    snapshot = await _take(authed_client)

    # Change the site after the snapshot so the plan has something to report.
    await create_draft(authed_client, slug="later", title="Later")

    staged = await authed_client.post(f"{_SNAPSHOTS}/{snapshot['id']}/restore")
    assert staged.status_code == 201, staged.text
    plan = staged.json()["plan"]
    assert [p["slug"] for p in plan["pages"]["unchanged"]] == ["home"]
    # "later" is not in the bundle; restore keeps it rather than deleting it.
    assert [p["slug"] for p in plan["pages"]["untouched"]] == ["later"]

    # Still there — staging writes nothing.
    listing = await authed_client.get("/api/pagebuilder/pages")
    assert {p["slug"] for p in listing.json()["items"]} == {"home", "later"}


async def test_second_restore_is_refused_while_one_is_pending(authed_client):
    snapshot = await _take(authed_client)
    first = await authed_client.post(f"{_SNAPSHOTS}/{snapshot['id']}/restore")
    assert first.status_code == 201
    again = await authed_client.post(f"{_SNAPSHOTS}/{snapshot['id']}/restore")
    assert again.status_code == 409


async def test_publish_alone_cannot_approve(publisher_client):
    """The gate is the point: staging a restore must not let you apply it.

    One client, because two would each get their own in-memory database and
    the second would never see the import the first staged.
    """
    snapshot = await _take(publisher_client)
    staged = await publisher_client.post(f"{_SNAPSHOTS}/{snapshot['id']}/restore")
    assert staged.status_code == 201, staged.text

    refused = await publisher_client.post(
        f"/api/pagebuilder/imports/{staged.json()['id']}/approve"
    )
    assert refused.status_code == 403
    # And rejecting is gated the same way.
    assert (
        await publisher_client.post(
            f"/api/pagebuilder/imports/{staged.json()['id']}/reject", json={}
        )
    ).status_code == 403


async def test_approving_takes_a_pre_restore_snapshot_first(approver_client):
    await create_draft(approver_client, slug="home", title="Home")
    snapshot = await _take(approver_client)
    staged = await approver_client.post(f"{_SNAPSHOTS}/{snapshot['id']}/restore")

    applied = await approver_client.post(
        f"/api/pagebuilder/imports/{staged.json()['id']}/approve"
    )
    assert applied.status_code == 200, applied.text
    assert applied.json()["pages_updated"] == 1

    listing = (await approver_client.get(_SNAPSHOTS)).json()["items"]
    sources = [s["source"] for s in listing]
    assert "pre_restore" in sources
    # And the gate is closed again afterwards.
    assert (await approver_client.get(_PENDING)).json() is None


async def test_restoring_brings_back_a_page_deleted_after_the_snapshot(approver_client):
    page = await create_draft(approver_client, slug="home", title="Home")
    snapshot = await _take(approver_client)
    await approver_client.delete(f"/api/pagebuilder/pages/{page['id']}")

    listing = await approver_client.get("/api/pagebuilder/pages")
    assert listing.json()["items"] == []

    staged = await approver_client.post(f"{_SNAPSHOTS}/{snapshot['id']}/restore")
    await approver_client.post(
        f"/api/pagebuilder/imports/{staged.json()['id']}/approve"
    )

    listing = await approver_client.get("/api/pagebuilder/pages")
    assert [p["slug"] for p in listing.json()["items"]] == ["home"]


async def test_rejecting_leaves_the_site_alone_and_clears_the_gate(approver_client):
    await create_draft(approver_client, slug="home", title="Home")
    snapshot = await _take(approver_client)
    staged = await approver_client.post(f"{_SNAPSHOTS}/{snapshot['id']}/restore")

    rejected = await approver_client.post(
        f"/api/pagebuilder/imports/{staged.json()['id']}/reject",
        json={"note": "wrong bundle"},
    )
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"
    assert (await approver_client.get(_PENDING)).json() is None


async def test_deciding_twice_is_refused(approver_client):
    snapshot = await _take(approver_client)
    staged = await approver_client.post(f"{_SNAPSHOTS}/{snapshot['id']}/restore")
    import_id = staged.json()["id"]
    await approver_client.post(f"/api/pagebuilder/imports/{import_id}/reject", json={})
    again = await approver_client.post(
        f"/api/pagebuilder/imports/{import_id}/reject", json={}
    )
    assert again.status_code == 409


async def test_download_then_upload_round_trips_through_the_api(authed_client):
    await create_draft(authed_client, slug="home", title="Home")
    snapshot = await _take(authed_client)

    downloaded = await authed_client.get(f"{_SNAPSHOTS}/{snapshot['id']}/download")
    assert downloaded.status_code == 200
    assert downloaded.headers["content-type"] == "application/zip"

    uploaded = await authed_client.post(
        f"{_SNAPSHOTS}/upload",
        files={"file": ("bundle.zip", downloaded.content, "application/zip")},
    )
    assert uploaded.status_code == 201, uploaded.text
    assert uploaded.json()["source"] == "upload"
    assert uploaded.json()["manifest"]["counts"]["pages"] == 1


async def test_uploading_something_that_is_not_a_bundle_is_refused(authed_client):
    response = await authed_client.post(
        f"{_SNAPSHOTS}/upload",
        files={"file": ("notes.txt", b"just some text", "text/plain")},
    )
    assert response.status_code == 422
    assert "zip" in response.json()["detail"].lower()


async def test_deleting_a_snapshot_removes_it(authed_client):
    snapshot = await _take(authed_client)
    assert (
        await authed_client.delete(f"{_SNAPSHOTS}/{snapshot['id']}")
    ).status_code == 204
    assert (await authed_client.get(_SNAPSHOTS)).json()["items"] == []


async def test_restoring_a_missing_snapshot_is_a_404(authed_client):
    assert (await authed_client.post(f"{_SNAPSHOTS}/999/restore")).status_code == 404
