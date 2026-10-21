"""Inputs the admin UI never sends, which the API must still refuse (#158).

A bare number is coerced by pydantic as Unix seconds, so ``{"publish_at": 1}``
scheduled a page for 1970 — live on the next scheduler tick — and a client that
sent milliseconds got a date tens of millennia out. A naive time is ambiguous
about its zone. A rejection note of spaces passed ``min_length=1`` and left the
history panel an empty reason.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from pagebuilder.contracts.schemas import (
    ImportDecisionRequest,
    LayoutUpdate,
    PageNoteRequest,
    PageRejectRequest,
    SnapshotCreateRequest,
)
from pagebuilder.contracts.schemas._fields import NOTE_MAX
from pydantic import ValidationError

PAGES = "/api/pagebuilder/pages"
LATER = (datetime.now(UTC) + timedelta(days=3)).replace(microsecond=0)


async def _draft(client: AsyncClient, slug: str = "strict") -> int:
    response = await client.post(
        PAGES, json={"title": "Draft", "slug": slug, "draft_data": {"content": []}}
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


@pytest.mark.parametrize(
    "value",
    [
        1,
        1_700_000_000_000,
        1.5,
        True,
        "1700000000",
        LATER.replace(tzinfo=None).isoformat(),
        LATER.date().isoformat(),
        "next tuesday",
    ],
)
@pytest.mark.parametrize("field", ["publish_at", "unpublish_at"])
async def test_schedule_refuses_anything_but_an_offset_aware_iso_string(
    authed_client: AsyncClient, field: str, value: object
) -> None:
    page_id = await _draft(authed_client)

    response = await authed_client.post(f"{PAGES}/{page_id}/schedule", json={field: value})

    assert response.status_code == 422, response.text
    assert response.json()["detail"][0]["loc"] == ["body", field]
    detail = (await authed_client.get(f"{PAGES}/{page_id}")).json()
    assert detail[field] is None


@pytest.mark.parametrize(
    "sent",
    [
        LATER.isoformat(),
        LATER.isoformat().replace("+00:00", "Z"),
        LATER.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        (LATER + timedelta(hours=2)).isoformat().replace("+00:00", "+02:00"),
    ],
)
async def test_schedule_accepts_an_offset_aware_iso_string(
    authed_client: AsyncClient, sent: str
) -> None:
    """``Z`` is what the editor's ``toISOString()`` sends; any offset is the
    same instant once normalised to UTC."""
    page_id = await _draft(authed_client)

    response = await authed_client.post(f"{PAGES}/{page_id}/schedule", json={"publish_at": sent})

    assert response.status_code == 200, response.text
    assert datetime.fromisoformat(response.json()["publish_at"]) == LATER


async def test_create_refuses_a_numeric_schedule(authed_client: AsyncClient) -> None:
    """Create takes the same two fields, so it takes the same type."""
    response = await authed_client.post(
        PAGES, json={"title": "Draft", "slug": "numeric", "publish_at": 1}
    )

    assert response.status_code == 422, response.text


@pytest.mark.parametrize("note", ["", "   ", "\n\t "])
async def test_reject_refuses_a_blank_note(authed_client: AsyncClient, note: str) -> None:
    page_id = await _draft(authed_client)
    await authed_client.post(f"{PAGES}/{page_id}/submit")

    response = await authed_client.post(f"{PAGES}/{page_id}/reject", json={"note": note})

    assert response.status_code == 422, response.text
    detail = (await authed_client.get(f"{PAGES}/{page_id}")).json()
    assert detail["status"] == "submitted_for_review"


async def test_reject_stores_the_note_trimmed(authed_client: AsyncClient) -> None:
    page_id = await _draft(authed_client)
    await authed_client.post(f"{PAGES}/{page_id}/submit")

    response = await authed_client.post(
        f"{PAGES}/{page_id}/reject", json={"note": "  Needs a source.\n"}
    )

    assert response.status_code == 200, response.text
    assert response.json()["rejection_note"] == "Needs a source."


async def test_a_blank_optional_note_is_recorded_as_no_note(authed_client: AsyncClient) -> None:
    """Publish's note is optional: spaces mean "no note", not an empty one."""
    page_id = await _draft(authed_client)

    response = await authed_client.post(f"{PAGES}/{page_id}/publish", json={"note": "   "})

    assert response.status_code == 200, response.text
    revisions = (await authed_client.get(f"{PAGES}/{page_id}/revisions")).json()["items"]
    assert [r["note"] for r in revisions if r["event"] == "publish"] == [None]


# Every note a write takes: the bound is on the stripped note, so padding never
# pushes a valid note over it and a long run of spaces is blank, not too long.
OPTIONAL_NOTES = [PageNoteRequest, LayoutUpdate, SnapshotCreateRequest, ImportDecisionRequest]


@pytest.mark.parametrize("model", [*OPTIONAL_NOTES, PageRejectRequest])
def test_a_padded_note_at_the_limit_is_kept(model) -> None:
    note = "a" * NOTE_MAX
    assert model(note=f" {note} ").note == note


@pytest.mark.parametrize("model", [*OPTIONAL_NOTES, PageRejectRequest])
def test_a_trimmed_note_over_the_limit_is_refused(model) -> None:
    with pytest.raises(ValidationError):
        model(note="a" * (NOTE_MAX + 1))


@pytest.mark.parametrize("model", OPTIONAL_NOTES)
def test_a_long_run_of_spaces_is_no_optional_note(model) -> None:
    assert model(note=" " * (NOTE_MAX + 1)).note is None


def test_a_long_run_of_spaces_is_a_blank_rejection() -> None:
    with pytest.raises(ValidationError) as caught:
        PageRejectRequest(note=" " * (NOTE_MAX + 1))
    assert caught.value.errors()[0]["type"] == "string_too_short"


async def test_reject_keeps_a_padded_note_at_the_limit(authed_client: AsyncClient) -> None:
    page_id = await _draft(authed_client)
    await authed_client.post(f"{PAGES}/{page_id}/submit")
    note = "a" * NOTE_MAX

    response = await authed_client.post(f"{PAGES}/{page_id}/reject", json={"note": f" {note} "})

    assert response.status_code == 200, response.text
    assert response.json()["rejection_note"] == note


def test_an_offset_that_overflows_utc_is_refused_not_a_500() -> None:
    from pagebuilder.contracts.schemas import PageScheduleRequest

    with pytest.raises(ValidationError):
        PageScheduleRequest(publish_at="9999-12-31T23:59:59-05:00")
