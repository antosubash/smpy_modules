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


def test_one_article_per_slug() -> None:
    # The slug is the public address. Two articles sharing one would make the
    # URL ambiguous and the viewer's lookup non-deterministic.
    assert NewsArticle.__table__.columns["slug"].unique is True


def test_listing_columns_are_indexed() -> None:
    # Every listing filters on category or status and orders by published_at;
    # the viewer looks up by slug; the trash filter is on every query there is.
    for name in ("category", "published_at", "slug", "status", "deleted_at"):
        assert NewsArticle.__table__.columns[name].index is True


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


def test_an_old_slug_resolves_to_exactly_one_article() -> None:
    assert NewsArticleRedirect.__table__.columns["from_slug"].unique is True


def test_tag_links_cascade_from_the_article() -> None:
    fk = next(iter(NewsArticleTag.__table__.columns["article_id"].foreign_keys))
    assert fk.column.table.name == "news_articles"
    assert fk.ondelete == "CASCADE"
