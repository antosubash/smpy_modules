"""Integration tests for the editor → publisher approval workflow.

Covers the three new transitions (submit / approve / reject), the
``submitted_for_review`` status, the rejection-note round-trip, and
the role-based gating that lets an editor submit but not publish.
"""

from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


async def _create_draft(client: AsyncClient, *, slug: str = "post") -> dict:
    response = await client.post(
        "/api/pagebuilder/pages",
        json={
            "title": "Draft",
            "slug": slug,
            "draft_data": {"content": ["hello"]},
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


async def test_submit_moves_draft_to_review(authed_client: AsyncClient) -> None:
    page = await _create_draft(authed_client)
    response = await authed_client.post(
        f"/api/pagebuilder/pages/{page['id']}/submit"
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "submitted_for_review"
    assert body["rejection_note"] is None


async def test_submit_rejects_non_draft_status(authed_client: AsyncClient) -> None:
    page = await _create_draft(authed_client)
    pub = await authed_client.post(
        f"/api/pagebuilder/pages/{page['id']}/publish"
    )
    assert pub.status_code == 200
    # Already published — submit should refuse.
    response = await authed_client.post(
        f"/api/pagebuilder/pages/{page['id']}/submit"
    )
    assert response.status_code == 409


async def test_submit_appears_in_pending_queue(authed_client: AsyncClient) -> None:
    page = await _create_draft(authed_client)
    await authed_client.post(f"/api/pagebuilder/pages/{page['id']}/submit")
    response = await authed_client.get("/api/pagebuilder/pages/pending")
    assert response.status_code == 200
    items = response.json()["items"]
    assert [p["id"] for p in items] == [page["id"]]
    assert items[0]["status"] == "submitted_for_review"


async def test_pending_queue_excludes_drafts_and_published(
    authed_client: AsyncClient,
) -> None:
    draft = await _create_draft(authed_client, slug="draft-only")
    submitted = await _create_draft(authed_client, slug="submitted")
    await authed_client.post(
        f"/api/pagebuilder/pages/{submitted['id']}/submit"
    )
    published = await _create_draft(authed_client, slug="published")
    await authed_client.post(f"/api/pagebuilder/pages/{published['id']}/publish")

    response = await authed_client.get("/api/pagebuilder/pages/pending")
    assert response.status_code == 200
    pending_ids = {p["id"] for p in response.json()["items"]}
    assert pending_ids == {submitted["id"]}
    assert draft["id"] not in pending_ids
    assert published["id"] not in pending_ids


async def test_approve_publishes_and_records_one_revision(
    authed_client: AsyncClient,
) -> None:
    page = await _create_draft(authed_client)
    await authed_client.post(f"/api/pagebuilder/pages/{page['id']}/submit")
    response = await authed_client.post(
        f"/api/pagebuilder/pages/{page['id']}/approve"
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "published"
    assert body["has_published"] is True

    revisions = (
        await authed_client.get(f"/api/pagebuilder/pages/{page['id']}/revisions")
    ).json()["items"]
    # Order is desc by id, so the most recent event is first.
    events = [r["event"] for r in revisions]
    assert events == ["approve", "submit"]


async def test_approve_rejects_non_submitted(authed_client: AsyncClient) -> None:
    page = await _create_draft(authed_client)
    # No submit step — approve should refuse.
    response = await authed_client.post(
        f"/api/pagebuilder/pages/{page['id']}/approve"
    )
    assert response.status_code == 409


async def test_reject_sends_back_to_draft_with_note(
    authed_client: AsyncClient,
) -> None:
    page = await _create_draft(authed_client)
    await authed_client.post(f"/api/pagebuilder/pages/{page['id']}/submit")
    response = await authed_client.post(
        f"/api/pagebuilder/pages/{page['id']}/reject",
        json={"note": "Needs more punctuation."},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == "draft"
    assert body["rejection_note"] == "Needs more punctuation."


async def test_reject_requires_non_empty_note(authed_client: AsyncClient) -> None:
    page = await _create_draft(authed_client)
    await authed_client.post(f"/api/pagebuilder/pages/{page['id']}/submit")
    response = await authed_client.post(
        f"/api/pagebuilder/pages/{page['id']}/reject",
        json={"note": ""},
    )
    assert response.status_code == 422


async def test_reject_revision_carries_note(authed_client: AsyncClient) -> None:
    page = await _create_draft(authed_client)
    await authed_client.post(f"/api/pagebuilder/pages/{page['id']}/submit")
    await authed_client.post(
        f"/api/pagebuilder/pages/{page['id']}/reject",
        json={"note": "Tone is off."},
    )
    revisions = (
        await authed_client.get(f"/api/pagebuilder/pages/{page['id']}/revisions")
    ).json()["items"]
    reject_rev = next(r for r in revisions if r["event"] == "reject")
    assert reject_rev["note"] == "Tone is off."


async def test_resubmit_after_reject_clears_note(authed_client: AsyncClient) -> None:
    page = await _create_draft(authed_client)
    await authed_client.post(f"/api/pagebuilder/pages/{page['id']}/submit")
    await authed_client.post(
        f"/api/pagebuilder/pages/{page['id']}/reject",
        json={"note": "Try again."},
    )
    response = await authed_client.post(
        f"/api/pagebuilder/pages/{page['id']}/submit"
    )
    assert response.status_code == 200
    assert response.json()["rejection_note"] is None


async def test_publish_clears_stale_rejection_note(
    authed_client: AsyncClient,
) -> None:
    page = await _create_draft(authed_client)
    await authed_client.post(f"/api/pagebuilder/pages/{page['id']}/submit")
    await authed_client.post(
        f"/api/pagebuilder/pages/{page['id']}/reject",
        json={"note": "Nope."},
    )
    pub = await authed_client.post(
        f"/api/pagebuilder/pages/{page['id']}/publish"
    )
    assert pub.status_code == 200
    assert pub.json()["rejection_note"] is None


async def test_editor_can_submit_but_not_publish_or_approve(
    editor_client: AsyncClient,
) -> None:
    """Acceptance criterion: editor without publish permission can submit
    but not publish."""
    page = await _create_draft(editor_client)

    # Submit succeeds — pagebuilder.edit covers it.
    submit = await editor_client.post(
        f"/api/pagebuilder/pages/{page['id']}/submit"
    )
    assert submit.status_code == 200, submit.text

    # Publish is gated by pagebuilder.publish.
    publish = await editor_client.post(
        f"/api/pagebuilder/pages/{page['id']}/publish"
    )
    assert publish.status_code == 403

    # Approve / reject are gated by pagebuilder.approve.
    approve = await editor_client.post(
        f"/api/pagebuilder/pages/{page['id']}/approve"
    )
    assert approve.status_code == 403
    reject = await editor_client.post(
        f"/api/pagebuilder/pages/{page['id']}/reject",
        json={"note": "blocked"},
    )
    assert reject.status_code == 403


async def test_editor_cannot_see_pending_queue(editor_client: AsyncClient) -> None:
    """Pending queue is the approver's view — editors get 403, not the list."""
    response = await editor_client.get("/api/pagebuilder/pages/pending")
    assert response.status_code == 403


async def test_approver_can_run_full_workflow(approver_client: AsyncClient) -> None:
    page = await _create_draft(approver_client)
    submit = await approver_client.post(
        f"/api/pagebuilder/pages/{page['id']}/submit"
    )
    assert submit.status_code == 200
    queue = await approver_client.get("/api/pagebuilder/pages/pending")
    assert queue.status_code == 200
    assert len(queue.json()["items"]) == 1
    approve = await approver_client.post(
        f"/api/pagebuilder/pages/{page['id']}/approve"
    )
    assert approve.status_code == 200
    assert approve.json()["status"] == "published"


async def test_approve_revision_is_restorable(
    authed_client: AsyncClient,
) -> None:
    """An approve event carries the same data snapshot as a direct
    publish, so the editor's restore-as-draft affordance treats it
    identically."""
    page = await _create_draft(authed_client)
    await authed_client.post(f"/api/pagebuilder/pages/{page['id']}/submit")
    await authed_client.post(f"/api/pagebuilder/pages/{page['id']}/approve")
    revisions = (
        await authed_client.get(f"/api/pagebuilder/pages/{page['id']}/revisions")
    ).json()["items"]
    approve_rev = next(r for r in revisions if r["event"] == "approve")
    restored = await authed_client.post(
        f"/api/pagebuilder/pages/{page['id']}/revisions/{approve_rev['id']}/restore"
    )
    assert restored.status_code == 200
    assert restored.json()["draft_data"] == {"content": ["hello"]}
