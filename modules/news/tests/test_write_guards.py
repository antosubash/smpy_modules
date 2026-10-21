"""Guards on the write API that each closed a specific hole.

Each was found by review rather than by a failing screen, which is why they are
pinned here: none of them is visible in the normal flow, and each fails in a way
that names the wrong problem or quietly widens what a role can do.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest
from factories import make_article
from news.constants import MAX_NOTE_LEN, ROUTE_PREFIX_API
from news.models import ArticleStatus

pytestmark = pytest.mark.asyncio

ARTICLES = f"{ROUTE_PREFIX_API}/articles"


async def _article(client, slug: str, status: ArticleStatus) -> int:
    async with client.db_state.session_factory() as db:
        article = await make_article(db, slug=slug, title="Subject", status=status)
        return article.id or 0


async def test_an_author_cannot_unpublish_by_submitting(author_client) -> None:
    """Submit needs only news.edit and moves the article to review. From PUBLISHED
    that would take it off the site — which is news.publish's to do."""
    article_id = await _article(author_client, "live", ArticleStatus.PUBLISHED)

    response = await author_client.post(f"{ARTICLES}/{article_id}/submit")

    assert response.status_code == 409, response.text
    listed = (await author_client.get(f"{ARTICLES}?status=published")).json()
    assert [item["id"] for item in listed["items"]] == [article_id]


@pytest.mark.parametrize("field", ["title", "slug", "index_in_search"])
async def test_null_for_a_required_field_is_a_422(editor_client, field: str) -> None:
    """Otherwise the NOT NULL failure surfaces as "Slug already in use"."""
    slug = f"null-{field}".replace("_", "-")
    article_id = await _article(editor_client, slug, ArticleStatus.DRAFT)

    response = await editor_client.put(f"{ARTICLES}/{article_id}", json={field: None})

    assert response.status_code == 422, response.text


async def test_a_schedule_is_stored_in_utc(editor_client) -> None:
    """Sent with an offset, read back as the same instant in UTC. SQLite drops
    the offset without converting, so an unconverted +02:00 time would fire two
    hours late."""
    article_id = await _article(editor_client, "zoned", ArticleStatus.DRAFT)
    instant = datetime.now(UTC).replace(microsecond=0) + timedelta(days=1)
    sent = instant.astimezone(timezone(timedelta(hours=2)))

    response = await editor_client.post(
        f"{ARTICLES}/{article_id}/schedule", json={"publish_at": sent.isoformat()}
    )
    assert response.status_code == 200, response.text

    detail = (await editor_client.get(f"{ARTICLES}/{article_id}/detail")).json()
    assert datetime.fromisoformat(detail["publish_at"]) == instant


@pytest.mark.parametrize(
    "value",
    [1, 1_700_000_000_000, True, "1700000000", "2026-12-01T09:00:00", "2026-12-01", "soon"],
)
@pytest.mark.parametrize("field", ["publish_at", "unpublish_at"])
async def test_a_schedule_must_be_an_offset_aware_iso_string(
    editor_client, field: str, value: object
) -> None:
    """A number is Unix seconds to pydantic — ``1`` went live on the next tick —
    and a naive time is a guess about the zone (#158)."""
    article_id = await _article(editor_client, "numeric", ArticleStatus.DRAFT)

    response = await editor_client.post(f"{ARTICLES}/{article_id}/schedule", json={field: value})

    assert response.status_code == 422, response.text
    assert response.json()["detail"][0]["loc"] == ["body", field]


@pytest.mark.parametrize("note", ["   ", "\n\t"])
async def test_a_blank_rejection_note_is_no_note(editor_client, note: str) -> None:
    """The note is optional here, so spaces mean "no reason given" — not an
    empty reason in the author's banner."""
    article_id = await _article(editor_client, "blank-note", ArticleStatus.SUBMITTED_FOR_REVIEW)

    response = await editor_client.post(f"{ARTICLES}/{article_id}/reject", json={"note": note})

    assert response.status_code == 200, response.text
    detail = (await editor_client.get(f"{ARTICLES}/{article_id}/detail")).json()
    assert detail["rejection_note"] is None


async def test_a_rejection_note_is_stored_trimmed(editor_client) -> None:
    article_id = await _article(editor_client, "trim-note", ArticleStatus.SUBMITTED_FOR_REVIEW)

    await editor_client.post(f"{ARTICLES}/{article_id}/reject", json={"note": " Cite it. \n"})

    detail = (await editor_client.get(f"{ARTICLES}/{article_id}/detail")).json()
    assert detail["rejection_note"] == "Cite it."


async def test_the_note_bound_applies_after_trimming(editor_client) -> None:
    """Padding round a note of exactly the limit does not push it over."""
    article_id = await _article(editor_client, "padded-note", ArticleStatus.SUBMITTED_FOR_REVIEW)
    note = "a" * MAX_NOTE_LEN

    response = await editor_client.post(
        f"{ARTICLES}/{article_id}/reject", json={"note": f" {note} "}
    )

    assert response.status_code == 200, response.text
    detail = (await editor_client.get(f"{ARTICLES}/{article_id}/detail")).json()
    assert detail["rejection_note"] == note


async def test_a_long_run_of_spaces_is_no_note(editor_client) -> None:
    article_id = await _article(editor_client, "space-note", ArticleStatus.SUBMITTED_FOR_REVIEW)

    response = await editor_client.post(
        f"{ARTICLES}/{article_id}/reject", json={"note": " " * (MAX_NOTE_LEN + 1)}
    )

    assert response.status_code == 200, response.text
    detail = (await editor_client.get(f"{ARTICLES}/{article_id}/detail")).json()
    assert detail["rejection_note"] is None


async def test_a_trimmed_note_over_the_limit_is_refused(editor_client) -> None:
    article_id = await _article(editor_client, "long-note", ArticleStatus.SUBMITTED_FOR_REVIEW)

    response = await editor_client.post(
        f"{ARTICLES}/{article_id}/reject", json={"note": "a" * (MAX_NOTE_LEN + 1)}
    )

    assert response.status_code == 422, response.text
