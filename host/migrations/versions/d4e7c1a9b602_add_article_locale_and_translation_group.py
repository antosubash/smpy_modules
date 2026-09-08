"""add article locale and translation group

Revision ID: d4e7c1a9b602
Revises: 8fd18ebe15e4, b1f4a72c9d30
Create Date: 2026-09-08 14:20:00.000000

Also the merge point for two heads. ``8fd18ebe15e4`` is the line on which an
article stopped being a sidecar over a page and grew its own body, address and
schedule; ``b1f4a72c9d30`` is the one on which pages became multilingual. They
were written in parallel, so a host that has run both is at neither head until
something joins them — and joining them is what this change is *about*, so it
happens here rather than in an empty merge revision of its own.

Being a merge node has one consequence worth knowing before you meet it:
``alembic downgrade -1`` from here fails with "Ambiguous walk", because a
relative step has two parents to choose between and alembic will not guess.
Name the revision you want instead — ``alembic downgrade b1f4a72c9d30`` or
``alembic downgrade 8fd18ebe15e4`` — which runs this revision's ``downgrade``
and then unwinds the branch you named.

Hand-adjusted from autogenerate in three places, for the same reasons
``b1f4a72c9d30`` was on the pages side:

* ``locale`` is NOT NULL, so it needs a ``server_default`` for the rows that
  already exist. Everything written before this migration is in the default
  content locale by definition — that is the language whose articles keep
  serving at the unprefixed URL. The default is dropped again afterwards so the
  application owns the column's default from here on.
* ``translation_group`` is NOT NULL *and* has to differ per row (it is half of
  a unique index), which no ``server_default`` can express portably. It goes in
  nullable, gets a generated value per existing article, and is tightened to
  NOT NULL after.
* Both unique indexes on a slug are replaced rather than added to: slugs are
  unique per language now, so the old single-column ones would forbid exactly
  the case this change exists to allow — the same word as the address in two
  languages.
"""

from collections.abc import Sequence
from uuid import uuid4

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d4e7c1a9b602"
down_revision: str | tuple[str, ...] | None = ("8fd18ebe15e4", "b1f4a72c9d30")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ARTICLES = "news_articles"
_REDIRECTS = "news_article_redirects"
_LOCALE_LEN = 12
_GROUP_LEN = 32

# Read straight out of the settings table rather than through ``NewsSettings``:
# a migration that constructs application settings starts failing whenever an
# unrelated required setting is added, and this is the only value it needs.
#
# The key is *pagebuilder's*, deliberately, and not news' own. News has no
# ``default_content_locale`` setting: ``news.locales`` borrows the site's
# content languages from pagebuilder where that module is installed, because an
# article and a page are documents on the same site and two lists would drift.
# Where it is not installed there is no stored value to find, and the fallback
# below is the same "en" both modules declare as their default.
_SETTINGS_TABLE = "settings_setting"
_LOCALE_KEY = "pagebuilder.default_content_locale"
_FALLBACK_LOCALE = "en"

_SETTINGS = sa.table(
    _SETTINGS_TABLE,
    sa.column("scope", sa.String),
    sa.column("scope_id", sa.String),
    sa.column("key", sa.String),
    sa.column("value", sa.String),
)


def _default_locale(bind: sa.Connection) -> str:
    """The language every pre-existing article is in, per the settings store.

    ``default_content_locale`` is a plain ``str``, so the store holds it
    verbatim rather than JSON-encoded. The table is checked for rather than
    assumed: a host that mounts news without the Settings module would
    otherwise fail here instead of backfilling the default.
    """
    if not sa.inspect(bind).has_table(_SETTINGS_TABLE):
        return _FALLBACK_LOCALE
    stored = bind.scalar(
        sa.select(_SETTINGS.c.value).where(
            _SETTINGS.c.scope == "system",
            _SETTINGS.c.scope_id == "",
            _SETTINGS.c.key == _LOCALE_KEY,
        )
    )
    return (stored or "").strip() or _FALLBACK_LOCALE


def upgrade() -> None:
    bind = op.get_bind()
    locale = _default_locale(bind)

    with op.batch_alter_table(_ARTICLES) as batch:
        batch.add_column(
            sa.Column(
                "locale",
                sa.String(length=_LOCALE_LEN),
                nullable=False,
                server_default=locale,
            )
        )
        batch.add_column(
            sa.Column("translation_group", sa.String(length=_GROUP_LEN), nullable=True)
        )

    articles = sa.table(
        _ARTICLES,
        sa.column("id", sa.Integer),
        sa.column("translation_group", sa.String),
    )
    # One group per existing article: nothing was a translation of anything
    # before this migration, so every row is a group of one.
    for (article_id,) in bind.execute(sa.select(articles.c.id)).all():
        bind.execute(
            articles.update()
            .where(articles.c.id == article_id)
            .values(translation_group=uuid4().hex)
        )

    op.drop_index(op.f("ix_news_articles_slug"), table_name=_ARTICLES)
    with op.batch_alter_table(_ARTICLES) as batch:
        batch.alter_column("locale", server_default=None)
        batch.alter_column(
            "translation_group",
            existing_type=sa.String(length=_GROUP_LEN),
            nullable=False,
        )
    op.create_index(
        "ix_news_articles_locale_slug", _ARTICLES, ["locale", "slug"], unique=True
    )
    op.create_index(
        "ix_news_articles_group_locale",
        _ARTICLES,
        ["translation_group", "locale"],
        unique=True,
    )

    with op.batch_alter_table(_REDIRECTS) as batch:
        batch.add_column(
            sa.Column(
                "locale",
                sa.String(length=_LOCALE_LEN),
                nullable=False,
                server_default=locale,
            )
        )
    op.drop_index(op.f("ix_news_article_redirects_from_slug"), table_name=_REDIRECTS)
    with op.batch_alter_table(_REDIRECTS) as batch:
        batch.alter_column("locale", server_default=None)
    op.create_index(
        "ix_news_article_redirects_locale_from_slug",
        _REDIRECTS,
        ["locale", "from_slug"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_news_article_redirects_locale_from_slug", table_name=_REDIRECTS)
    with op.batch_alter_table(_REDIRECTS) as batch:
        batch.drop_column("locale")
    op.create_index(
        op.f("ix_news_article_redirects_from_slug"),
        _REDIRECTS,
        ["from_slug"],
        unique=True,
    )

    op.drop_index("ix_news_articles_group_locale", table_name=_ARTICLES)
    op.drop_index("ix_news_articles_locale_slug", table_name=_ARTICLES)
    with op.batch_alter_table(_ARTICLES) as batch:
        batch.drop_column("translation_group")
        batch.drop_column("locale")
    # Re-creating the global unique index fails if two languages had claimed the
    # same slug — which is the whole point of the upgrade. Downgrading a
    # database that used the feature therefore needs those resolved first; that
    # is a data decision, not one a migration can make.
    op.create_index(op.f("ix_news_articles_slug"), _ARTICLES, ["slug"], unique=True)
