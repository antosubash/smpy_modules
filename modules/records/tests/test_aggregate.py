"""``GET /types/{key}/records/aggregate`` — the live aggregate, and the stored one.

Phase 5 §5.1. The original design said the aggregates this module actually
needs are "``COUNT(*)`` with a ``GROUP BY`` against an indexed table"; this is
that endpoint, and these tests are mostly about it being the *same* query the
list is — same filter grammar, same refusals, same soft-delete rule — because
a dashboard that counts a different set from the one the list shows is worse
than no dashboard.

Records are written through the API rather than seeded, because the index rows
the ``GROUP BY`` reads are written by ``write_index`` and a seeded row has
none.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sm_records.index.reduce import register_reduce_provider

from tests.app_harness import ADMIN, ROLE_EDITOR_TWO, ROLE_VIEWER, roles, seed_type
from tests.test_reduce import STATE, state_spec

API = "/api/records/types"


_CHOICES = [{"value": tag, "label": tag.title()} for tag in ("red", "blue")]


def _field(key: str, type_: str, **extra) -> dict:
    options = extra.pop("options", None) or {}
    return {
        "key": key,
        "type": type_,
        "label": key.title(),
        "indexed": True,
        "options": options,
        **extra,
    }


@pytest.fixture
async def order(client):
    return await seed_type(
        client.db_state,
        "order",
        [
            _field("state", "text"),
            _field("total", "number"),
            _field("placed", "date"),
            _field("name", "text"),
            _field("tags", "multiselect", options={"choices": _CHOICES}),
            _field("note", "text", indexed=False),
        ],
        display_field="name",
    )


async def create(client, data, **extra):
    response = await client.post(
        f"{API}/order/records", json={"data": data, **extra}, headers=roles(ADMIN)
    )
    assert response.status_code == 201, response.text
    return response.json()


async def agg(client, expect=200, **params):
    response = await client.get(
        f"{API}/order/records/aggregate", params=params, headers=roles(ROLE_VIEWER)
    )
    assert response.status_code == expect, response.text
    return response.json()


@pytest.fixture
async def seeded(client, order):
    await create(client, {"state": "CA", "total": "10", "placed": "2026-01-02", "name": "a"})
    await create(client, {"state": "CA", "total": "5", "placed": "2026-03-04", "name": "b"})
    await create(client, {"state": "NY", "total": "7", "placed": "2026-02-02", "name": "c"})
    return order


async def test_count_per_group_is_ordered_by_count_then_value(client, seeded):
    body = await agg(client, group_by="state")
    assert body["group_by"] == "state"
    assert body["metric"] == "count"
    assert body["groups"] == [
        {"value": "CA", "count": 2, "sum": None, "min": None, "max": None},
        {"value": "NY", "count": 1, "sum": None, "min": None, "max": None},
    ]
    assert body["total_groups"] == 2
    assert body["truncated"] is False
    assert body["stored"] is False


async def test_sum_min_and_max_over_the_kinds_that_support_them(client, seeded):
    summed = await agg(client, group_by="state", metric="sum:total")
    assert summed["metric"] == "sum:total"
    assert [(g["value"], Decimal(g["sum"])) for g in summed["groups"]] == [
        ("CA", Decimal("15.00000")),
        ("NY", Decimal("7.00000")),
    ]
    dates = await agg(client, group_by="state", metric="min:placed")
    assert (dates["groups"][0]["value"], dates["groups"][0]["min"]) == ("CA", "2026-01-02")
    text = await agg(client, group_by="state", metric="max:name")
    assert (text["groups"][0]["value"], text["groups"][0]["max"]) == ("CA", "b")


async def test_fixed_columns_group_without_an_index_table(client, seeded):
    """``status`` and ``locale`` are columns on ``records_record``, not index
    rows — the grammar resolves them first, and the aggregate has to agree."""
    await create(client, {"state": "TX", "total": "1", "name": "d"}, status="published")
    by_status = await agg(client, group_by="status")
    assert {g["value"]: g["count"] for g in by_status["groups"]} == {"draft": 3, "published": 1}
    by_locale = await agg(client, group_by="locale")
    assert {g["value"]: g["count"] for g in by_locale["groups"]} == {"en": 4}


async def test_filters_narrow_the_aggregate_exactly_as_they_narrow_the_list(client, seeded):
    body = await agg(client, group_by="state", metric="sum:total", filter="total:gte:7")
    assert {g["value"]: (g["count"], g["sum"]) for g in body["groups"]} == {
        "CA": (1, "10.00000"),
        "NY": (1, "7.00000"),
    }
    assert (await agg(client, group_by="state", locale="de"))["groups"] == []


async def test_a_multi_valued_group_counts_a_record_once_per_value(client, order):
    await create(client, {"state": "CA", "name": "a", "tags": ["red", "blue"]})
    await create(client, {"state": "CA", "name": "b", "tags": ["red"]})
    body = await agg(client, group_by="tags")
    assert {g["value"]: g["count"] for g in body["groups"]} == {"red": 2, "blue": 1}


async def test_the_trash_is_never_counted(client, seeded):
    """The soft-delete rule is the framework's ``with_loader_criteria`` hook,
    which attaches to the ``Record`` mapper this statement names — the F4 trap
    in ``docs/performance.md``, one aggregate over."""
    listing = await client.get(f"{API}/order/records", headers=roles(ADMIN))
    uuid = listing.json()["items"][0]["uuid"]
    assert (
        await client.delete(f"{API}/order/records/{uuid}", headers=roles(ADMIN))
    ).status_code == 204
    counts = {g["value"]: g["count"] for g in (await agg(client, group_by="state"))["groups"]}
    assert sum(counts.values()) == 2


async def test_the_group_cap_truncates_the_long_tail(client, order):
    client.app.state.sm_records.settings = client.app.state.sm_records.settings.model_copy(
        update={"max_aggregate_groups": 2}
    )
    for i in range(4):
        await create(client, {"state": f"S{i}", "total": "1", "name": f"n{i}"})
    body = await agg(client, group_by="state")
    assert body["total_groups"] == 2
    assert body["truncated"] is True


async def test_allowed_roles_narrow_the_aggregate(client, order):
    await seed_type(
        client.db_state,
        "secret",
        [_field("state", "text")],
        allowed_roles=[ROLE_VIEWER],
    )
    ok = await client.get(
        f"{API}/secret/records/aggregate?group_by=state", headers=roles(ROLE_VIEWER)
    )
    assert ok.status_code == 200
    nope = await client.get(
        f"{API}/secret/records/aggregate?group_by=state", headers=roles(ROLE_EDITOR_TWO)
    )
    assert nope.status_code == 403


@pytest.mark.parametrize(
    ("params", "status", "reason"),
    [
        ({"group_by": "nope"}, 400, "unknown"),
        ({"group_by": "note"}, 400, "not_indexed"),
        ({"group_by": "state", "metric": "sum:name"}, 400, "unsupported_op"),
        ({"group_by": "state", "metric": "sum:tags"}, 400, "unsupported_op"),
        ({"group_by": "state", "metric": "avg:total"}, 400, "bad_value"),
        ({"group_by": "state", "metric": "sum"}, 400, "bad_value"),
        ({}, 400, "unknown"),
        ({"reduce": "nope"}, 400, "unknown"),
    ],
)
async def test_refusals_use_the_filter_grammars_shapes(client, seeded, params, status, reason):
    body = await agg(client, expect=status, **params)
    assert body["reason"] == reason


async def test_a_field_mid_rebuild_is_the_409_a_filter_on_it_is(client, order):
    async with client.db_state.session_factory() as session:
        from sm_records.models import RecordType
        from sqlalchemy import select

        stored_type = (
            (await session.execute(select(RecordType).where(RecordType.key == "order")))
            .scalars()
            .first()
        )
        stored_type.reindex_pending = {"state": "2026-01-01T00:00:00+00:00"}
        session.add(stored_type)
        await session.commit()
    body = await agg(client, expect=409, group_by="state")
    assert body["reason"] == "reindexing"


async def test_the_stored_reading_answers_in_the_same_shape(client, seeded):
    """``?reduce=`` is the maintained aggregate, on the same endpoint and in
    the same shape — so a caller can ask both and compare, which is how drift
    is noticed by the thing that reads it rather than only by the CLI."""
    register_reduce_provider(state_spec())
    # The spec was registered after these records were written, so the table is
    # empty until a rebuild — the documented consequence of a provider being a
    # deployment rather than a schema edit.
    assert (await agg(client, reduce=STATE))["groups"] == []

    assert (await client.post(f"{API}/order/reindex", headers=roles(ADMIN))).status_code == 202
    body = await agg(client, reduce=STATE)
    assert body["stored"] is True
    assert body["updated_at"] is not None
    # The spec's own description of its fold, and not ``sum:<spec key>``: on a
    # live reading ``sum:<x>`` names a *field*, so the two now read alike.
    assert body["metric"] == "sum:total"
    live = await agg(client, group_by="state", metric="sum:total")
    assert [(g["value"], g["count"], g["sum"]) for g in body["groups"]] == [
        (g["value"], g["count"], g["sum"]) for g in live["groups"]
    ]


async def test_a_stored_reading_cannot_be_filtered(client, seeded):
    register_reduce_provider(state_spec())
    body = await agg(client, expect=400, reduce=STATE, filter="total:gte:7")
    assert body["reason"] == "unsupported_op"
