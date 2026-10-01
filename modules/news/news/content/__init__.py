"""Writes to an article — its body, its address, its workflow.

This is the half of the module that did not exist while an article was a
sidecar: creating one meant creating a *page*, publishing one meant publishing
that page, and both went through a neighbour's service. Owning the content means
owning those writes, and this is where they live.

The read side stays in :mod:`news.service`, which is queried far more often than
it is written to and has no business carrying the transition rules.

Composed from a mixin chain so no single file carries the whole surface:
:mod:`._workflow` holds the status transitions and the trash and extends
:mod:`._revisions`, which holds the history — every transition records one.
Creation, editing and slug handling stay here.
"""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from news import locales, redirects
from news.content._revisions import clear_revisions
from news.content._slugs import free_slug, slug_exhausted, slug_for_title, slug_taken
from news.content._workflow import WorkflowMixin
from news.models import NOT_TRASHED, ArticleStatus, NewsArticle

__all__ = ["ArticlesService", "empty_article_document", "slug_for_title"]


def empty_article_document(title: str) -> dict[str, Any]:
    """What the body editor opens for an article with no blocks yet.

    The ``title`` column is the article's headline — the admin list, the public
    ``<title>``, the card and the rendered ``<h1>`` all read it, and the article
    screen is where it is edited. The copy in the root props is inert: Puck
    stores a root prop bag per document and this one has never had a field
    behind it, so nothing writes to it and nothing renders it. It is seeded
    anyway so every document has the same shape, whether it was created here or
    carried over by the migration.
    """
    return {
        "root": {"props": {"title": title}},
        "content": [],
        "zones": {},
    }


class ArticlesService(WorkflowMixin):
    """Article writes, constructed per-request from the injected session.

    Nothing here commits. In a request the framework's ``get_db`` owns the
    transaction and commits on the way out, so committing would take that
    decision away from the endpoint and leave a row behind when the handler goes
    on to raise.
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ── Queries the write paths need ──────────────────────────────────
    async def get_article(
        self, article_id: int, *, include_trashed: bool = False
    ) -> NewsArticle:
        """One article by id.

        A trashed article is a 404 here, not a row with a flag on it: every
        caller is an ordinary read or write, and letting one through would mean
        editing or publishing something the author believes they deleted.
        ``restore`` passes ``include_trashed`` because it is the one operation
        that is *about* trashed articles.
        """
        article = await self.db.get(NewsArticle, article_id)
        if article is None or (
            article.deleted_at is not None and not include_trashed
        ):
            raise HTTPException(status_code=404, detail="Article not found")
        return article

    async def get_by_slug_published(
        self, slug: str, locale: str | None = None
    ) -> NewsArticle | None:
        """One published article by address — slug *and* language.

        Both, because a slug identifies an article only within one language:
        ``/news/budget`` and ``/de/news/budget`` are two documents, and a lookup
        that took only the slug would serve whichever of them the database
        happened to return first. ``None`` means the site's default, which is
        what an unqualified slug can only mean.
        """
        result = await self.db.execute(
            select(NewsArticle).where(
                NOT_TRASHED,
                NewsArticle.slug == slug,
                NewsArticle.locale == (locale or locales.default()),
                NewsArticle.status == ArticleStatus.PUBLISHED,
            )
        )
        return result.scalars().first()

    # ── Create and edit ───────────────────────────────────────────────
    async def create(
        self,
        *,
        title: str,
        slug: str | None = None,
        locale: str | None = None,
        translation_group: str | None = None,
        category: str = "",
        author: str = "",
        published_at: Any = None,
        draft_data: dict[str, Any] | None = None,
    ) -> NewsArticle:
        """Create an article, deriving its address when none was given.

        An author-supplied ``slug`` is used verbatim and a collision is
        reported rather than silently altered: the URL is a thing they typed and
        expect to get. Only the derived default looks for a free variant,
        because there the author expressed no preference beyond the headline —
        and it looks within ``locale`` alone, since that is the scope a slug is
        unique in.

        The language is settled here and never again: it is fixed for the
        article's lifetime, because moving one between languages would strand
        its slug in the old one and orphan every redirect pointing at it.
        ``translation_group`` is passed only when this article is being started
        as a counterpart to another — see
        :mod:`news.endpoints.api.translations`. Left out, the column's own
        ``default_factory`` mints a fresh group, which is why it is *omitted*
        from the constructor rather than handed a ``None``: passing the None
        through would override that default with a value the column forbids.
        """
        active_locale = locale or locales.default()
        if slug:
            chosen = slug
        else:
            chosen = await free_slug(self.db, slug_for_title(title), active_locale)
            if not chosen:
                raise slug_exhausted(title)

        article = NewsArticle(
            title=title,
            slug=chosen,
            locale=active_locale,
            category=category,
            author=author,
            published_at=published_at,
            draft_data=draft_data
            if draft_data is not None
            else empty_article_document(title),
            status=ArticleStatus.DRAFT,
            **({"translation_group": translation_group} if translation_group else {}),
        )
        self.db.add(article)
        try:
            await self.db.flush()
        except IntegrityError as exc:
            await self.db.rollback()
            raise slug_taken() from exc
        await self.db.refresh(article)
        return article

    async def update(self, article_id: int, fields: dict[str, Any]) -> NewsArticle:
        """Apply the fields the caller actually sent.

        ``fields`` is already ``exclude_unset``-filtered by the endpoint, so an
        omitted key leaves its column alone while an explicit ``None`` clears
        it — a distinction the DTO can express and a plain ``or`` cannot.
        """
        article = await self.get_article(article_id)
        # Captured before the loop: once the slug is overwritten there is
        # nothing left to redirect *from*.
        previous_slug = article.slug
        for field, value in fields.items():
            setattr(article, field, value)
        self.db.add(article)
        try:
            await self.db.flush()
        except IntegrityError as exc:
            await self.db.rollback()
            raise slug_taken() from exc
        # Recorded after the flush, so a rename the database rejected leaves no
        # redirect pointing at an address the article never took. Scoped to the
        # article's own language, which a rename cannot change — the redirect
        # belongs to the address it replaces, and that address is in one
        # language only.
        await redirects.record(
            self.db,
            article_id=article_id,
            old_slug=previous_slug,
            new_slug=article.slug,
            locale=article.locale,
        )
        await self.db.refresh(article)
        return article

    async def save_body(
        self, article_id: int, data: dict[str, Any]
    ) -> NewsArticle:
        """Autosave from the block canvas — the draft only, never the live copy.

        Separate from :meth:`update` because it is the one write that fires on a
        timer rather than on a person pressing something, and it must not be
        able to touch the slug, the status or anything else a rename would
        record a redirect for.
        """
        article = await self.get_article(article_id)
        article.draft_data = data
        self.db.add(article)
        await self.db.flush()
        await self.db.refresh(article)
        return article

    async def purge(self, article_id: int) -> None:
        """Remove the row for good, with its redirects and its history.

        The tag links go by ``ondelete="CASCADE"`` where the database enforces
        it; ``news.tag_service.unlink_article`` is what the endpoint calls
        first, because SQLite only honours those with ``PRAGMA foreign_keys=ON``
        and nothing here sets it.
        """
        article = await self.get_article(article_id, include_trashed=True)
        await redirects.clear_for_article(self.db, article_id)
        await clear_revisions(self.db, article_id)
        await self.db.delete(article)
        await self.db.flush()
