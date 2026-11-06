"""``content.integrations``: news and pagebuilder are optional, and guarded."""

from __future__ import annotations

import sys
from types import SimpleNamespace

import pytest
from sm_newsletter.content import integrations
from sm_newsletter.content.integrations import news, pagebuilder
from sm_newsletter.core.errors import IntegrationUnavailable

T = "default"


def _app(**mounted: object) -> SimpleNamespace:
    return SimpleNamespace(state=SimpleNamespace(**mounted))


def test_unavailable_when_not_mounted():
    app = _app()
    assert news.available(app) is False
    assert pagebuilder.available(app) is False


async def test_unavailable_when_import_blocked(monkeypatch, db):
    app = _app(news=object(), pagebuilder=object())
    assert news.available(app) is True
    assert pagebuilder.available(app) is True
    monkeypatch.setitem(sys.modules, "news.contracts.articles", None)
    monkeypatch.setitem(sys.modules, "pagebuilder.contracts.cards", None)
    assert news.available(app) is False
    assert pagebuilder.available(app) is False
    with pytest.raises(IntegrationUnavailable):
        await news.search(app, db, tenant_id=T, q="x", locale=None)
    with pytest.raises(IntegrationUnavailable):
        await pagebuilder.card(app, db, tenant_id=T, source_id=1)
    with pytest.raises(IntegrationUnavailable):
        await pagebuilder.search_media(app, db, tenant_id=T, q="x")


def test_capabilities_dict():
    assert integrations.capabilities(_app()) == {"news": False, "pagebuilder": False}
    assert integrations.capabilities(_app(news=object())) == {"news": True, "pagebuilder": False}
    both = _app(news=object(), pagebuilder=object())
    assert integrations.capabilities(both) == {"news": True, "pagebuilder": True}


async def test_page_card_maps_the_contract(monkeypatch, db):
    """The pagebuilder hit is the contract's card, renamed; an id past INTEGER
    is no page, without asking the database."""
    import pagebuilder.contracts.cards as contract

    calls: list[dict] = []

    async def fake_get(app, session, *, tenant_id, page_id):
        calls.append({"tenant_id": tenant_id, "page_id": page_id})
        return contract.PageCard(
            id=page_id,
            title="About",
            excerpt="Us",
            image_url="/i.png",
            path="/p/about",
            locale="en",
        )

    monkeypatch.setattr(contract, "get_page_card", fake_get)
    app = _app(pagebuilder=object())
    hit = await pagebuilder.card(app, db, tenant_id=T, source_id=7)
    assert hit == integrations.CardHit(
        kind="page",
        source_id=7,
        title="About",
        excerpt="Us",
        image_url="/i.png",
        url="/p/about",
        locale="en",
    )
    assert calls == [{"tenant_id": T, "page_id": 7}]
    assert await pagebuilder.card(app, db, tenant_id=T, source_id=2**31) is None
    assert len(calls) == 1
