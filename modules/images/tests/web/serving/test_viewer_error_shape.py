# ruff: noqa: F811
"""One renderer for withheld and absent (Task 27 fix 4).

On the authenticated routes an unknown id fails in the framework's
``RequiresResource`` (``HTTPException``), which the host renders as JSON, HTML
or an Inertia page by negotiation. A withheld image or pending-only group must
fail the same way, byte for byte, in every negotiation.
"""

from __future__ import annotations

import uuid

import pytest
from sm_images.core.tenancy import DEFAULT_TENANT, tenant_scope
from sm_images.models import Collection, Group, Image
from sqlalchemy import event, select, update
from sqlalchemy.engine import Engine

from tests.support.access import OWNER, STRANGER, headers, image
from tests.web.collections.test_viewer_stats import blur_installed, seeded  # noqa: F401

NEGOTIATIONS = {
    "plain": {},
    "html": {"Accept": "text/html"},
    "inertia": {"X-Inertia": "true", "X-Inertia-Version": "1.0"},
}
IGNORED = {"date", "x-request-id", "x-correlation-id", "server-timing"}


def _shape(response):
    return (
        response.status_code,
        response.text,
        {k: v for k, v in response.headers.items() if k not in IGNORED},
    )


async def _ids(client, seeded):
    with tenant_scope(DEFAULT_TENANT):
        async with client.db_state.session_factory() as s:
            pending = (
                await s.execute(select(Image.id).where(Image.filename == "pending.jpg"))
            ).scalar_one()
            group = Group(collection_id=seeded.id, key="sensitive-site-123")
            s.add(group)
            await s.flush()
            await s.execute(update(Image).where(Image.id == pending).values(group_id=group.id))
            await s.commit()
            return pending, group.id


ROUTES = [
    ("get", "/api/images/images/{i}/original"),
    ("head", "/api/images/images/{i}/original"),
    ("get", "/api/images/images/{i}/display"),
    ("head", "/api/images/images/{i}/display"),
    ("get", "/api/images/images/{i}/r/small"),
    ("head", "/api/images/images/{i}/r/small"),
    ("get", "/api/images/images/{i}"),
    ("get", "/admin/images/images/{i}"),
    ("get", "/api/images/groups/{g}"),
]


@pytest.mark.parametrize("negotiation", sorted(NEGOTIATIONS))
@pytest.mark.parametrize(("method", "route"), ROUTES)
async def test_withheld_and_absent_fail_identically(client, seeded, method, route, negotiation):
    pending, group = await _ids(client, seeded)
    extra = {**headers(STRANGER), **NEGOTIATIONS[negotiation]}
    call = getattr(client, method)
    withheld = await call(route.format(i=pending, g=group), headers=extra)
    absent = await call(route.format(i=uuid.uuid4(), g=uuid.uuid4()), headers=extra)
    assert withheld.status_code == 404
    assert _shape(withheld) == _shape(absent)


async def test_group_page_query_count_is_constant_in_group_count(client, seeded):
    async def groups_with(n: int) -> int:
        with tenant_scope(DEFAULT_TENANT):
            async with client.db_state.session_factory() as s:
                have = len(
                    (await s.execute(select(Group.id).where(Group.collection_id == seeded.id)))
                    .scalars()
                    .all()
                )
                coll = (
                    await s.execute(select(Collection).where(Collection.id == seeded.id))
                ).scalar_one()
                for k in range(have, n):
                    g = Group(collection_id=seeded.id, key=f"g{k}")
                    s.add(g)
                    await s.flush()
                    s.add(image(coll, f"m{k}.jpg", group_id=g.id))
                await s.flush()
                await s.commit()
        seen: list[str] = []

        def spy(conn, cursor, statement, *a):
            seen.append(statement)

        event.listen(Engine, "before_cursor_execute", spy)
        try:
            got = await client.get(
                f"/api/images/collections/{seeded.id}/groups", headers=headers(OWNER)
            )
        finally:
            event.remove(Engine, "before_cursor_execute", spy)
        assert got.status_code == 200 and len(got.json()["items"]) == n
        return len(seen)

    few = await groups_with(2)
    many = await groups_with(12)
    assert many == few, (few, many)
