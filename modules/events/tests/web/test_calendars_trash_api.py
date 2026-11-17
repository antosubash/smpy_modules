"""A trashed calendar answers 404 to everyone but its owner and a manager."""

from __future__ import annotations

import pytest

from tests.support.access import grant
from tests.support.calendars import BASE, MANAGER, OWNER, SE, SV, VIEWER, make

NOT_FOUND = (404, {"detail": "Not found", "code": "not_found"})


@pytest.mark.parametrize("visibility", ["private", "internal", "public"])
async def test_trashed_calendar_is_404_for_everyone_but_owner_and_manager(client, visibility):
    """Same answer as an id that never existed, for a stranger and for view and
    edit share holders, on every route."""
    cid = (await make(client, visibility=visibility))["id"]
    await grant(client, cid, "sv", "view")
    await grant(client, cid, "se", "edit")
    assert (await client.delete(f"{BASE}/{cid}", headers=OWNER)).status_code == 204
    missing = "00000000-0000-4000-8000-000000000000"
    for who in (VIEWER, SV, SE):
        for target in (cid, missing):
            url = f"{BASE}/{target}"
            for call in (
                client.get(url, headers=who),
                client.patch(url, json={"name": "x"}, headers=who),
                client.put(f"{url}/visibility", json={"visibility": "public"}, headers=who),
                client.delete(url, headers=who),
                client.post(f"{url}/restore", headers=who),
            ):
                got = await call
                assert (got.status_code, got.json()) == NOT_FOUND, (who, target, got.text)
    # Owner-transfer is manager-only: the permission check answers first, and
    # identically for a trashed and a missing calendar.
    for who in (VIEWER, SV, SE):
        answers = {
            (await client.put(f"{BASE}/{t}/owner", json={"owner_id": "n"}, headers=who)).status_code
            for t in (cid, missing)
        }
        assert answers == {403}
    # The owner and a manager still restore it.
    assert (await client.post(f"{BASE}/{cid}/restore", headers=SE)).status_code == 404
    restored = await client.post(f"{BASE}/{cid}/restore", headers=OWNER)
    assert (restored.status_code, restored.json()["deleted_at"]) == (200, None)


async def test_trashed_calendar_routes_for_owner_and_manager(client):
    cid = (await make(client))["id"]
    url = f"{BASE}/{cid}"
    assert (await client.delete(url, headers=OWNER)).status_code == 204
    # Trashed rows are read through the trash list, not the live routes.
    assert (await client.get(url, headers=OWNER)).status_code == 404
    assert (await client.patch(url, json={"name": "x"}, headers=OWNER)).status_code == 404
    assert (await client.post(f"{url}/restore", headers=MANAGER)).status_code == 200
