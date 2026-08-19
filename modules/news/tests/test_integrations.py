"""Unit tests for the seam news borrows pagebuilder through.

``news.integrations.pagebuilder`` is the only module here that imports that
package, so it is also the only place where a change on pagebuilder's side can
break news silently. Everything it reimplements rather than imports — the slug
rules, the status vocabulary — is pinned here against pagebuilder's own
declarations rather than against a copy of them.

Synchronous, and therefore in its own file: the endpoint tests carry a
module-level ``asyncio`` mark that a plain function must not inherit.
"""

from __future__ import annotations

import re
from datetime import datetime

import pytest
from news import service
from news.constants import MAX_SLUG_LEN
from news.contracts.schemas import ArticleStatus
from news.integrations import pagebuilder as pb
from pagebuilder.contracts.schemas import PageCreate

# Pagebuilder's own constraint on the field, read off the schema rather than
# copied, so tightening it there fails here instead of in production.
PAGE_SLUG_PATTERN = re.compile(PageCreate.model_fields["slug"].metadata[-1].pattern)


class TestSlugify:
    @pytest.mark.parametrize(
        ("title", "expected"),
        [
            ("Field Campaign in Estonia", "field-campaign-in-estonia"),
            ("  leading and trailing  ", "leading-and-trailing"),
            ("Ünïcodé folds", "unicode-folds"),
            ("punctuation!!! -- everywhere", "punctuation-everywhere"),
            ("--leading hyphens--", "leading-hyphens"),
            # Nothing survives the fold. Returning "" rather than something
            # invalid is what lets the caller substitute a usable slug.
            ("???", ""),
            ("日本語", ""),
        ],
    )
    def test_folds_a_title_to_a_slug(self, title: str, expected: str) -> None:
        assert pb.slugify(title) == expected

    @pytest.mark.parametrize(
        "title",
        [
            "Field Campaign in Estonia",
            "--leading hyphens--",
            "Ünïcodé folds",
            "a " * 300,
            "x" * 500,
        ],
    )
    def test_anything_non_empty_satisfies_pagebuilders_pattern(self, title: str) -> None:
        """A slug that fails the pattern is a 422 the author cannot act on.

        Truncating to the column bound is where this nearly went wrong: the cut
        can land mid-separator, and a trailing hyphen fails the pattern.
        """
        slug = pb.slugify(title)

        assert slug, "these titles all have slug characters in them"
        assert len(slug) <= MAX_SLUG_LEN
        assert PAGE_SLUG_PATTERN.match(slug)


class TestArticleStatus:
    def test_every_page_status_has_a_news_name(self) -> None:
        """News' enum is its own, so only a test keeps the two total.

        A status added to pagebuilder that news cannot name would otherwise
        surface as a ValueError raised from inside a listing.
        """
        for status in pb.PageStatus:
            assert pb.article_status(status) == ArticleStatus(status.value)

    def test_the_two_vocabularies_have_not_drifted(self) -> None:
        assert {s.value for s in ArticleStatus} == {s.value for s in pb.PageStatus}


class TestDisplayDate:
    """``published_at`` is a date; the API accepts an instant."""

    def test_a_naive_datetime_is_taken_at_face_value(self) -> None:
        normalised = service.as_display_date(datetime(2026, 2, 1, 22, 30))

        assert normalised is not None
        assert normalised.timetuple()[:6] == (2026, 2, 1, 0, 0, 0)
        assert normalised.tzinfo is not None

    def test_undated_stays_undated(self) -> None:
        assert service.as_display_date(None) is None
