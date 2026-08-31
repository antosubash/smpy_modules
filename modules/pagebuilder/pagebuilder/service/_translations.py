"""A page's counterparts in the site's other languages.

A translation is an ordinary page: same table, same workflow, same revisions,
its own slug and its own draft. What makes two pages translations of each other
is that they share a ``translation_group`` — see :class:`pagebuilder.models.Page`
for why that is a generated key rather than a pointer at an "original".

That choice is what makes this file short. Publishing a German page, scheduling
it, rejecting it, restoring one of its revisions — none of it needed a line of
new code, because the German page is a page.
"""

from __future__ import annotations

from copy import deepcopy

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from pagebuilder import locales
from pagebuilder.contracts.schemas import (
    PageDetail,
    PageTranslationCreate,
    PageTranslationRead,
)
from pagebuilder.models import NOT_TRASHED, Page, PageStatus

# How many "-2", "-3"… variants to try when the source's slug is already taken
# in the target language. Far past any honest collision; it exists so a
# pathological slug cannot spin.
_MAX_SLUG_ATTEMPTS = 20
_SLUG_MAX_LEN = 200


class TranslationsMixin:
    """Sibling lookups and translation creation. Mixed into ``PagesService``."""

    db: AsyncSession

    async def list_translations(self, group: str) -> list[Page]:
        """Every page in ``group``, the source included — trashed ones too.

        Trashed siblings are listed rather than filtered out because
        ``(translation_group, locale)`` is unique regardless of ``deleted_at``:
        the language is occupied until the page is purged or restored, and
        :meth:`create_translation` refuses it. Hiding the row would leave the
        editor offering an "Add translation" button that can only 409. Each
        one is flagged so the panel can say *why* the language is unavailable
        instead of silently dropping its button.

        Ordered by locale so the language switcher does not reshuffle itself
        between two loads of the same page.
        """
        result = await self.db.execute(
            select(Page).where(Page.translation_group == group).order_by(Page.locale)
        )
        return list(result.scalars().all())

    async def detail(self, page: Page) -> PageDetail:
        """``page`` as the editor sees it — its own fields plus its siblings.

        Assembled here rather than by ``PageDetail.model_validate`` alone
        because the siblings are a second query. Every caller that renders the
        editor goes through this, so a screen cannot end up with a language
        switcher that silently lists nothing.
        """
        detail = PageDetail.model_validate(page)
        detail.translations = [
            PageTranslationRead.model_validate(sibling)
            for sibling in await self.list_translations(page.translation_group)
        ]
        return detail

    async def published_alternates(self, group: str) -> list[tuple[str, str]]:
        """``(locale, slug)`` for each *published* page in ``group``.

        What the public page's ``hreflang`` list is built from, so it names
        only addresses that actually answer: advertising a draft translation
        would point a crawler — and a reader following the language switcher —
        at a 404.
        """
        result = await self.db.execute(
            select(Page.locale, Page.slug)
            .where(
                NOT_TRASHED,
                Page.translation_group == group,
                Page.status == PageStatus.PUBLISHED,
            )
            .order_by(Page.locale)
        )
        return [(locale, slug) for locale, slug in result.all()]

    async def create_translation(self, page_id: int, data: PageTranslationCreate) -> Page:
        """Start ``page_id``'s counterpart in ``data.locale``.

        The new page joins the source's group, starts as a draft, and inherits
        the layout — never the status. A translation going live the moment it
        is created would publish untranslated copy at a URL that did not exist
        a second earlier.
        """
        source = await self.get_page(page_id)  # type: ignore[attr-defined]
        locale = locales.resolve(data.locale)
        if locale is None:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"{data.locale!r} is not a content locale. "
                    f"Configured: {', '.join(locales.supported())}."
                ),
            )
        if locale == source.locale:
            raise HTTPException(
                status_code=409, detail=f"This page is already in {locale}."
            )
        existing = await self._sibling(source.translation_group, locale)
        if existing is not None:
            raise HTTPException(
                status_code=409,
                detail=f"A {locale} translation already exists.",
                headers={"X-Existing-Page-Id": str(existing.id)},
            )

        slug = data.slug or await self._free_slug(source.slug, locale)
        page = Page(
            slug=slug,
            locale=locale,
            translation_group=source.translation_group,
            title=data.title or source.title,
            meta_description=source.meta_description,
            og_image=source.og_image,
            index_in_search=source.index_in_search,
            is_template=source.is_template,
            # Nav membership is per language: the German header lists the
            # German pages. Inherited so a translated page appears where its
            # source does instead of having to be re-ticked in every language.
            show_in_header_nav=source.show_in_header_nav,
            show_in_footer=source.show_in_footer,
            # Breadcrumbs must not cross languages, so the parent is the
            # parent's *own* counterpart. When that does not exist yet the
            # translation is simply top-level, which is recoverable; pointing
            # at the source's English parent would not be.
            parent_id=await self._parent_in(source.parent_id, locale),
            draft_data=deepcopy(source.draft_data or {}) if data.copy_content else {},
            status=PageStatus.DRAFT,
        )
        # canonical_url is deliberately not inherited: it names one absolute
        # address, and copying it would make every translation declare the
        # source page as its canonical — telling search engines the
        # translations are duplicates to be ignored.
        self.db.add(page)
        try:
            await self.db.flush()
        except IntegrityError as exc:
            await self.db.rollback()
            raise HTTPException(
                status_code=409, detail=f"Slug {slug!r} is already used in {locale}."
            ) from exc
        await self.db.refresh(page)
        return page

    async def _sibling(self, group: str, locale: str) -> Page | None:
        result = await self.db.execute(
            select(Page).where(Page.translation_group == group, Page.locale == locale)
        )
        # Trashed siblings count. The slug is still claimed while a page waits
        # out the retention window, so treating one as absent would offer to
        # create a translation the unique index then refuses.
        return result.scalars().first()

    async def _parent_in(self, parent_id: int | None, locale: str) -> int | None:
        """The parent page's own counterpart in ``locale``, if it has one."""
        if parent_id is None:
            return None
        parent = await self.db.get(Page, parent_id)
        if parent is None:
            return None
        sibling = await self._sibling(parent.translation_group, locale)
        return sibling.id if sibling is not None else None

    async def _free_slug(self, base: str, locale: str) -> str:
        """``base`` if it is free in ``locale``, else ``base-2``, ``base-3``…

        Usually the first: slugs are unique per language, so the source's own
        slug is available in the new one unless an unrelated page already took
        it. One query for the whole candidate set rather than a
        create-and-catch loop, which would roll back anything the caller had
        already written in the same transaction.
        """
        rows = await self.db.execute(
            select(Page.slug).where(Page.locale == locale, Page.slug.startswith(base[:_stem(base)]))
        )
        taken = set(rows.scalars())
        if base not in taken:
            return base
        for suffix in range(2, _MAX_SLUG_ATTEMPTS + 2):
            candidate = f"{base[: _SLUG_MAX_LEN - len(str(suffix)) - 1]}-{suffix}"
            if candidate not in taken:
                return candidate
        raise HTTPException(
            status_code=409,
            detail=f"Could not derive a free URL from {base!r} in {locale}. Set one explicitly.",
        )


def _stem(base: str) -> int:
    """How much of ``base`` every candidate is guaranteed to share.

    A base already at the column's limit has to be cut to make room for the
    suffix, so its variants do not start with ``base`` — prefiltering on the
    full string would miss them and hand back a slug that is in fact taken.
    """
    longest = len(str(_MAX_SLUG_ATTEMPTS + 1))
    return min(len(base), _SLUG_MAX_LEN - longest - 1)
