"""The article table's shape is this module's contract with itself.

It used to be a contract with pagebuilder: the column that mattered most was
``page_id``, an unenforceable pointer into another module's table, and half the
assertions here were about making that pointer safe. Those are gone, replaced by
the ones a table that owns its content needs.
"""

from __future__ import annotations

from news.models import (
    NewsArticle,
    NewsArticleRedirect,
    NewsArticleRevision,
    NewsArticleTag,
)
from sqlalchemy import Table


def unique_index(table: Table, name: str) -> tuple[str, ...]:
    """The columns of one unique index, in order, or ``()`` if it is absent.

    Named rather than matched on shape because the name is what a migration
    creates and drops: an index that exists under a different one is a schema
    the migrations cannot manage, not a passing test.
    """
    for index in table.indexes:
        if index.name == name:
            assert index.unique is True, f"{name} exists but is not unique"
            return tuple(column.name for column in index.columns)
    return ()


def test_table_name() -> None:
    assert NewsArticle.__tablename__ == "news_articles"


def test_owns_its_content() -> None:
    """The columns that used to live on a pagebuilder page.

    This is the whole split in one assertion: an article is a document here, not
    a label attached to somebody else's document.
    """
    columns = set(NewsArticle.__table__.columns.keys())
    assert {
        "slug",
        "title",
        "draft_data",
        "published_data",
        "status",
        "meta_description",
        "og_image",
    } <= columns


def test_keeps_the_metadata_a_generic_page_never_had() -> None:
    columns = set(NewsArticle.__table__.columns.keys())
    assert {"category", "published_at", "pinned", "show_in_feed", "author"} <= columns


def test_no_page_id_remains() -> None:
    """The sidecar's pointer is gone rather than merely unused.

    Left behind it would be a nullable column nothing writes, and the next
    person to read the model would reasonably assume it still meant something.
    """
    assert "page_id" not in NewsArticle.__table__.columns


def test_one_article_per_slug_per_language() -> None:
    """The slug is the public address *within a language*.

    Two articles sharing one in the same locale would make the URL ambiguous
    and the viewer's lookup non-deterministic. Across locales it is not a
    collision at all: ``/news/budget`` and ``/de/news/budget`` are two
    documents, and forcing the German one to pick a different word would make
    the URL a workaround for a schema decision.
    """
    assert unique_index(NewsArticle.__table__, "ix_news_articles_tenant_locale_slug") == (
        "tenant_id",
        "locale",
        "slug",
    )
    assert NewsArticle.__table__.columns["slug"].unique is not True


def test_one_article_per_language_per_translation_group() -> None:
    # Without it a second "add German" click — a double submit, a stale tab —
    # produces two German siblings and every alternates list starts
    # contradicting itself.
    assert unique_index(
        NewsArticle.__table__, "ix_news_articles_tenant_group_locale"
    ) == (
        "tenant_id",
        "translation_group",
        "locale",
    )


def test_every_article_has_a_language_and_a_group() -> None:
    """Neither is nullable, and both are defaulted by a factory.

    A nullable locale would mean every query had to spell "this locale or
    nothing", and the rows that predate the feature would be the ones behaving
    differently. A nullable group would make "does this have translations" a
    null check instead of "are there siblings sharing this group" — every
    article starts a group of one.
    """
    for name in ("locale", "translation_group"):
        assert NewsArticle.__table__.columns[name].nullable is False


def test_listing_columns_are_indexed() -> None:
    # Every listing filters on category or status and orders by published_at;
    # the trash filter is on every query there is.
    for name in ("category", "published_at", "status", "deleted_at"):
        assert NewsArticle.__table__.columns[name].index is True


def test_the_addressing_columns_lean_on_their_composites() -> None:
    """No single-column index on slug, locale or translation_group.

    Both composites lead with the column a single-column lookup would want, so
    a ``locale = ?`` or ``translation_group = ?`` scan already has one to use
    and a second would only cost writes. The viewer never looks a slug up
    without a locale either, so the pair is the index it actually wants.
    """
    for name in ("slug", "locale", "translation_group"):
        assert NewsArticle.__table__.columns[name].index is not True


def test_revisions_cascade_from_the_article() -> None:
    """A real foreign key, which the sidecar could not have.

    ``create_module_base`` gives every module its own ``MetaData``, so the old
    cross-module pointer could not carry one and deletion had to be swept up
    afterwards. Both sides live here now, so the database does the work.
    """
    fk = next(iter(NewsArticleRevision.__table__.columns["article_id"].foreign_keys))
    assert fk.column.table.name == "news_articles"
    assert fk.ondelete == "CASCADE"


def test_redirects_cascade_from_the_article() -> None:
    fk = next(iter(NewsArticleRedirect.__table__.columns["article_id"].foreign_keys))
    assert fk.column.table.name == "news_articles"
    assert fk.ondelete == "CASCADE"


def test_an_old_slug_resolves_to_exactly_one_article_per_language() -> None:
    # Scoped to a language for the same reason the article's own slug is: two
    # languages can legitimately have retired the same word, and a global
    # unique index would make the second rename collide with the first.
    assert unique_index(
        NewsArticleRedirect.__table__, "ix_news_article_redirects_tenant_locale_from_slug"
    ) == ("tenant_id", "locale", "from_slug")
    assert NewsArticleRedirect.__table__.columns["from_slug"].unique is not True


def test_tag_links_cascade_from_the_article() -> None:
    fk = next(iter(NewsArticleTag.__table__.columns["article_id"].foreign_keys))
    assert fk.column.table.name == "news_articles"
    assert fk.ondelete == "CASCADE"
