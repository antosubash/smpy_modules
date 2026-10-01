"""news owns its article content

An article used to be a *sidecar*: a category and a date on a ``news_articles``
row, pointing by id at a ``pagebuilder_pages`` row that held the title, the
slug, the body, the workflow and the SEO. This moves all of that onto the
article itself, so ``simple_module_news`` can be installed, migrated and served
without its former neighbour.

The interesting part is not the DDL — it is the backfill in the middle. Every
existing article's content lives in the page it points at, so adding the columns
without copying it across would leave a site with a table full of untitled,
unaddressable, empty articles. The copy is guarded on ``pagebuilder_pages``
actually existing: a host that installed news alone has no such table, and by
definition no articles that could have come from one.

Revision ID: 7a1a2e92f6df
Revises: 6504b2249610
Create Date: 2026-08-25 22:16:49.553608
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "7a1a2e92f6df"
down_revision: str | None = "6504b2249610"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_PAGES = "pagebuilder_pages"

# Named once, because Postgres keeps an enum as a type of its own: ``add_column``
# does not create it (only ``create_table`` does), and dropping the column or
# table does not drop it. Both are created and dropped explicitly below, which
# is a no-op on SQLite, where an enum is only a CHECK-less VARCHAR.
_STATUS = sa.Enum("DRAFT", "SUBMITTED_FOR_REVIEW", "PUBLISHED", name="news_article_status")
_EVENT = sa.Enum("PUBLISH", "UNPUBLISH", "SUBMIT", "APPROVE", "REJECT", name="news_revision_event")


def _has_pages(bind) -> bool:
    return _PAGES in sa.inspect(bind).get_table_names()


def _backfill(bind) -> None:
    """Copy each article's content out of the page it points at.

    Matched on ``page_id``, which is still there at this point — it is dropped
    at the very end, after this has run.

    ``INNER JOIN`` semantics by construction: an article whose page had already
    been deleted gets nothing here and falls through to the fallbacks below.
    Such a row was invisible on the old schema anyway (every listing joined the
    page), so this neither loses nor resurrects anything.
    """
    if not _has_pages(bind):
        return
    # Pagebuilder's status is its own enum type on Postgres, and Postgres will
    # not assign one enum type to another. The labels are identical, so going
    # through text is exact. SQLite needs no cast — and must not get one: it
    # would give the unknown type name NUMERIC affinity and turn every label
    # into 0.
    page_status = "p.status"
    if bind.dialect.name == "postgresql":
        page_status = "CAST(CAST(p.status AS TEXT) AS news_article_status)"
    bind.execute(
        sa.text(
            f"""
            UPDATE news_articles SET
                slug = COALESCE(
                    (SELECT p.slug FROM {_PAGES} p WHERE p.id = news_articles.page_id),
                    slug
                ),
                title = COALESCE(
                    (SELECT p.title FROM {_PAGES} p WHERE p.id = news_articles.page_id),
                    title
                ),
                draft_data = COALESCE(
                    (SELECT p.draft_data FROM {_PAGES} p WHERE p.id = news_articles.page_id),
                    draft_data
                ),
                published_data = (
                    SELECT p.published_data FROM {_PAGES} p WHERE p.id = news_articles.page_id
                ),
                status = COALESCE(
                    (SELECT {page_status} FROM {_PAGES} p WHERE p.id = news_articles.page_id),
                    status
                ),
                meta_description = (
                    SELECT p.meta_description FROM {_PAGES} p WHERE p.id = news_articles.page_id
                ),
                og_image = (
                    SELECT p.og_image FROM {_PAGES} p WHERE p.id = news_articles.page_id
                ),
                canonical_url = (
                    SELECT p.canonical_url FROM {_PAGES} p WHERE p.id = news_articles.page_id
                ),
                index_in_search = COALESCE(
                    (SELECT p.index_in_search FROM {_PAGES} p WHERE p.id = news_articles.page_id),
                    index_in_search
                ),
                json_ld = (
                    SELECT p.json_ld FROM {_PAGES} p WHERE p.id = news_articles.page_id
                ),
                deleted_at = (
                    SELECT p.deleted_at FROM {_PAGES} p WHERE p.id = news_articles.page_id
                )
            """
        )
    )


def _carry_over_redirects(bind) -> None:
    """Keep the old addresses of renamed articles working.

    Pagebuilder recorded a redirect whenever a page's slug changed, and the news
    viewer read that table because the slug being renamed was a page's. It reads
    its own now, so the rows that belong to articles have to come across or every
    article ever renamed loses its old URL at upgrade time.

    Only the rows pointing at pages that are articles are taken; the rest stay
    where they are, still serving pagebuilder's own viewer.
    """
    if not _has_pages(bind):
        return
    if "pagebuilder_page_redirects" not in sa.inspect(bind).get_table_names():
        return
    bind.execute(
        sa.text(
            """
            INSERT INTO news_article_redirects (from_slug, article_id)
            SELECT r.from_slug, a.id
            FROM pagebuilder_page_redirects r
            JOIN news_articles a ON a.page_id = r.page_id
            """
        )
    )


def _fill_gaps(bind) -> None:
    """Give any article the backfill could not reach a usable identity.

    Only reachable for a row whose page was already gone — invisible on the old
    schema, and about to become visible on this one. A derived slug and a
    placeholder title keep the NOT NULL constraints satisfiable and leave the
    row findable in the admin list, which is where someone can decide whether to
    keep it. Silently deleting other people's rows in a migration is not this
    file's call to make.
    """
    bind.execute(
        sa.text(
            """
            UPDATE news_articles
            SET slug = 'article-' || id
            WHERE slug IS NULL OR slug = ''
            """
        )
    )
    bind.execute(
        sa.text(
            """
            UPDATE news_articles
            SET title = 'Untitled article ' || id
            WHERE title IS NULL OR title = ''
            """
        )
    )
    bind.execute(sa.text("UPDATE news_articles SET draft_data = '{}' WHERE draft_data IS NULL"))
    # A recovered orphan must not go live on upgrade. DRAFT is the only safe
    # default: it is the one state that publishes nothing.
    bind.execute(sa.text("UPDATE news_articles SET status = 'DRAFT' WHERE status IS NULL"))
    bind.execute(
        sa.text("UPDATE news_articles SET index_in_search = TRUE WHERE index_in_search IS NULL")
    )


def upgrade() -> None:
    op.create_table(
        "news_article_redirects",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("from_slug", sa.String(length=200), nullable=False),
        sa.Column("article_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["article_id"],
            ["news_articles.id"],
            name=op.f("fk_news_article_redirects_article_id_news_articles"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_news_article_redirects")),
    )
    op.create_index(
        op.f("ix_news_article_redirects_article_id"),
        "news_article_redirects",
        ["article_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_news_article_redirects_from_slug"),
        "news_article_redirects",
        ["from_slug"],
        unique=True,
    )
    op.create_table(
        "news_article_revisions",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(length=255), nullable=True),
        sa.Column("updated_by", sa.String(length=255), nullable=True),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("article_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=300), nullable=False),
        sa.Column("meta_description", sa.String(length=500), nullable=True),
        sa.Column("og_image", sa.String(length=500), nullable=True),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column(
            "event",
            _EVENT,
            server_default="PUBLISH",
            nullable=False,
        ),
        sa.Column("note", sa.String(length=2000), nullable=True),
        sa.ForeignKeyConstraint(
            ["article_id"],
            ["news_articles.id"],
            name=op.f("fk_news_article_revisions_article_id_news_articles"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_news_article_revisions")),
    )
    op.create_index(
        op.f("ix_news_article_revisions_article_id"),
        "news_article_revisions",
        ["article_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_news_article_revisions_event"),
        "news_article_revisions",
        ["event"],
        unique=False,
    )

    # Added nullable, every one of them. Autogenerate proposed NOT NULL, which
    # cannot be applied to a table that already holds rows — and these rows have
    # no values yet, because their values are still in another table. The
    # constraints go on after the backfill.
    op.add_column("news_articles", sa.Column("slug", sa.String(length=200), nullable=True))
    op.add_column("news_articles", sa.Column("title", sa.String(length=300), nullable=True))
    op.add_column("news_articles", sa.Column("draft_data", sa.JSON(), nullable=True))
    op.add_column("news_articles", sa.Column("published_data", sa.JSON(), nullable=True))
    _STATUS.create(op.get_bind(), checkfirst=True)
    op.add_column("news_articles", sa.Column("status", _STATUS, nullable=True))
    op.add_column(
        "news_articles", sa.Column("meta_description", sa.String(length=500), nullable=True)
    )
    op.add_column("news_articles", sa.Column("og_image", sa.String(length=500), nullable=True))
    op.add_column(
        "news_articles", sa.Column("canonical_url", sa.String(length=500), nullable=True)
    )
    op.add_column("news_articles", sa.Column("index_in_search", sa.Boolean(), nullable=True))
    op.add_column("news_articles", sa.Column("json_ld", sa.JSON(), nullable=True))
    op.add_column(
        "news_articles", sa.Column("rejection_note", sa.String(length=2000), nullable=True)
    )
    op.add_column(
        "news_articles", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True)
    )

    bind = op.get_bind()
    _backfill(bind)
    _carry_over_redirects(bind)
    _fill_gaps(bind)

    # Now that every row has values, the columns can carry the constraints the
    # model declares. Batched because SQLite cannot alter a column in place.
    with op.batch_alter_table("news_articles") as batch:
        batch.alter_column("slug", existing_type=sa.String(length=200), nullable=False)
        batch.alter_column("title", existing_type=sa.String(length=300), nullable=False)
        batch.alter_column("draft_data", existing_type=sa.JSON(), nullable=False)
        batch.alter_column(
            "status",
            existing_type=_STATUS,
            nullable=False,
        )
        batch.alter_column("index_in_search", existing_type=sa.Boolean(), nullable=False)

    op.drop_index(op.f("ix_news_articles_page_id"), table_name="news_articles")
    op.create_index(
        op.f("ix_news_articles_deleted_at"), "news_articles", ["deleted_at"], unique=False
    )
    op.create_index(op.f("ix_news_articles_slug"), "news_articles", ["slug"], unique=True)
    op.create_index(op.f("ix_news_articles_status"), "news_articles", ["status"], unique=False)
    # Last, so everything above could still read it.
    op.drop_column("news_articles", "page_id")


def downgrade() -> None:
    """Put the sidecar's shape back.

    The *shape* only. There is no way to restore the link: ``page_id`` named a
    row in another module's table, and nothing in this schema recorded which one
    after the columns were merged. A downgraded article keeps its category and
    date and points at nothing, which is the honest outcome — inventing page ids
    would silently attach articles to whatever happened to hold them.
    """
    op.add_column("news_articles", sa.Column("page_id", sa.INTEGER(), nullable=True))
    # Negative, so it is NOT NULL and unique as the old schema demands yet can
    # never name a real page — `id` itself would attach each article to
    # whichever unrelated page happened to hold that number.
    op.execute("UPDATE news_articles SET page_id = -id")
    op.drop_index(op.f("ix_news_articles_status"), table_name="news_articles")
    op.drop_index(op.f("ix_news_articles_slug"), table_name="news_articles")
    op.drop_index(op.f("ix_news_articles_deleted_at"), table_name="news_articles")
    with op.batch_alter_table("news_articles") as batch:
        batch.alter_column("page_id", existing_type=sa.INTEGER(), nullable=False)
    op.create_index(
        op.f("ix_news_articles_page_id"), "news_articles", ["page_id"], unique=True
    )
    op.drop_column("news_articles", "deleted_at")
    op.drop_column("news_articles", "rejection_note")
    op.drop_column("news_articles", "json_ld")
    op.drop_column("news_articles", "index_in_search")
    op.drop_column("news_articles", "canonical_url")
    op.drop_column("news_articles", "og_image")
    op.drop_column("news_articles", "meta_description")
    op.drop_column("news_articles", "status")
    op.drop_column("news_articles", "published_data")
    op.drop_column("news_articles", "draft_data")
    op.drop_column("news_articles", "title")
    op.drop_column("news_articles", "slug")
    op.drop_index(op.f("ix_news_article_revisions_event"), table_name="news_article_revisions")
    op.drop_index(
        op.f("ix_news_article_revisions_article_id"), table_name="news_article_revisions"
    )
    op.drop_table("news_article_revisions")
    op.drop_index(
        op.f("ix_news_article_redirects_from_slug"), table_name="news_article_redirects"
    )
    op.drop_index(
        op.f("ix_news_article_redirects_article_id"), table_name="news_article_redirects"
    )
    op.drop_table("news_article_redirects")
    bind = op.get_bind()
    _STATUS.drop(bind, checkfirst=True)
    _EVENT.drop(bind, checkfirst=True)
