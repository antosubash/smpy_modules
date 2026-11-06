"""The admin screens' props, their guards, and the sidebar entries."""

from __future__ import annotations

import json
from pathlib import Path

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sm_newsletter.campaigns.test_send import MAX_TEST_RECIPIENTS
from sm_newsletter.core import constants
from sm_newsletter.web.endpoints.menu import menu_items

from tests.support.app import build_app
from tests.support.records_seed import restrict_list, seed_list

API = constants.ROUTE_PREFIX_API
VIEW = constants.VIEW_PREFIX
READ = {"x-perms": constants.PERM_VIEW}
EDIT = {"x-perms": f"{constants.PERM_VIEW},{constants.PERM_EDIT}"}
ALL = {"x-perms": ",".join((*constants.PERMISSIONS, constants.PERM_SETTINGS_EDIT))}
LOCALES = Path(__file__).parents[2] / "sm_newsletter" / "locales"


@pytest_asyncio.fixture
async def built():
    app, state = await build_app()
    await seed_list(state, "default")
    yield app, state
    await state.engine.dispose()


@pytest_asyncio.fixture
async def client(built):
    app, _ = built
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as c:
        yield c


async def _campaign(client) -> int:
    res = await client.post(
        f"{API}/campaigns",
        json={"name": "n", "list_type_key": "news", "subject": "s"},
        headers=EDIT,
    )
    return res.json()["id"]


async def test_campaigns_view_props(client):
    res = await client.get(f"{VIEW}/", headers=READ)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["component"] == constants._PAGE_CAMPAIGNS
    assert (body["props"]["can_edit"], body["props"]["can_send"]) == (False, False)
    full = (await client.get(f"{VIEW}/", headers=ALL)).json()["props"]
    assert (full["can_edit"], full["can_send"]) == (True, True)
    assert full["tenant"] == "default"


async def test_editor_props(client, built):
    cid = await _campaign(client)
    res = await client.get(f"{VIEW}/campaigns/{cid}", headers=EDIT)
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["component"] == constants._PAGE_EDITOR
    props = body["props"]
    assert props["campaign_id"] == cid
    assert (props["can_edit"], props["can_send"]) == (True, False)
    # Neither news nor pagebuilder is mounted on this app.
    assert props["capabilities"] == {"news": False, "pagebuilder": False}
    assert props["max_test_recipients"] == MAX_TEST_RECIPIENTS == 5
    assert props["public_base_url_set"] is False
    app, _ = built
    app.state.sm.settings.public_base_url = "https://example.com"
    again = (await client.get(f"{VIEW}/campaigns/{cid}", headers=EDIT)).json()["props"]
    assert again["public_base_url_set"] is True


async def test_editor_unknown_campaign_404(client):
    res = await client.get(f"{VIEW}/campaigns/9999", headers=READ)
    assert res.status_code == 404


async def test_editor_unreadable_list_404(client, built):
    _, state = built
    cid = await _campaign(client)
    await restrict_list(state, "default", "news", ["nobody"])
    res = await client.get(f"{VIEW}/campaigns/{cid}", headers=READ)
    assert res.status_code == 404


async def test_views_need_view_permission(client):
    cid = await _campaign(client)
    for path in ("/", f"/campaigns/{cid}"):
        assert (await client.get(f"{VIEW}{path}", headers={"x-perms": ""})).status_code == 403


async def test_settings_view_needs_manage(client):
    assert (await client.get(f"{VIEW}/settings", headers=READ)).status_code == 403
    manage = {"x-perms": constants.PERM_MANAGE}
    res = await client.get(f"{VIEW}/settings", headers=manage)
    assert res.status_code == 200
    assert res.json()["component"] == constants._PAGE_SETTINGS
    assert res.json()["props"]["can_write"] is False
    full = (await client.get(f"{VIEW}/settings", headers=ALL)).json()["props"]
    assert full["can_write"] is True


def _has(tree: dict, dotted: str) -> bool:
    node = tree
    for part in dotted.split("."):
        if not isinstance(node, dict) or part not in node:
            return False
        node = node[part]
    return isinstance(node, str)


def test_menu_items():
    items = menu_items()
    assert [(i.label, i.icon, i.order, i.permissions) for i in items] == [
        ("Campaigns", "mail", 300, [constants.PERM_VIEW]),
        ("Settings", "settings", 390, [constants.PERM_MANAGE]),
    ]
    assert [i.url for i in items] == [f"{VIEW}/", constants.SETTINGS_URL]
    for lang in ("en", "de"):
        # The catalogue's namespace prefix is not part of the file's key tree.
        tree = json.loads((LOCALES / f"{lang}.json").read_text())
        for item in items:
            assert item.group_key == constants.MENU_GROUP_KEY
            for key in (item.label_key, item.group_key):
                assert _has(tree, key.removeprefix(f"{constants.LOCALE_NAMESPACE}."))
