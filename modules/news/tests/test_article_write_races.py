"""QA regressions on the article write path: validation, no-op publish,
atomic transitions and optimistic concurrency."""

from __future__ import annotations

import asyncio

import pytest
from factories import make_article
from fastapi import HTTPException
from news.constants import ROUTE_PREFIX_API
from news.content import ArticlesService
from news.content._fresh import STALE_DETAIL, claim_status
from news.models import ArticleStatus

pytestmark = pytest.mark.asyncio

ARTICLES = f"{ROUTE_PREFIX_API}/articles"


async def _article(client, slug: str, status: ArticleStatus = ArticleStatus.DRAFT) -> int:
    async with client.db_state.session_factory() as db:
        return (await make_article(db, slug=slug, title="Subject", status=status)).id or 0


async def _revisions(client, article_id: int) -> list[str]:
    response = await client.get(f"{ARTICLES}/{article_id}/revisions")
    return [row["event"] for row in response.json()]


# ── BUG-001 ──────────────────────────────────────────────────────────
async def test_a_blank_title_on_update_is_a_422(editor_client) -> None:
    article_id = await _article(editor_client, "blank-update")
    response = await editor_client.put(f"{ARTICLES}/{article_id}", json={"title": "   "})
    assert response.status_code == 422
    assert "An article needs a headline." in response.text


async def test_update_trims_the_title(editor_client) -> None:
    article_id = await _article(editor_client, "trim-update")
    response = await editor_client.put(
        f"{ARTICLES}/{article_id}", json={"title": "  padded  "}
    )
    assert response.status_code == 200, response.text
    assert response.json()["title"] == "padded"


async def test_a_blank_translation_title_is_a_422(editor_client, bilingual) -> None:
    article_id = await _article(editor_client, "blank-translation")
    response = await editor_client.post(
        f"{ARTICLES}/{article_id}/translations", json={"locale": "de", "title": "   "}
    )
    assert response.status_code == 422


# ── BUG-011 ──────────────────────────────────────────────────────────
@pytest.mark.parametrize("field", ["canonical_url", "og_image"])
@pytest.mark.parametrize(
    "bad",
    [
        "not a url",
        "javascript:alert(1)",
        "data:text/html,x",
        "http://:80",
        "https://@",
        "https://user:pw@/x",
        "http://:8080/path",
    ],
)
async def test_unsafe_urls_are_refused(editor_client, field: str, bad: str) -> None:
    article_id = await _article(editor_client, f"url-{field}".replace("_", "-"))
    response = await editor_client.put(f"{ARTICLES}/{article_id}", json={field: bad})
    assert response.status_code == 422, response.text


async def test_good_urls_are_accepted_and_empty_clears(editor_client) -> None:
    article_id = await _article(editor_client, "good-urls")
    ok = await editor_client.put(
        f"{ARTICLES}/{article_id}",
        json={"canonical_url": "https://example.com/a", "og_image": "/media/x.png"},
    )
    assert ok.status_code == 200, ok.text
    cleared = await editor_client.put(
        f"{ARTICLES}/{article_id}", json={"canonical_url": "", "og_image": ""}
    )
    assert cleared.status_code == 200, cleared.text
    detail = (await editor_client.get(f"{ARTICLES}/{article_id}/detail")).json()
    assert detail["canonical_url"] == "" and detail["og_image"] == ""


async def test_a_stored_javascript_url_is_not_rendered(editor_public_client) -> None:
    async with editor_public_client.db_state.session_factory() as db:
        article = await make_article(db, slug="legacy", og_image="javascript:alert(1)")
        article.canonical_url = "javascript:alert(2)"
        db.add(article)
        await db.commit()
    page = await editor_public_client.get("/news/legacy")
    assert page.status_code == 200
    assert "javascript:" not in page.text


@pytest.mark.parametrize(
    "bad", ["http://:80", "https://@", "https://user:pw@/x", "http://:8080/path"]
)
async def test_a_stored_hostless_url_is_not_rendered(editor_public_client, bad: str) -> None:
    async with editor_public_client.db_state.session_factory() as db:
        article = await make_article(db, slug="legacy-hostless", og_image=bad)
        article.canonical_url = bad
        db.add(article)
        await db.commit()
    page = await editor_public_client.get("/news/legacy-hostless")
    assert page.status_code == 200
    assert bad not in page.text
    assert 'rel="canonical" href="http://test/news/legacy-hostless"' in page.text
    assert 'property="og:image"' not in page.text


# ── BUG-016 ──────────────────────────────────────────────────────────
async def test_a_nul_byte_is_a_422(editor_client) -> None:
    created = await editor_client.post(ARTICLES, json={"title": "bad\x00title"})
    assert created.status_code == 422
    article_id = await _article(editor_client, "nul")
    updated = await editor_client.put(
        f"{ARTICLES}/{article_id}", json={"meta_description": "a\x00b"}
    )
    assert updated.status_code == 422
    body = await editor_client.put(
        f"{ARTICLES}/{article_id}/body", json={"draft_data": {"content": ["x\x00"]}}
    )
    assert body.status_code == 422


# ── BUG-018 ──────────────────────────────────────────────────────────
async def test_republishing_an_unchanged_article_is_a_no_op(editor_client) -> None:
    article_id = await _article(editor_client, "noop")
    first = await editor_client.post(f"{ARTICLES}/{article_id}/publish")
    assert first.status_code == 200, first.text
    before = await _revisions(editor_client, article_id)
    again = await editor_client.post(f"{ARTICLES}/{article_id}/publish")
    assert again.status_code == 200
    assert await _revisions(editor_client, article_id) == before


async def test_republishing_a_changed_draft_is_recorded(editor_client) -> None:
    article_id = await _article(editor_client, "changed")
    await editor_client.post(f"{ARTICLES}/{article_id}/publish")
    await editor_client.put(
        f"{ARTICLES}/{article_id}/body", json={"draft_data": {"content": [1]}}
    )
    before = await _revisions(editor_client, article_id)
    await editor_client.post(f"{ARTICLES}/{article_id}/publish")
    assert len(await _revisions(editor_client, article_id)) == len(before) + 1


# ── BUG-019 ──────────────────────────────────────────────────────────
async def test_unpublishing_a_draft_is_a_409(editor_client) -> None:
    article_id = await _article(editor_client, "undraft")
    response = await editor_client.post(f"{ARTICLES}/{article_id}/unpublish")
    assert response.status_code == 409


async def test_a_transition_claim_loses_to_an_earlier_one(editor_client) -> None:
    """Two requests that both read the article as SUBMITTED: only the first
    claim matches a row, so the second gets a 409 and records nothing."""
    article_id = await _article(editor_client, "claims", ArticleStatus.SUBMITTED_FOR_REVIEW)
    factory = editor_client.db_state.session_factory
    async with factory() as one, factory() as two:
        a = await ArticlesService(one).get_article(article_id)
        b = await ArticlesService(two).get_article(article_id)
        await claim_status(
            one, a, expected=(ArticleStatus.SUBMITTED_FOR_REVIEW,),
            to=ArticleStatus.PUBLISHED, conflict="lost",
        )
        await one.commit()
        with pytest.raises(HTTPException) as lost:
            await claim_status(
                two, b, expected=(ArticleStatus.SUBMITTED_FOR_REVIEW,),
                to=ArticleStatus.PUBLISHED, conflict="lost",
            )
        assert lost.value.status_code == 409


async def test_parallel_approves_record_one_revision(editor_client) -> None:
    article_id = await _article(editor_client, "parallel", ArticleStatus.SUBMITTED_FOR_REVIEW)
    results = await asyncio.gather(
        *(editor_client.post(f"{ARTICLES}/{article_id}/approve") for _ in range(5)),
        return_exceptions=True,
    )
    codes = [getattr(r, "status_code", None) for r in results]
    assert codes.count(200) == 1, codes
    assert (await _revisions(editor_client, article_id)).count("approve") == 1


# ── BUG-020 ──────────────────────────────────────────────────────────
async def test_a_stale_expected_updated_at_is_a_409(editor_client) -> None:
    created = await editor_client.post(ARTICLES, json={"title": "Stale"})
    article_id = created.json()["id"]
    first = (await editor_client.get(f"{ARTICLES}/{article_id}/detail")).json()
    stamp = first["updated_at"]
    assert stamp is not None and (stamp.endswith("Z") or "+" in stamp)

    saved = await editor_client.put(
        f"{ARTICLES}/{article_id}", json={"author": "A", "expected_updated_at": stamp}
    )
    assert saved.status_code == 200, saved.text
    fresh = saved.json()["updated_at"]
    assert fresh != stamp

    stale = await editor_client.put(
        f"{ARTICLES}/{article_id}", json={"author": "B", "expected_updated_at": stamp}
    )
    assert stale.status_code == 409
    assert stale.json()["detail"] == STALE_DETAIL

    stale_body = await editor_client.put(
        f"{ARTICLES}/{article_id}/body",
        json={"draft_data": {"content": []}, "expected_updated_at": stamp},
    )
    assert stale_body.status_code == 409

    ok_body = await editor_client.put(
        f"{ARTICLES}/{article_id}/body",
        json={"draft_data": {"content": []}, "expected_updated_at": fresh},
    )
    assert ok_body.status_code == 200, ok_body.text
    assert ok_body.json()["updated_at"] != fresh


async def test_omitting_expected_updated_at_still_writes(editor_client) -> None:
    article_id = await _article(editor_client, "unchecked")
    response = await editor_client.put(f"{ARTICLES}/{article_id}", json={"author": "Z"})
    assert response.status_code == 200
