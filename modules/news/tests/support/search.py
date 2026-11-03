"""Cross-section search.

Articles are always searched — they are this module's own. Pages and media are
searched only where pagebuilder happens to be installed, which is what
``news.integrations.pagebuilder`` now decides.

What used to be worth pinning here was that an article is a page underneath, so
the obvious implementation counted it twice and reported more results than the
archive held. That hazard is gone with the sidecar: they are two tables, and a
row can only be in one of them. What replaces it is the other shape — that the
whole screen still works with no neighbour at all.
"""

from __future__ import annotations

from tests.support.factories import make_article

#: Pagebuilder is a workspace member here, so these run. On a host that
#: installed news alone they are skipped rather than failing — which is the
#: behaviour the split is for.


async def _article(db, slug: str, *, category: str = "", title: str | None = None,
                   draft_data: dict | None = None):
    return await make_article(
        db, slug=slug, title=title or slug, category=category, draft_data=draft_data
    )


async def _page(db, slug: str, *, title: str | None = None, draft_data: dict | None = None,
                tenant: str = "default"):
    from pagebuilder.models import Page, PageStatus

    page = Page(
        # pagebuilder's tables are tenant-owned; news (and so this suite) is
        # not tenant-aware yet, so the row is filed where a single-tenant host's
        # pages live rather than stamped from a binding nothing here makes.
        tenant_id=tenant,
        slug=slug,
        title=title or slug,
        status=PageStatus.PUBLISHED,
        draft_data=draft_data or {},
    )
    db.add(page)
    await db.commit()
    await db.refresh(page)
    return page
