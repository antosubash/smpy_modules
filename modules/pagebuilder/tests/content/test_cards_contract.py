"""``pagebuilder.contracts.cards`` — page and media cards for newsletters."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from pagebuilder.contracts.cards import (
    MediaCard,
    PageCard,
    get_page_card,
    search_media_cards,
    search_page_cards,
)
from pagebuilder.core import locales
from pagebuilder.core.settings import PagebuilderSettings
from pagebuilder.models import MediaAsset, Page, PageStatus
from simple_module_db import TenantIsolationError, tenant_context

pytestmark = [pytest.mark.asyncio, pytest.mark.unbound_tenant]


def _app(**settings):
    pb = SimpleNamespace(settings=PagebuilderSettings(**settings))
    return SimpleNamespace(state=SimpleNamespace(pagebuilder=pb))


async def _page(
    db, slug, *, tenant="default", locale="en", status=PageStatus.PUBLISHED, trashed=False
):
    page = Page(
        tenant_id=tenant,
        slug=slug,
        title=slug.title(),
        locale=locale,
        status=status,
        meta_description="about " + slug,
        og_image="/img/x.png",
        deleted_at=datetime.now(UTC) if trashed else None,
    )
    db.add(page)
    await db.commit()
    await db.refresh(page)
    return page


async def _asset(db, name, content_type, *, tenant="default"):
    asset = MediaAsset(
        tenant_id=tenant, filename=f"f-{name}", original_filename=name, content_type=content_type
    )
    db.add(asset)
    await db.commit()
    await db.refresh(asset)
    return asset


async def test_page_card_published_only(db) -> None:
    app = _app()
    ok = await _page(db, "live")
    draft = await _page(db, "wip", status=PageStatus.DRAFT)
    gone = await _page(db, "bin", trashed=True)

    card = await get_page_card(app, db, tenant_id="default", page_id=ok.id)
    assert card == PageCard(
        id=ok.id,
        title="Live",
        excerpt="about live",
        image_url="/img/x.png",
        path="/p/live",
        locale="en",
    )
    assert await get_page_card(app, db, tenant_id="default", page_id=draft.id) is None
    assert await get_page_card(app, db, tenant_id="default", page_id=gone.id) is None
    found = await search_page_cards(app, db, tenant_id="default", pattern="%l%")
    assert [c.id for c in found] == [ok.id]


async def test_page_card_path_is_locale_prefixed(db) -> None:
    locales.use(PagebuilderSettings(content_locales=("en", "de"), default_content_locale="en"))
    app = _app()
    en = await _page(db, "hello")
    de = await _page(db, "hallo", locale="de")

    assert (await get_page_card(app, db, tenant_id="default", page_id=en.id)).path == "/p/hello"
    assert (await get_page_card(app, db, tenant_id="default", page_id=de.id)).path == "/de/p/hallo"
    only_de = await search_page_cards(app, db, tenant_id="default", pattern="%", locale="de")
    assert [c.id for c in only_de] == [de.id]


async def test_other_tenant_is_none(db) -> None:
    app = _app()
    theirs = await _page(db, "theirs", tenant="other")
    await _asset(db, "theirs.png", "image/png", tenant="other")

    assert await get_page_card(app, db, tenant_id="default", page_id=theirs.id) is None
    assert await search_page_cards(app, db, tenant_id="default", pattern="%") == []
    assert await search_media_cards(app, db, tenant_id="default", pattern="%") == []


async def test_bound_other_tenant_raises(db) -> None:
    app = _app()
    page = await _page(db, "mine")
    with tenant_context("other"):
        with pytest.raises(TenantIsolationError):
            await get_page_card(app, db, tenant_id="default", page_id=page.id)
        with pytest.raises(TenantIsolationError):
            await search_media_cards(app, db, tenant_id="default", pattern="%")
    with tenant_context("default"):
        assert await get_page_card(app, db, tenant_id="default", page_id=page.id) is not None


async def test_media_cards_exclude_svg_and_non_images(db) -> None:
    app = _app()
    png = await _asset(db, "a.png", "image/png")
    await _asset(db, "b.svg", "image/svg+xml")
    await _asset(db, "c.pdf", "application/pdf")

    cards = await search_media_cards(app, db, tenant_id="default", pattern="%")
    assert cards == [
        MediaCard(
            id=png.id,
            filename="a.png",
            content_type="image/png",
            path=f"{app.state.pagebuilder.settings.media_url_prefix}/default/{png.filename}",
        )
    ]


async def test_unmounted_app_answers_nothing(db) -> None:
    app = SimpleNamespace(state=SimpleNamespace())
    page = await _page(db, "live")
    assert await get_page_card(app, db, tenant_id="default", page_id=page.id) is None
    assert await search_page_cards(app, db, tenant_id="default", pattern="%") == []
    assert await search_media_cards(app, db, tenant_id="default", pattern="%") == []


@pytest.mark.parametrize("limit", [0, 101])
async def test_limit_validated(db, limit) -> None:
    with pytest.raises(ValueError):
        await search_page_cards(_app(), db, tenant_id="default", pattern="%", limit=limit)
    with pytest.raises(ValueError):
        await search_media_cards(_app(), db, tenant_id="default", pattern="%", limit=limit)
