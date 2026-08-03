"""The sidecar's shape is its contract with pagebuilder."""

from __future__ import annotations

from news.models import NewsArticle


def test_table_name() -> None:
    assert NewsArticle.__tablename__ == "news_articles"


def test_has_the_metadata_a_page_cannot_carry() -> None:
    columns = set(NewsArticle.__table__.columns.keys())
    assert {"id", "page_id", "category", "published_at"} <= columns


def test_one_article_per_page() -> None:
    assert NewsArticle.__table__.columns["page_id"].unique is True


def test_page_id_carries_no_database_foreign_key() -> None:
    # create_module_base gives every module its own MetaData, so a
    # cross-module ForeignKey cannot resolve its target and the mapper raises
    # NoReferencedTableError. Orphans are made harmless by the listing's inner
    # join instead — see the model docstring.
    assert NewsArticle.__table__.columns["page_id"].foreign_keys == set()


def test_listing_columns_are_indexed() -> None:
    # Every listing filters on category and orders by published_at.
    for name in ("category", "published_at", "page_id"):
        assert NewsArticle.__table__.columns[name].index is True
