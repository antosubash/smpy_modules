"""Integration tests for publish notes + the revisions diff endpoint (issue #16)."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

pytestmark = pytest.mark.asyncio


async def _create(client: AsyncClient, *, slug: str, blocks: list[dict]) -> int:
    response = await client.post(
        "/api/pagebuilder/pages",
        json={
            "title": "v1",
            "slug": slug,
            "meta_description": "first description",
            "draft_data": {"content": blocks},
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _block(block_id: str, type_: str, **props) -> dict:
    return {"type": type_, "props": {"id": block_id, **props}}


async def _publish(client: AsyncClient, page_id: int, note: str | None = None) -> dict:
    payload = {"note": note} if note is not None else None
    response = await client.post(
        f"/api/pagebuilder/pages/{page_id}/publish",
        json=payload,
    )
    assert response.status_code == 200, response.text
    return response.json()


# ── Notes ──────────────────────────────────────────────────────────────


async def test_publish_without_body_still_works(authed_client: AsyncClient) -> None:
    page_id = await _create(authed_client, slug="no-note", blocks=[])
    response = await authed_client.post(f"/api/pagebuilder/pages/{page_id}/publish")
    assert response.status_code == 200
    revisions = (
        await authed_client.get(f"/api/pagebuilder/pages/{page_id}/revisions")
    ).json()["items"]
    assert revisions[0]["note"] is None


async def test_publish_note_is_persisted_on_revision(
    authed_client: AsyncClient,
) -> None:
    page_id = await _create(authed_client, slug="with-note", blocks=[])
    await _publish(authed_client, page_id, note="Initial launch — homepage v1")
    revisions = (
        await authed_client.get(f"/api/pagebuilder/pages/{page_id}/revisions")
    ).json()["items"]
    assert revisions[0]["note"] == "Initial launch — homepage v1"


async def test_publish_note_max_length_2000(authed_client: AsyncClient) -> None:
    page_id = await _create(authed_client, slug="too-long", blocks=[])
    response = await authed_client.post(
        f"/api/pagebuilder/pages/{page_id}/publish",
        json={"note": "x" * 2001},
    )
    assert response.status_code == 422


async def test_approve_carries_note(approver_client: AsyncClient) -> None:
    page_id = await _create(approver_client, slug="approve-note", blocks=[])
    await approver_client.post(f"/api/pagebuilder/pages/{page_id}/submit")
    response = await approver_client.post(
        f"/api/pagebuilder/pages/{page_id}/approve",
        json={"note": "LGTM after copy review"},
    )
    assert response.status_code == 200
    revisions = (
        await approver_client.get(f"/api/pagebuilder/pages/{page_id}/revisions")
    ).json()["items"]
    approve_rows = [r for r in revisions if r["event"] == "approve"]
    assert approve_rows[0]["note"] == "LGTM after copy review"


# ── Diff ───────────────────────────────────────────────────────────────


async def test_diff_reports_added_block(authed_client: AsyncClient) -> None:
    page_id = await _create(
        authed_client, slug="diff-add", blocks=[_block("a", "Heading", text="Hi")]
    )
    await _publish(authed_client, page_id)
    # Add a new block + republish.
    await authed_client.put(
        f"/api/pagebuilder/pages/{page_id}",
        json={
            "draft_data": {
                "content": [
                    _block("a", "Heading", text="Hi"),
                    _block("b", "Text", body="Hello world"),
                ]
            }
        },
    )
    await _publish(authed_client, page_id)

    revisions = (
        await authed_client.get(f"/api/pagebuilder/pages/{page_id}/revisions")
    ).json()["items"]
    new_id, old_id = revisions[0]["id"], revisions[1]["id"]

    diff = await authed_client.get(
        f"/api/pagebuilder/pages/{page_id}/revisions/{old_id}/diff/{new_id}"
    )
    assert diff.status_code == 200
    body = diff.json()
    assert body["blocks"]["added"] == [{"id": "b", "type": "Text", "fields": []}]
    assert body["blocks"]["removed"] == []
    assert body["blocks"]["changed"] == []


async def test_diff_reports_removed_block(authed_client: AsyncClient) -> None:
    page_id = await _create(
        authed_client,
        slug="diff-remove",
        blocks=[_block("a", "Heading"), _block("b", "Text")],
    )
    await _publish(authed_client, page_id)
    await authed_client.put(
        f"/api/pagebuilder/pages/{page_id}",
        json={"draft_data": {"content": [_block("a", "Heading")]}},
    )
    await _publish(authed_client, page_id)

    revisions = (
        await authed_client.get(f"/api/pagebuilder/pages/{page_id}/revisions")
    ).json()["items"]
    diff = (
        await authed_client.get(
            f"/api/pagebuilder/pages/{page_id}"
            f"/revisions/{revisions[1]['id']}/diff/{revisions[0]['id']}"
        )
    ).json()
    assert diff["blocks"]["removed"] == [{"id": "b", "type": "Text", "fields": []}]


async def test_diff_reports_changed_fields(authed_client: AsyncClient) -> None:
    page_id = await _create(
        authed_client,
        slug="diff-change",
        blocks=[_block("a", "Heading", text="Old", level=1)],
    )
    await _publish(authed_client, page_id)
    await authed_client.put(
        f"/api/pagebuilder/pages/{page_id}",
        json={"draft_data": {"content": [_block("a", "Heading", text="New", level=1)]}},
    )
    await _publish(authed_client, page_id)

    revisions = (
        await authed_client.get(f"/api/pagebuilder/pages/{page_id}/revisions")
    ).json()["items"]
    diff = (
        await authed_client.get(
            f"/api/pagebuilder/pages/{page_id}"
            f"/revisions/{revisions[1]['id']}/diff/{revisions[0]['id']}"
        )
    ).json()
    changed = diff["blocks"]["changed"]
    assert len(changed) == 1
    assert changed[0]["id"] == "a"
    assert changed[0]["fields"] == ["text"]


async def test_diff_reports_metadata_changes(authed_client: AsyncClient) -> None:
    page_id = await _create(authed_client, slug="diff-meta", blocks=[])
    await _publish(authed_client, page_id)
    await authed_client.put(
        f"/api/pagebuilder/pages/{page_id}",
        json={"title": "v2 — refreshed", "meta_description": "second description"},
    )
    await _publish(authed_client, page_id)

    revisions = (
        await authed_client.get(f"/api/pagebuilder/pages/{page_id}/revisions")
    ).json()["items"]
    diff = (
        await authed_client.get(
            f"/api/pagebuilder/pages/{page_id}"
            f"/revisions/{revisions[1]['id']}/diff/{revisions[0]['id']}"
        )
    ).json()
    metadata = diff["metadata"]
    assert metadata["title"]["before"] == "v1"
    assert metadata["title"]["after"] == "v2 — refreshed"
    assert metadata["meta_description"]["before"] == "first description"
    assert metadata["meta_description"]["after"] == "second description"


async def test_diff_empty_when_revisions_match(authed_client: AsyncClient) -> None:
    page_id = await _create(
        authed_client, slug="diff-noop", blocks=[_block("a", "Heading")]
    )
    await _publish(authed_client, page_id)
    await _publish(authed_client, page_id)  # publish again, same draft

    revisions = (
        await authed_client.get(f"/api/pagebuilder/pages/{page_id}/revisions")
    ).json()["items"]
    diff = (
        await authed_client.get(
            f"/api/pagebuilder/pages/{page_id}"
            f"/revisions/{revisions[1]['id']}/diff/{revisions[0]['id']}"
        )
    ).json()
    assert diff["metadata"] == {}
    assert diff["blocks"] == {"added": [], "removed": [], "changed": []}


async def test_diff_404_for_revision_from_another_page(
    authed_client: AsyncClient,
) -> None:
    page_a = await _create(authed_client, slug="alpha", blocks=[])
    page_b = await _create(authed_client, slug="bravo", blocks=[])
    await _publish(authed_client, page_a)
    await _publish(authed_client, page_b)
    a_rev = (
        await authed_client.get(f"/api/pagebuilder/pages/{page_a}/revisions")
    ).json()["items"][0]["id"]
    b_rev = (
        await authed_client.get(f"/api/pagebuilder/pages/{page_b}/revisions")
    ).json()["items"][0]["id"]
    response = await authed_client.get(
        f"/api/pagebuilder/pages/{page_a}/revisions/{a_rev}/diff/{b_rev}"
    )
    assert response.status_code == 404


async def test_diff_for_type_change(authed_client: AsyncClient) -> None:
    """Swapping a block's type at the same id surfaces as both fields and type."""
    page_id = await _create(
        authed_client, slug="diff-type", blocks=[_block("a", "Heading", text="Hi")]
    )
    await _publish(authed_client, page_id)
    await authed_client.put(
        f"/api/pagebuilder/pages/{page_id}",
        json={"draft_data": {"content": [_block("a", "Text", body="Hi")]}},
    )
    await _publish(authed_client, page_id)

    revisions = (
        await authed_client.get(f"/api/pagebuilder/pages/{page_id}/revisions")
    ).json()["items"]
    diff = (
        await authed_client.get(
            f"/api/pagebuilder/pages/{page_id}"
            f"/revisions/{revisions[1]['id']}/diff/{revisions[0]['id']}"
        )
    ).json()
    changed = diff["blocks"]["changed"]
    assert len(changed) == 1
    assert changed[0]["type"] == "Text"
    assert changed[0]["type_before"] == "Heading"
