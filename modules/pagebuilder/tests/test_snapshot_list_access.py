"""Only a publisher or an approver reads the snapshot list.

The list carries every snapshot's note, creator and manifest (section counts
included), so ``GET /pagebuilder/content`` and ``GET /api/pagebuilder/snapshots``
take the gate ``GET /imports/pending`` already had. Both say which controls the
reader may use, so an approver sees the list and the pending restore without
being offered Restore, Delete, Upload or Take.
"""

from __future__ import annotations

from typing import Any

import pytest
from conftest import _build_app, _client_for
from pagebuilder.permissions import PERM_APPROVE, PERM_EDIT, PERM_PUBLISH

pytestmark = pytest.mark.asyncio

_SNAPSHOTS = "/api/pagebuilder/snapshots"
_CONTENT = "/pagebuilder/content"
_INERTIA = {"X-Inertia": "true"}
_ROLE = "someone"


async def _client(tmp_path, grants: list[str], *, seed: bool = False):
    """A client whose one role holds *grants*; ``seed`` stages a snapshot and a restore first.

    Seeding runs under a publish grant that is then replaced by *grants*, so
    an approve-only reader has something on the list to (not) act on.
    """
    initial = [PERM_EDIT, PERM_PUBLISH] if seed else grants
    app, cleanup = await _build_app(
        tmp_path,
        requires_auth=True,
        csrf_protect=False,
        inject_user=True,
        user_roles=(_ROLE,),
        role_map={_ROLE: initial},
    )
    try:
        async with _client_for(app) as client:
            if seed:
                taken = await client.post(_SNAPSHOTS, json={"note": "before the redesign"})
                assert taken.status_code == 201, taken.text
                staged = await client.post(f"{_SNAPSHOTS}/{taken.json()['id']}/restore")
                assert staged.status_code == 201, staged.text
                _regrant(app, grants)
            yield client
    finally:
        await cleanup()


def _regrant(app: Any, grants: list[str]) -> None:
    registry = app.state.sm.permissions
    registry._role_map[_ROLE] = set(grants)
    registry._invalidate()


@pytest.mark.parametrize("grants", [[], [PERM_EDIT]])
async def test_a_reader_without_publish_or_approve_is_refused(tmp_path, grants):
    async for client in _client(tmp_path, grants):
        api = await client.get(_SNAPSHOTS)
        assert api.status_code == 403
        assert api.json()["detail"] == "Permission required: pagebuilder.publish"

        view = await client.get(_CONTENT, headers=_INERTIA)
        assert view.status_code == 403
        assert "snapshots" not in view.text


async def test_a_publisher_reads_the_list_with_publish_controls(tmp_path):
    async for client in _client(tmp_path, [PERM_EDIT, PERM_PUBLISH]):
        await client.post(_SNAPSHOTS, json={"note": "first"})

        api = await client.get(_SNAPSHOTS)
        assert api.status_code == 200
        assert [s["note"] for s in api.json()["items"]] == ["first"]
        assert api.json()["capabilities"] == {"publish": True, "approve": False}

        view = await client.get(_CONTENT, headers=_INERTIA)
        assert view.status_code == 200
        assert view.json()["props"]["capabilities"] == {"publish": True, "approve": False}


async def test_an_approver_reads_the_list_and_the_pending_restore_only(tmp_path):
    async for client in _client(tmp_path, [PERM_APPROVE], seed=True):
        api = await client.get(_SNAPSHOTS)
        assert api.status_code == 200
        assert [s["note"] for s in api.json()["items"]] == ["before the redesign"]
        assert api.json()["capabilities"] == {"publish": False, "approve": True}

        props = (await client.get(_CONTENT, headers=_INERTIA)).json()["props"]
        assert props["capabilities"] == {"publish": False, "approve": True}
        assert props["pending"]["status"] == "pending"

        # The gate it was shown no controls for still holds server-side.
        assert (await client.post(_SNAPSHOTS, json={})).status_code == 403


async def test_an_admin_holds_both_capabilities(authed_client):
    response = await authed_client.get(_SNAPSHOTS)
    assert response.json()["capabilities"] == {"publish": True, "approve": True}


@pytest.mark.parametrize(
    ("grants", "expected"),
    [
        ([PERM_EDIT, PERM_PUBLISH], {"publish": True, "approve": False}),
        ([PERM_APPROVE], {"publish": False, "approve": True}),
    ],
)
async def test_the_review_screen_says_who_may_decide(tmp_path, grants, expected):
    async for client in _client(tmp_path, grants, seed=True):
        props = (await client.get(f"{_CONTENT}/review", headers=_INERTIA)).json()["props"]
        assert props["capabilities"] == expected
        assert props["pending"]["status"] == "pending"
