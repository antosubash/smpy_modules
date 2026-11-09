"""Searching the public archive.

``/api/news/articles?q=`` was anonymous and the admin had a whole search screen,
but a reader browsing ``/news/`` could only page or narrow by category or tag:
the capability was built and simply not offered to the people most likely to
want it.

What these tests pin is the *shape* of the answer rather than the fact of it.
A search is an address (``/news/?q=…``), so it can be linked and paged. It
composes with everything else that narrows the archive rather than replacing
it. It obeys the archive's visibility rule, so no search reaches a draft. And
it is not indexable, because the input space is unbounded.
"""

from __future__ import annotations

import pytest
from news.models import NewsArticleTag, NewsCategory, NewsTag
from news.web.endpoints.public._archive import archive_url

from tests.support.public_search import _props, _seed

pytestmark = pytest.mark.asyncio

NEWS = "/news"
INERTIA = {"X-Inertia": "true", "X-Inertia-Version": "1.0"}



class TestTheEncoding:
    """No route involved, just ``archive_url`` itself — ``async`` only because
    the module's ``pytestmark`` expects it of every test here."""

    async def test_matches_urlsearchparams_on_the_two_characters_that_differ(
        self,
    ) -> None:
        """`*` and `~` are the one pair Python's default ``urlencode`` and the
        browser's own ``URLSearchParams`` read oppositely — see
        ``archive_url``'s ``_form_urlencode``. Pinned as a literal string
        against ``archiveUrl.test.ts``'s matching case, the same way
        ``test_the_canonical_names_the_search`` below is."""
        assert archive_url("/news/", q="a*b~c d!") == "/news/?q=a*b%7Ec+d%21"


class TestItNarrows:
    async def test_a_search_filters_the_archive(self, anon_client) -> None:
        await _seed(anon_client, "canopy-cover", title="Canopy cover in 2026")
        await _seed(anon_client, "budget", title="The budget, line by line")

        props = await _props(anon_client, f"{NEWS}/?q=canopy")

        assert [item["slug"] for item in props["items"]] == ["canopy-cover"]
        # The count is the search's, not the archive's — the pager reads it.
        assert props["total"] == 1
        assert props["query"] == "canopy"

    async def test_it_matches_the_excerpt(self, anon_client) -> None:
        """The standfirst is where a half-remembered phrase usually is.

        Headline-only search was the old behaviour and is why the excerpt was
        added to the filter: a reader searching an archive is matching words
        they read, and most of the words on a card are not in the headline.
        """
        await _seed(
            anon_client, "quiet-title", meta_description="A study of canopy loss."
        )

        props = await _props(anon_client, f"{NEWS}/?q=canopy loss")

        assert [i["slug"] for i in props["items"]] == ["quiet-title"]

    async def test_it_matches_a_tag(self, anon_client) -> None:
        article = await _seed(anon_client, "tagged")
        async with anon_client.db_state.session_factory() as db:
            tag = NewsTag(name="Canopy", slug="canopy")
            db.add(tag)
            await db.flush()
            db.add(NewsArticleTag(article_id=article.id, tag_id=tag.id))
            await db.commit()

        props = await _props(anon_client, f"{NEWS}/?q=canopy")

        assert [i["slug"] for i in props["items"]] == ["tagged"]

    async def test_it_does_not_match_the_body(self, anon_client) -> None:
        """The public search stops at what a card shows.

        The admin screen searches ``draft_data`` — text that may never have been
        published. A public route answering for it would tell an outsider that
        an unpublished edit exists.
        """
        await _seed(
            anon_client,
            "prose",
            draft_data={"root": {"props": {"title": "prose"}}, "content": ["embargo"]},
        )

        props = await _props(anon_client, f"{NEWS}/?q=embargo")

        assert props["items"] == []

    async def test_a_wildcard_is_matched_literally(self, anon_client) -> None:
        # `%` and `_` are LIKE wildcards; an unescaped search for them would
        # return the whole archive from a public route.
        await _seed(anon_client, "plain", title="Plain")

        props = await _props(anon_client, f"{NEWS}/?q=%25")

        assert props["items"] == []


class TestItComposes:
    async def test_a_search_narrows_within_a_category(self, anon_client) -> None:
        """Narrowing, not replacing — the reader is standing on the category."""
        await _seed(anon_client, "in-scope", title="Canopy in the field", category="Field notes")
        await _seed(anon_client, "out-of-scope", title="Canopy releases", category="Releases")
        async with anon_client.db_state.session_factory() as db:
            db.add(NewsCategory(name="Field notes", slug="field-notes"))
            await db.commit()

        props = await _props(anon_client, f"{NEWS}/category/field-notes?q=canopy")

        assert [i["slug"] for i in props["items"]] == ["in-scope"]
        assert props["narrowed"] is True
        # The form posts back to the category, so the next search stays in it.
        assert props["base_path"] == f"{NEWS}/category/field-notes"

    async def test_a_search_narrows_within_a_tag(self, anon_client) -> None:
        tagged = await _seed(anon_client, "tagged", title="Canopy piece")
        await _seed(anon_client, "loose", title="Canopy loose")
        async with anon_client.db_state.session_factory() as db:
            tag = NewsTag(name="Field", slug="field")
            db.add(tag)
            await db.flush()
            db.add(NewsArticleTag(article_id=tagged.id, tag_id=tag.id))
            await db.commit()

        props = await _props(anon_client, f"{NEWS}/tag/field?q=canopy")

        assert [i["slug"] for i in props["items"]] == ["tagged"]

    async def test_it_pages_and_keeps_the_term(self, anon_client) -> None:
        for index in range(14):
            await _seed(anon_client, f"canopy-{index:02d}", title=f"Canopy {index:02d}")
        await _seed(anon_client, "unrelated", title="Budget")

        first = await _props(anon_client, f"{NEWS}/?q=canopy")
        second = await _props(anon_client, f"{NEWS}/?q=canopy&page=2")

        assert len(first["items"]) == 12
        assert first["pages"] == 2
        assert first["total"] == 14
        assert len(second["items"]) == 2
        assert second["query"] == "canopy"

    async def test_it_stays_in_one_language(self, bilingual_public_client) -> None:
        client = bilingual_public_client
        await _seed(client, "canopy-en", title="Canopy", locale="en")
        await _seed(client, "canopy-de", title="Canopy", locale="de")

        english = await _props(client, f"{NEWS}/?q=canopy")
        german = await _props(client, f"/de{NEWS}/?q=canopy")

        assert [i["slug"] for i in english["items"]] == ["canopy-en"]
        assert [i["slug"] for i in german["items"]] == ["canopy-de"]
