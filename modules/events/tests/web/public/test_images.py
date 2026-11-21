"""An image is emitted only where the site's own policy lets the page load it (``img-src 'self'``):
a path on the site, or an address on the site's own origin. An off-site address is simply not
emitted: the event page, its JSON-LD, the lists, the blocks and the card contract all agree."""

from __future__ import annotations

import json
import re

import pytest
from sm_events.contracts import cards as contract
from sm_events.models import Event
from sqlalchemy import update

from tests.support.public import INERTIA, seed_public
from tests.web.public.test_public_blocks_api import UPCOMING

OFF = "https://cdn.example.net/studio.jpg"
PATH = "/media/studio.jpg"
OWN = "http://test/media/studio.jpg"  # the harness's own origin


@pytest.fixture
async def fx(public_locales_client):
    return await seed_public(public_locales_client, german=False)


async def _set(client, event, image):
    from sm_events.core.tenancy import tenant_scope

    with tenant_scope("default"):
        async with client.db_state.session_factory() as db:
            await db.execute(update(Event).where(Event.id == event.id).values(image=image))
            await db.commit()


async def _page(client, fx):
    got = await client.get(f"/events/{fx.slug(fx.one_off)}", headers=INERTIA)
    assert got.status_code == 200
    return got.json()["props"]


def _json_ld(html: str) -> dict:
    found = re.search(r"<script[^>]*application/ld\+json[^>]*>(.*?)</script>", html, re.DOTALL)
    assert found, "the page carries its JSON-LD in the head"
    data = json.loads(found.group(1))
    return data[0] if isinstance(data, list) else data


@pytest.mark.parametrize(("image", "emitted"), [(OFF, False), (PATH, True), (OWN, True)])
async def test_the_event_page_and_its_json_ld(public_locales_client, fx, image, emitted):
    await _set(public_locales_client, fx.one_off, image)
    props = await _page(public_locales_client, fx)
    assert (props["image"] is not None) is emitted
    html = (await public_locales_client.get(f"/events/{fx.slug(fx.one_off)}")).text
    ld = _json_ld(html)
    assert ("image" in ld) is emitted
    assert ("og:image" in html) is emitted
    if emitted:
        # A crawler needs an absolute address, for the JSON-LD and for og:image alike.
        absolute = image if image.startswith("http") else f"http://test{image}"
        assert ld["image"] == absolute
        assert f'content="{absolute}"' in html
    assert "cdn.example.net" not in html + str(props)


@pytest.mark.parametrize(("image", "emitted"), [(OFF, False), (PATH, True)])
async def test_the_lists_and_the_blocks(public_locales_client, fx, image, emitted):
    await _set(public_locales_client, fx.one_off, image)
    index = (await public_locales_client.get("/events/", headers=INERTIA)).json()["props"]
    items = [i for g in index["groups"] for i in g["items"]]
    block = (await public_locales_client.get(f"{UPCOMING}?count=20")).json()["items"]
    for found in (items, block):
        mine = next(i for i in found if i["title"] == fx.slug(fx.one_off).title())
        assert (mine["image"] is not None) is emitted
        assert "cdn.example.net" not in str(found)


async def test_the_card_contract_carries_only_a_site_path(public_locales_client, fx):
    async with public_locales_client.db_state.session_factory() as db:
        for image, want in ((OFF, ""), (PATH, PATH), (OWN, "")):
            await _set(public_locales_client, fx.one_off, image)
            card = await contract.get_event_card(db, tenant_id="default", event_id=fx.one_off.id)
            assert card is not None and card.image_url == want, image
            await db.rollback()
