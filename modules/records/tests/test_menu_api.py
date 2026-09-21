"""The sidebar switch over HTTP: the contract, and what a page then sees.

The app here is built with ``menus=True``, which adds the two host pieces the
sidebar needs — a ``MenuRegistry`` filled through ``register_menu_items`` and
``InertiaLayoutDataMiddleware`` — so ``menus.adminSidebar`` in a view
response's shared props is the same object a real page's ``AdminLayout``
renders. That is the assertion worth making: not that a registry holds an
item, but that a request produces one.
"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sm_records.settings import RecordsSettings

from tests.app_harness import ADMIN, ROLE_EDITOR, ROLE_VIEWER, build_app, roles, seed_type

_INERTIA = {"X-Inertia": "true", "X-Inertia-Version": "1.0"}
_TYPES = "/api/records/types"


async def _menu_client(tmp_path, refresh_seconds: int | None) -> AsyncIterator[AsyncClient]:
    """The harness client, with the menu registry wired and ``on_startup`` run.

    ``on_startup`` is what the host calls, and it is where the first sidebar
    read happens (the registry is filled at construction, before there is a
    database to ask) — so running it here is half the point.

    ``refresh_seconds`` is applied *after* it, because ``on_startup`` adopts
    the hydrated settings off the services container and would otherwise put
    the default back.
    """
    app, db_state = await build_app(tmp_path, menus=True)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.app = app  # type: ignore[attr-defined]
        client.db_state = db_state  # type: ignore[attr-defined]
        module = app.state.records_module
        await module.on_startup(app)
        if refresh_seconds is not None:
            module.settings = RecordsSettings(menu_refresh_seconds=refresh_seconds)
        yield client
    await db_state.engine.dispose()


@pytest_asyncio.fixture
async def menu_client(tmp_path) -> AsyncIterator[AsyncClient]:
    """Default refresh window, so what a test sees it had to be *told* about:
    these are the assertions about the dirty flag a type write sets."""
    async for client in _menu_client(tmp_path, None):
        yield client


@pytest_asyncio.fixture
async def worker_client(tmp_path) -> AsyncIterator[AsyncClient]:
    """``menu_refresh_seconds=0``, which is how a row this process did not
    write — a seed, or another worker's ``PUT`` — reaches the sidebar."""
    async for client in _menu_client(tmp_path, 0):
        yield client


async def _sidebar(client: AsyncClient, *names: str) -> list[dict]:
    resp = await client.get("/admin/records/", headers={**roles(*names), **_INERTIA})
    assert resp.status_code == 200, resp.text
    return resp.json()["props"]["menus"]["adminSidebar"]


async def test_create_carries_show_in_menu_and_defaults_to_off(client):
    off = await client.post(_TYPES, json={"key": "quiet", "label": "Quiet"}, headers=roles(ADMIN))
    assert off.status_code == 201
    assert off.json()["show_in_menu"] is False

    on = await client.post(
        _TYPES,
        json={"key": "company", "label": "Company", "show_in_menu": True},
        headers=roles(ADMIN),
    )
    assert on.status_code == 201
    assert on.json()["show_in_menu"] is True

    read = await client.get(f"{_TYPES}/company", headers=roles(ADMIN))
    assert read.json()["show_in_menu"] is True


async def test_update_toggles_it_without_touching_the_schema(client):
    created = (
        await client.post(
            _TYPES,
            json={"key": "company", "label": "Company", "show_in_menu": True},
            headers=roles(ADMIN),
        )
    ).json()

    updated = await client.put(
        f"{_TYPES}/company",
        json={"expected_version": created["version"], "show_in_menu": False},
        headers=roles(ADMIN),
    )
    assert updated.status_code == 200
    body = updated.json()
    assert body["show_in_menu"] is False
    # A navigation flag, not a schema change: the version moves, the schema
    # version does not, and nothing is queued for reindexing.
    assert body["version"] == created["version"] + 1
    assert body["schema_version"] == created["schema_version"]
    assert body["reindex_pending"] == {}


async def test_export_and_import_round_trip_the_flag(client):
    await client.post(
        _TYPES,
        json={"key": "company", "label": "Company", "show_in_menu": True},
        headers=roles(ADMIN),
    )

    definition = (await client.get(f"{_TYPES}/company/export", headers=roles(ADMIN))).json()
    assert definition["show_in_menu"] is True

    definition["key"] = "firm"
    imported = await client.post(f"{_TYPES}/import", json=definition, headers=roles(ADMIN))
    assert imported.status_code == 200
    assert imported.json()["show_in_menu"] is True


async def test_import_in_update_mode_can_turn_it_off(client):
    created = (
        await client.post(
            _TYPES,
            json={"key": "company", "label": "Company", "show_in_menu": True},
            headers=roles(ADMIN),
        )
    ).json()
    definition = (await client.get(f"{_TYPES}/company/export", headers=roles(ADMIN))).json()
    definition |= {"mode": "update", "expected_version": created["version"], "show_in_menu": False}

    imported = await client.post(f"{_TYPES}/import", json=definition, headers=roles(ADMIN))

    assert imported.status_code == 200
    assert imported.json()["show_in_menu"] is False


async def test_a_type_that_asked_for_it_is_in_the_shared_props(worker_client):
    await seed_type(
        worker_client.db_state,
        "company",
        [],
        label_plural="Companies",
        icon="building",
        show_in_menu=True,
    )
    await seed_type(worker_client.db_state, "quiet", [], label_plural="Quiets")

    items = await _sidebar(worker_client, ADMIN)

    labels = [item["label"] for item in items]
    assert labels == ["Records", "Companies"]
    entry = items[1]
    assert entry["url"] == "/admin/records/company"
    assert entry["icon"] == "building"
    assert entry["group"] == "Records"
    assert "Quiets" not in labels


async def test_allowed_roles_narrow_who_sees_the_entry(worker_client):
    await seed_type(
        worker_client.db_state,
        "company",
        [],
        label_plural="Companies",
        show_in_menu=True,
        allowed_roles=[ROLE_EDITOR],
    )

    assert "Companies" in [item["label"] for item in await _sidebar(worker_client, ROLE_EDITOR)]
    # The same narrowing ``role_blocked`` applies to the page behind the link —
    # including for an admin, since neither has a wildcard.
    assert "Companies" not in [item["label"] for item in await _sidebar(worker_client, ROLE_VIEWER)]
    assert "Companies" not in [item["label"] for item in await _sidebar(worker_client, ADMIN)]


async def test_toggling_the_switch_shows_up_on_the_next_page_request(menu_client):
    created = (
        await menu_client.post(
            _TYPES,
            json={"key": "company", "label": "Company", "label_plural": "Companies"},
            headers=roles(ADMIN),
        )
    ).json()
    assert [item["label"] for item in await _sidebar(menu_client, ADMIN)] == ["Records"]

    updated = await menu_client.put(
        f"{_TYPES}/company",
        json={"expected_version": created["version"], "show_in_menu": True},
        headers=roles(ADMIN),
    )
    assert updated.status_code == 200

    # No waiting for ``menu_refresh_seconds``: the write marked this process
    # dirty, so the next request that renders a sidebar re-reads.
    assert [item["label"] for item in await _sidebar(menu_client, ADMIN)] == [
        "Records",
        "Companies",
    ]


async def test_deleting_a_shown_type_removes_its_entry(menu_client):
    created = (
        await menu_client.post(
            _TYPES,
            json={
                "key": "company",
                "label": "Company",
                "label_plural": "Companies",
                "show_in_menu": True,
            },
            headers=roles(ADMIN),
        )
    ).json()
    assert created["show_in_menu"] is True
    assert "Companies" in [item["label"] for item in await _sidebar(menu_client, ADMIN)]

    deleted = await menu_client.delete(
        f"{_TYPES}/company?confirm_record_count=0", headers=roles(ADMIN)
    )
    assert deleted.status_code == 204

    assert [item["label"] for item in await _sidebar(menu_client, ADMIN)] == ["Records"]


async def test_renaming_the_plural_relabels_the_entry(menu_client):
    created = (
        await menu_client.post(
            _TYPES,
            json={
                "key": "company",
                "label": "Company",
                "label_plural": "Companies",
                "show_in_menu": True,
            },
            headers=roles(ADMIN),
        )
    ).json()
    assert "Companies" in [item["label"] for item in await _sidebar(menu_client, ADMIN)]

    await menu_client.put(
        f"{_TYPES}/company",
        json={"expected_version": created["version"], "label_plural": "Firms"},
        headers=roles(ADMIN),
    )

    labels = [item["label"] for item in await _sidebar(menu_client, ADMIN)]
    assert labels == ["Records", "Firms"]
