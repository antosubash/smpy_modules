"""Phase 4 review, the provider extension point and the anonymous surface.

Each test failed before its fix. Two subjects:

* a provider projects rows — it does not get to claim keys nothing can read,
  write the wrong kind under one, or invent references (design §7.6 sells it
  as *additive projection*, and §7.7's argument is that index bugs produce
  wrong answers rather than slow ones);
* the anonymous read grammar may only reach what the anonymous shape shows,
  and the prefix that shape is served under may not swallow the admin API.

The companion file ``test_review_fixes_round4.py`` holds the schema and
expansion halves of the same review.
"""

from __future__ import annotations

import logging
import warnings

import pytest
from simple_module_core.public_routes import PublicRouteRegistry
from sm_records.index import IndexKind, VirtualField, register_index_provider
from sm_records.index import providers as registry
from sm_records.models import IndexRef, IndexText
from sm_records.settings import RecordsSettings
from sm_records.settings_checks import check_public_route_prefix
from sqlalchemy import func, select

from tests.app_harness import ADMIN, roles
from tests.relation_helpers import field, make_record, make_type
from tests.test_review_fixes_round4 import API, indexed, yielding

# ---------------------------------------------------------------------------
# m5 / m6 / m7 — what a provider may claim, and what it may write
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "key", ["status", "position", "_orphaned", "id", "", "Not A Key", "x" * 65]
)
def test_register_refuses_a_virtual_key_nothing_could_read(key):
    with pytest.raises(ValueError, match="virtual field"):
        registry.register(yielding(), fields=[VirtualField(key, IndexKind.TEXT)])
    assert key not in registry.virtual_fields()


async def test_a_kind_that_disagrees_with_the_declaration_is_dropped_and_logged(
    client, records_app, caplog
):
    _app, db_state = records_app
    await make_type(client, "product", [field("name", "text")])
    register_index_provider(
        yielding((IndexKind.TEXT, "price_bucket", "100")),
        fields=[VirtualField("price_bucket", IndexKind.NUMBER)],
    )
    with caplog.at_level(logging.WARNING):
        for name in ("one", "two"):
            await make_record(client, "product", {"name": name})

    async with db_state.session_factory() as session:
        rows = (
            await session.execute(
                select(func.count(IndexText.id)).where(IndexText.field_key == "price_bucket")
            )
        ).scalar_one()
    assert rows == 0
    logged = [rec for rec in caplog.records if "price_bucket" in rec.getMessage()]
    assert len(logged) == 1, "once per provider and key, not once per record"


async def test_a_provider_cannot_invent_a_reference(client, records_app):
    """A ``REF`` row is load-bearing — it blocks deletes and fills the delete
    dialog — so one naming a type id that does not exist is dropped."""
    _app, db_state = records_app
    await make_type(client, "author", [field("name", "text")])
    await make_type(client, "note", [field("name", "text")])
    author = await make_record(client, "author", {"name": "A"})

    register_index_provider(
        yielding((IndexKind.REF, "haunt", (author["uuid"], 99999))),
        fields=[VirtualField("haunt", IndexKind.REF)],
    )
    await make_record(client, "note", {"name": "unrelated"})

    async with db_state.session_factory() as session:
        refs = (await session.execute(select(func.count(IndexRef.id)))).scalar_one()
    assert refs == 0

    panel = await client.get(
        f"{API}/types/author/records/{author['uuid']}/referrers", headers=roles(ADMIN)
    )
    assert panel.json()["total"] == 0
    deleted = await client.delete(
        f"{API}/types/author/records/{author['uuid']}", headers=roles(ADMIN)
    )
    assert deleted.status_code == 204


# ---------------------------------------------------------------------------
# m4 — the anonymous grammar reaches only the anonymous shape
# ---------------------------------------------------------------------------


@pytest.fixture
async def published(client):
    await make_type(client, "article", [indexed("name")], is_public=True)
    created = await make_record(client, "article", {"name": "One"})
    await client.put(
        f"{API}/types/article/records/{created['uuid']}",
        json={"data": {"name": "One"}, "status": "published", "expected_version": 1},
        headers=roles(ADMIN),
    )
    await client.app.state.records_module.on_startup(client.app)
    return client


@pytest.mark.parametrize(
    "query",
    [
        "sort=-updated_at",
        "sort=created_at",
        "sort=position",
        "sort=-status",
        "filter=updated_at:gt:2020-01-01T00:00:00Z",
        "filter=created_at:lt:2099-01-01T00:00:00Z",
        "filter=position:eq:0",
        "filter=status:eq:draft",
    ],
)
async def test_a_column_the_public_shape_removes_is_refused_by_name(published, query):
    resp = await published.get(f"{API}/public/article?{query}")
    assert resp.status_code == 400
    assert resp.json()["detail"].endswith(f"{query.split('=')[1].lstrip('-').split(':')[0]!r}")


@pytest.mark.parametrize(
    "query", ["sort=slug", "sort=-published_at", "sort=display_title", "filter=name:eq:One"]
)
async def test_the_columns_it_keeps_still_answer(published, query):
    resp = await published.get(f"{API}/public/article?{query}")
    assert resp.status_code == 200, resp.text
    assert resp.json()["total"] == 1


# ---------------------------------------------------------------------------
# M3 — the prefix an operator can type
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "prefix", ["/api/records", "/api", "/admin", "/admin/records", "/", "", "api/records/public"]
)
def test_a_prefix_that_would_expose_the_admin_surface_is_refused(prefix):
    with pytest.raises(ValueError):
        check_public_route_prefix(prefix)
    with pytest.raises(ValueError):
        RecordsSettings(public_route_prefix=prefix)


@pytest.mark.parametrize("prefix", ["/api/records/public", "/content", "/api/records/public/"])
def test_a_usable_prefix_is_accepted(prefix):
    assert RecordsSettings(public_route_prefix=prefix).public_route_prefix == prefix


async def test_a_stored_prefix_that_no_longer_validates_falls_back(records_app, caplog):
    """A row written before the validator existed reaches ``on_startup``
    anyway. Raising there takes the host down and leaves the only screen that
    could fix the setting unreachable, so the default is used — loudly."""
    app, _db_state = records_app
    registry_ = PublicRouteRegistry()
    app.state.public_routes = registry_
    # Assignment, not construction: this is what a stored override looks like
    # from inside a process whose rules changed under it.
    app.state.sm_records.settings.public_route_prefix = "/api/records"

    with caplog.at_level(logging.ERROR):
        await app.state.records_module.on_startup(app)

    assert not registry_.matches("GET", "/api/records/types")
    assert registry_.matches("GET", "/api/records/public/article")
    assert [rec for rec in caplog.records if "public_route_prefix" in rec.getMessage()]


async def test_on_startup_twice_leaves_one_exemption(records_app):
    """A host that restarts the lifespan in-process must not grow a rule per
    restart."""
    app, _db_state = records_app
    app.state.public_routes = PublicRouteRegistry()
    await app.state.records_module.on_startup(app)
    await app.state.records_module.on_startup(app)
    assert len(app.state.public_routes.routes) == 1


async def test_the_public_get_and_head_are_distinct_operations(records_app):
    """One ``api_route`` with both verbs gave them one ``operationId``, which
    warns twice per route and breaks generated clients."""
    app, _db_state = records_app
    app.state.public_routes = PublicRouteRegistry()
    await app.state.records_module.on_startup(app)
    app.openapi_schema = None
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        schema = app.openapi()
    ids = [
        operation["operationId"]
        for path, item in schema["paths"].items()
        if "/public/" in path
        for operation in item.values()
    ]
    assert len(ids) == 4
    assert len(set(ids)) == 4
    assert not [w for w in caught if "Duplicate Operation ID" in str(w.message)]
