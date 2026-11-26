"""Layout saves and restores guard the editor's loaded version (#466)."""

from datetime import UTC, datetime, timedelta, timezone

import pytest

pytestmark = pytest.mark.asyncio
PATH = "/api/pagebuilder/layout"


def document(text):
    return {"content": [{"type": "Text", "props": {"id": "text", "text": text}}]}


@pytest.mark.parametrize("slot", ["header_data", "footer_data"])
async def test_stale_save_preserves_both_slots_and_history(authed_client, slot):
    client = authed_client
    loaded = (await client.get(PATH)).json()
    current = await client.put(PATH, json={
        "header_data": document("Other header"), "footer_data": document("Other footer"),
    })
    revisions = (await client.get(f"{PATH}/revisions")).json()
    refused = await client.put(PATH, json={
        slot: document("Stale"), "expected_updated_at": loaded["updated_at"],
    })
    assert refused.status_code == 409, refused.text
    assert refused.json() == {
        "detail": "This layout was changed elsewhere", "code": "layout_conflict",
    }
    assert (await client.get(PATH)).json() == current.json()
    assert (await client.get(f"{PATH}/revisions")).json() == revisions


async def test_fresh_and_returned_tokens_allow_successive_saves(authed_client):
    loaded = (await authed_client.get(PATH)).json()
    assert loaded["updated_at"] is None
    for slot in ("header_data", "footer_data"):
        response = await authed_client.put(PATH, json={
            slot: document(slot), "expected_updated_at": loaded["updated_at"],
        })
        assert response.status_code == 200, response.text
        saved = response.json()
        assert saved[slot] == document(slot)
        assert saved["updated_at"] != loaded["updated_at"]
        loaded = saved
    # An unchanged guarded save neither advances the token nor adds history.
    before = (await authed_client.get(f"{PATH}/revisions")).json()
    noop = await authed_client.put(PATH, json={
        "footer_data": loaded["footer_data"], "expected_updated_at": loaded["updated_at"],
    })
    assert noop.status_code == 200, noop.text
    assert noop.json() == loaded
    assert (await authed_client.get(f"{PATH}/revisions")).json() == before


async def test_no_token_preserves_older_clients_and_explicit_overwrite(authed_client):
    client = authed_client
    await client.put(PATH, json={"header_data": document("First")})
    loaded = (await client.get(PATH)).json()
    await client.put(PATH, json={"header_data": document("Other editor")})
    patch = {"header_data": document("Mine")}
    refused = await client.put(PATH, json={**patch, "expected_updated_at": loaded["updated_at"]})
    assert refused.status_code == 409
    overwritten = await client.put(PATH, json=patch)
    assert overwritten.status_code == 200, overwritten.text
    assert overwritten.json()["header_data"] == document("Mine")
    next_save = await client.put(PATH, json={
        "footer_data": document("Next"),
        "expected_updated_at": overwritten.json()["updated_at"],
    })
    assert next_save.status_code == 200, next_save.text


async def test_equivalent_utc_offset_is_fresh(authed_client):
    loaded = (await authed_client.put(PATH, json={"header_data": document("First")})).json()
    instant = datetime.fromisoformat(loaded["updated_at"])
    offset = instant.astimezone(timezone(timedelta(hours=2))).isoformat()
    saved = await authed_client.put(PATH, json={
        "header_data": document("Second"), "expected_updated_at": offset,
    })
    assert saved.status_code == 200, saved.text


async def test_restore_checks_version_and_supplies_next_save_token(authed_client):
    client = authed_client
    loaded = (await client.put(PATH, json={"header_data": document("Original")})).json()
    revision = (await client.get(f"{PATH}/revisions")).json()["items"][0]["id"]
    path = f"{PATH}/revisions/{revision}/restore"
    current = (await client.put(PATH, json={"header_data": document("Other")})).json()
    history = (await client.get(f"{PATH}/revisions")).json()
    refused = await client.post(path, json={"expected_updated_at": loaded["updated_at"]})
    assert refused.status_code == 409, refused.text
    assert refused.json()["code"] == "layout_conflict"
    assert (await client.get(PATH)).json() == current
    assert (await client.get(f"{PATH}/revisions")).json() == history
    restored = await client.post(path, json={"expected_updated_at": current["updated_at"]})
    assert restored.status_code == 200, restored.text
    assert restored.json()["header_data"] == document("Original")
    saved = await client.put(PATH, json={
        "footer_data": document("After restore"),
        "expected_updated_at": restored.json()["updated_at"],
    })
    assert saved.status_code == 200, saved.text
    # Older restore clients may still omit the entire body.
    assert (await client.post(path)).status_code == 200


async def test_schema_serializes_sqlite_version_as_an_accepted_utc_token():
    from pagebuilder.contracts.schemas import LayoutDetail, LayoutUpdate

    loaded = LayoutDetail.model_validate({
        "id": 1, "created_at": datetime(2026, 1, 1),
        "updated_at": datetime(2026, 1, 2, 3, 4, 5),
        "header_data": {}, "footer_data": {},
    }).model_dump(mode="json")
    assert loaded["updated_at"] == "2026-01-02T03:04:05Z"
    request = LayoutUpdate(expected_updated_at=loaded["updated_at"])
    assert request.expected_updated_at == datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)


async def test_schema_distinguishes_an_untouched_version_from_omission():
    from pagebuilder.contracts.schemas import LayoutUpdate

    assert "expected_updated_at" not in LayoutUpdate().model_fields_set
    explicit = LayoutUpdate(expected_updated_at=None)
    assert "expected_updated_at" in explicit.model_fields_set
    assert explicit.expected_updated_at is None
