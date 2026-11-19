"""``content.integrations``: news and pagebuilder are optional, and guarded."""

from __future__ import annotations

import subprocess
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from sm_newsletter.content import integrations
from sm_newsletter.content.integrations import events, news, pagebuilder
from sm_newsletter.core.errors import IntegrationUnavailable

T = "default"


def _app(**mounted: object) -> SimpleNamespace:
    return SimpleNamespace(state=SimpleNamespace(**mounted))


def test_unavailable_when_not_mounted():
    app = _app()
    assert news.available(app) is False
    assert pagebuilder.available(app) is False
    assert events.available(app) is False


async def test_unavailable_when_import_blocked(monkeypatch, db):
    app = _app(news=object(), pagebuilder=object(), sm_events=object())
    assert news.available(app) is True
    assert pagebuilder.available(app) is True
    assert events.available(app) is True
    monkeypatch.setitem(sys.modules, "news.contracts.articles", None)
    monkeypatch.setitem(sys.modules, "pagebuilder.contracts.cards", None)
    monkeypatch.setitem(sys.modules, "sm_events.contracts.cards", None)
    assert news.available(app) is False
    assert pagebuilder.available(app) is False
    assert events.available(app) is False
    with pytest.raises(IntegrationUnavailable):
        await events.search(app, db, tenant_id=T, q="x", locale=None)
    with pytest.raises(IntegrationUnavailable):
        await events.card(app, db, tenant_id=T, source_id=str(uuid.uuid4()))
    with pytest.raises(IntegrationUnavailable):
        await news.search(app, db, tenant_id=T, q="x", locale=None)
    with pytest.raises(IntegrationUnavailable):
        await pagebuilder.card(app, db, tenant_id=T, source_id=1)
    with pytest.raises(IntegrationUnavailable):
        await pagebuilder.search_media(app, db, tenant_id=T, q="x")


def test_capabilities_dict():
    none = {"news": False, "pagebuilder": False, "events": False}
    assert integrations.capabilities(_app()) == none
    assert integrations.capabilities(_app(news=object())) == none | {"news": True}
    everything = _app(news=object(), pagebuilder=object(), sm_events=object())
    assert integrations.capabilities(everything) == dict.fromkeys(none, True)


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


async def test_event_card_maps_the_contract(monkeypatch, db):
    """The event hit is the contract's card, renamed field by field; an id that is not a UUID is
    no event, without asking the contract."""
    import sm_events.contracts.cards as contract

    calls: list[dict] = []
    event_id = uuid.uuid4()
    start = datetime(2026, 7, 1, 8, tzinfo=UTC)

    async def fake_get(session, *, tenant_id, event_id, locale=None):
        calls.append({"tenant_id": tenant_id, "event_id": event_id, "locale": locale})
        return contract.EventCard(
            id=event_id,
            title="Open day",
            summary="Come by",
            starts_at=start,
            ends_at=start.replace(hour=9),
            all_day=False,
            start_date=None,
            end_date=None,
            timezone="Europe/Vienna",
            attendance_mode="hybrid",
            venue_name="Hall 1",
            address="Main St 2",
            image_url="https://cdn.example.com/a.png",
            path="/events/open-day?date=2026-07-01",
            ics_path="/events/open-day.ics",
            locale="en",
            cancelled=True,
        )

    monkeypatch.setattr(contract, "get_event_card", fake_get)
    app = _app(sm_events=object())
    hit = await events.card(app, db, tenant_id=T, source_id=str(event_id).upper())
    assert hit == integrations.EventHit(
        kind="event",
        source_id=str(event_id),
        title="Open day",
        excerpt="Come by",
        image_url="https://cdn.example.com/a.png",
        url="/events/open-day?date=2026-07-01",
        ics_url="/events/open-day.ics",
        locale="en",
        starts_at=start,
        ends_at=start.replace(hour=9),
        all_day=False,
        start_date=None,
        end_date=None,
        timezone="Europe/Vienna",
        attendance_mode="hybrid",
        place="Hall 1, Main St 2",
        cancelled=True,
    )
    assert calls == [{"tenant_id": T, "event_id": event_id, "locale": None}]
    assert await events.card(app, db, tenant_id=T, source_id="nope") is None
    assert len(calls) == 1


async def test_event_search_passes_escaped_pattern_and_upcoming(monkeypatch, db):
    import sm_events.contracts.cards as contract

    seen: dict = {}

    async def fake_search(session, **kwargs):
        seen.update(kwargs)
        return []

    monkeypatch.setattr(contract, "search_events", fake_search)
    assert (
        await events.search(_app(sm_events=object()), db, tenant_id=T, q=" 50%_x ", locale="de")
        == []
    )
    assert seen == {
        "tenant_id": T,
        "pattern": "%50\\%\\_x%",
        "locale": "de",
        "limit": integrations.hits.SEARCH_LIMIT,
        "upcoming_only": True,
    }


def test_newsletter_imports_without_events():
    """With ``sm_events`` unimportable the module, the cards API and the cards service all load."""
    code = (
        "import sys; sys.modules['sm_events'] = None\n"
        "import sm_newsletter.module, sm_newsletter.web.endpoints.cards_api, "
        "sm_newsletter.content.cards\n"
        "from sm_newsletter.content import integrations\n"
        "assert integrations.events.available(type('A', (), {'state': object()})()) is False\n"
    )
    done = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False)
    assert done.returncode == 0, done.stderr


def test_only_integrations_import_sm_events():
    root = Path(integrations.__file__).resolve().parents[2]
    guarded = root / "content" / "integrations"
    offenders = [
        str(path.relative_to(root))
        for path in root.rglob("*.py")
        if guarded not in path.parents and "sm_events" in path.read_text()
    ]
    assert offenders == []
