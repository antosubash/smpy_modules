"""``GET …/collections/{id}/points``, its public twin and the ``points`` contract (Task 26).

GeoJSON with only ``id``, ``captured_at`` and ``group_id`` per point, filtered
in SQL by the access policy and the redaction gate: no point for an image the
caller cannot see, and none for an image whose display mutator has not settled.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sm_images.contracts import points as points_contract
from sm_images.core import constants
from sm_images.core.tenancy import DEFAULT_TENANT
from sm_images.models import Group, StepRun, Visibility
from sm_images.models.enums import StepStatus

from tests.support.access import OWNER, STRANGER, collection, headers, image, principal
from tests.support.pipeline import Blur, use_steps

WHEN = datetime(2026, 5, 1, 12, 0, tzinfo=UTC)


async def _seed(client, visibility=Visibility.PRIVATE, places=None, **coll_kw):
    coll = collection(f"m-{uuid.uuid4().hex[:8]}", visibility, OWNER, **coll_kw)
    places = places or {
        "vienna": (48.2, 16.37),
        "paris": (48.85, 2.35),
        "nowhere": None,
    }
    async with client.db_state.session_factory() as s:
        s.add(coll)
        await s.flush()
        site = Group(collection_id=coll.id, key="site-1")
        s.add(site)
        await s.flush()
        rows = {}
        for name, where in places.items():
            lat, lng = where if where else (None, None)
            rows[name] = image(
                coll,
                f"{name}-secret-name.jpg",
                lat=lat,
                lng=lng,
                captured_at=WHEN,
                properties={"note": "secret-prop"},
                group_id=site.id if name == "vienna" else None,
            )
        s.add_all(rows.values())
        await s.commit()
    return coll, {k: v.id for k, v in rows.items()}, site.id


def _url(coll, query: str = "") -> str:
    return f"/api/images/collections/{coll.id}/points{query}"


def _public(coll, query: str = "") -> str:
    return f"/api/images/public/c/{coll.slug}/points{query}"


def _ids(body) -> set[str]:
    return {f["properties"]["id"] for f in body["features"]}


async def test_points_hold_only_id_captured_at_and_group(client):
    coll, ids, site = await _seed(client)
    got = await client.get(_url(coll), headers=headers(OWNER))
    assert got.status_code == 200, got.text
    body = got.json()
    assert body["type"] == "FeatureCollection"
    assert _ids(body) == {str(ids["vienna"]), str(ids["paris"])}
    for feature in body["features"]:
        assert set(feature) == {"type", "geometry", "properties"}
        assert set(feature["properties"]) == {"id", "captured_at", "group_id"}
    vienna = next(f for f in body["features"] if f["properties"]["id"] == str(ids["vienna"]))
    assert vienna["geometry"] == {"type": "Point", "coordinates": [16.37, 48.2]}
    assert vienna["properties"]["group_id"] == str(site)
    assert vienna["properties"]["captured_at"].startswith("2026-05-01T12:00:00")
    assert "secret-name" not in got.text and "secret-prop" not in got.text
    assert body["next_cursor"] is None
    assert got.headers["cache-control"] == "private, no-cache"


async def test_bbox_filter(client):
    coll, ids, _ = await _seed(client)
    got = await client.get(_url(coll, "?bbox=16,48,17,49"), headers=headers(OWNER))
    assert got.status_code == 200, got.text
    assert _ids(got.json()) == {str(ids["vienna"])}


async def test_bbox_across_the_antimeridian(client):
    places = {"east": (0.0, 179.5), "west": (1.0, -179.5), "middle": (0.0, 0.0)}
    coll, ids, _ = await _seed(client, places=places)
    got = await client.get(_url(coll, "?bbox=179,-10,-179,10"), headers=headers(OWNER))
    assert _ids(got.json()) == {str(ids["east"]), str(ids["west"])}


@pytest.mark.parametrize(
    "bbox",
    [
        "a,b,c,d",
        "1,2,3",
        "0,0,200,1",
        "0,-91,1,1",
        "0,10,1,5",
        "nan,0,1,1",
        "0,0,inf,1",
        "1,2,3,4,5",
    ],
)
async def test_bad_bbox_is_422(client, bbox):
    coll, _, _ = await _seed(client)
    got = await client.get(_url(coll, f"?bbox={bbox}"), headers=headers(OWNER))
    assert got.status_code == 422, got.text


async def test_limit_is_clamped_and_a_cursor_pages_past_it(client, monkeypatch):
    monkeypatch.setattr(constants, "POINTS_LIMIT_MAX", 2)
    places = {f"p{i}": (10.0 + i, 20.0 + i) for i in range(5)}
    coll, ids, _ = await _seed(client, places=places)
    seen: list[str] = []
    cursor = None
    for _ in range(5):
        query = "?limit=100000" + (f"&cursor={cursor}" if cursor else "")
        body = (await client.get(_url(coll, query), headers=headers(OWNER))).json()
        assert len(body["features"]) <= 2
        seen += [f["properties"]["id"] for f in body["features"]]
        cursor = body["next_cursor"]
        if cursor is None:
            break
    assert sorted(seen) == sorted(str(i) for i in ids.values())
    assert len(seen) == len(set(seen))


async def test_a_private_collections_points_are_hidden(client):
    coll, _, _ = await _seed(client)
    got = await client.get(_url(coll), headers=headers(STRANGER))
    assert got.status_code == 404
    assert "secret" not in got.text and str(coll.id) not in got.text
    for who in (None, STRANGER, OWNER):
        twin = await client.get(_public(coll), headers=headers(who))
        assert twin.status_code == 404
        assert twin.headers["cache-control"] == "no-store"


async def test_an_internal_collection_has_no_public_points(client):
    coll, _, _ = await _seed(client, Visibility.INTERNAL)
    assert (await client.get(_public(coll))).status_code == 404
    got = await client.get(_url(coll), headers=headers(STRANGER))
    assert got.status_code == 200  # any signed-in member sees an internal one


@pytest.mark.unbound_tenant
async def test_public_twin_serves_a_public_collection(client):
    from sm_images.core.tenancy import tenant_scope

    with tenant_scope(DEFAULT_TENANT):
        coll, ids, _ = await _seed(client, Visibility.PUBLIC)
    got = await client.get(_public(coll, "?bbox=0,40,20,50"))
    assert got.status_code == 200, got.text
    assert _ids(got.json()) == {str(ids["vienna"]), str(ids["paris"])}
    assert got.headers["cache-control"] == "public, no-cache"
    assert "secret" not in got.text


@pytest.fixture
def blur_installed():
    use_steps(Blur())
    yield
    use_steps()


async def test_points_wait_for_the_redaction_gate(client, blur_installed):
    places = {"settled": (1.0, 1.0), "pending": (2.0, 2.0), "redacted": (3.0, 3.0)}
    coll, ids, _ = await _seed(client, places=places, pipeline_config={"steps": {"acme.blur": {}}})
    async with client.db_state.session_factory() as s:
        s.add(
            StepRun(
                image_id=ids["settled"],
                step="acme.blur",
                status=StepStatus.COMPLETED,
                step_version=1,
            )
        )
        s.add(
            StepRun(
                image_id=ids["pending"],
                step="acme.blur",
                status=StepStatus.RUNNING,
                step_version=1,
            )
        )
        await s.commit()
    from sm_images.models import Image
    from sqlalchemy import update

    async with client.db_state.session_factory() as s:
        await s.execute(
            update(Image)
            .where(Image.id == ids["redacted"])
            .values(display_key="k/d", display_step="acme.blur", display_generation=1)
        )
        await s.commit()
    got = await client.get(_url(coll), headers=headers(OWNER))
    assert _ids(got.json()) == {str(ids["settled"]), str(ids["redacted"])}


async def test_an_uninstalled_mutator_hides_every_point(client, blur_installed):
    coll, _, _ = await _seed(client, pipeline_config={"steps": {"gone.step": {}}})
    got = await client.get(_url(coll), headers=headers(OWNER))
    assert got.json()["features"] == []


async def test_the_points_contract(client):
    coll, ids, _ = await _seed(client)
    async with client.db_state.session_factory() as db:
        mine = await points_contract(DEFAULT_TENANT, coll.id, principal(OWNER), db=db)
        assert _ids(mine) == {str(ids["vienna"]), str(ids["paris"])}
        boxed = await points_contract(
            DEFAULT_TENANT, coll.id, principal(OWNER), bbox=(16, 48, 17, 49), db=db
        )
        assert _ids(boxed) == {str(ids["vienna"])}
        assert await points_contract(DEFAULT_TENANT, coll.id, principal(STRANGER), db=db) is None
