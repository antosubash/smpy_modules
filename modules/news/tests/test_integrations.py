"""Unit tests for the seam news borrows pagebuilder through.

``news.integrations.pagebuilder`` is the only module here that imports that
package, so it is also the only place where a change on pagebuilder's side can
break news silently. Everything the seam restates rather than imports — the
status vocabulary, the slug rules, the admin routes — is pinned here against
pagebuilder's own declarations rather than against a copy of them.

Synchronous, and therefore in its own file: the endpoint tests carry a
module-level ``asyncio`` mark that a plain function must not inherit.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta, timezone

import pytest
from news import settings as news_settings
from news.constants import MAX_SLUG_LEN
from news.contracts.schemas import ArticleStatus
from news.display_date import as_display_date
from news.integrations import pagebuilder as pb
from news.integrations import pages as pb_pages
from news.settings import NewsSettings, public_article_path
from pagebuilder.contracts.schemas import PageCreate

# Pagebuilder's own constraint on the field, read off the schema rather than
# copied, so tightening it there fails here instead of in production.
PAGE_SLUG_PATTERN = re.compile(PageCreate.model_fields["slug"].metadata[-1].pattern)


class TestNoOtherModuleImportsPagebuilder:
    def test_the_seam_is_the_only_importer(self) -> None:
        """The rule the whole package exists to state.

        Asserted rather than left to review because it is the kind of thing a
        single convenient import quietly undoes, and nothing else would fail.

        The unit is ``news/integrations/`` rather than one file in it — which
        is what the package docstring has always said. It outgrew a single
        module when the 300-line cap split the page *writes* and the content
        locales into siblings; both still sit behind the same boundary, and
        widening the check to the directory is what keeps it checkable by
        reading one directory listing.
        """
        import pathlib

        import news

        root = pathlib.Path(news.__file__).parent
        seam = root / "integrations"
        offenders = sorted(
            path.relative_to(root).as_posix()
            for path in root.rglob("*.py")
            if seam not in path.parents
            and re.search(r"^\s*(from|import) pagebuilder", path.read_text(), re.M)
        )

        assert offenders == []


class TestSlugForTitle:
    @pytest.mark.parametrize(
        ("title", "expected"),
        [
            ("Field Campaign in Estonia", "field-campaign-in-estonia"),
            ("  leading and trailing  ", "leading-and-trailing"),
            ("Ünïcodé folds", "unicode-folds"),
            ("punctuation!!! -- everywhere", "punctuation-everywhere"),
            ("--leading hyphens--", "leading-hyphens"),
        ],
    )
    def test_folds_a_title_to_a_slug(self, title: str, expected: str) -> None:
        assert pb_pages.slug_for_title(title) == expected

    @pytest.mark.parametrize(
        "title",
        [
            "Field Campaign in Estonia",
            "--leading hyphens--",
            "Ünïcodé folds",
            "a " * 300,
            "x" * 500,
            # Nothing survives the fold, so the shared fallback is all that
            # stands between this and a slug the column rejects.
            "???",
            "日本語",
        ],
    )
    def test_anything_at_all_satisfies_pagebuilders_pattern(self, title: str) -> None:
        """A slug that fails the pattern is a 422 the author cannot act on.

        Truncating to the column bound is where this nearly went wrong: the cut
        can land mid-separator, and a trailing hyphen fails the pattern.
        """
        slug = pb_pages.slug_for_title(title)

        assert slug, "never empty — the column is unique and NOT NULL"
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


class TestRoutes:
    def test_the_editor_path_names_the_page(self) -> None:
        assert pb.page_editor_path(7) == "/pagebuilder/7/edit"

    def test_the_media_path_is_a_pagebuilder_route(self) -> None:
        assert pb.media_library_path().startswith("/pagebuilder")

    def test_the_page_search_path_carries_the_query(self) -> None:
        assert "sensors" in pb.page_search_path("sensors")


class TestDisplayDate:
    """``published_at`` is a date; the API accepts an instant."""

    def test_a_naive_datetime_is_taken_at_face_value(self) -> None:
        normalised = as_display_date(datetime(2026, 2, 1, 22, 30))

        assert normalised == datetime(2026, 2, 1, tzinfo=UTC)

    def test_an_offset_is_not_applied_before_truncating(self) -> None:
        """The bug this exists to remove.

        6pm on the 1st in UTC-6 is the 2nd in UTC. Converting first and
        truncating second stored and listed it as the 2nd — a day the author
        never picked.
        """
        evening = datetime(2026, 2, 1, 18, 0, tzinfo=timezone(timedelta(hours=-6)))

        assert as_display_date(evening) == datetime(2026, 2, 1, tzinfo=UTC)

    def test_a_time_already_at_midnight_utc_is_unchanged(self) -> None:
        midnight = datetime(2026, 2, 1, tzinfo=UTC)

        assert as_display_date(midnight) == midnight

    def test_undated_stays_undated(self) -> None:
        # An undated article is work in progress — a real value, not a missing
        # one, so it must not be turned into a date.
        assert as_display_date(None) is None


class TestPublicArticlePath:
    """Where an article serves. Its own prefix, not pagebuilder's generic one —
    an article used to sit at ``/p/{slug}`` next to the contact page, so the
    address said nothing about what the document was."""

    def test_the_default_prefix_is_the_modules_own(self) -> None:
        assert public_article_path("estonia") == "/news/estonia"

    def test_a_deployment_can_move_it(self) -> None:
        """A setting rather than a constant because it is the one thing here a
        site owner has an opinion about — /news, /blog, or a word in their own
        language."""
        news_settings.use(NewsSettings(public_route_prefix="/aktuelles"))

        assert public_article_path("estonia") == "/aktuelles/estonia"

    def test_a_trailing_slash_does_not_double(self) -> None:
        news_settings.use(NewsSettings(public_route_prefix="/blog/"))

        assert public_article_path("estonia") == "/blog/estonia"
