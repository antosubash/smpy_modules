"""A bulk publish of an already-published record writes nothing.

"Select all, Publish" is the natural gesture on a list, and most of what it
selects is usually already published. Every one of those went through
``update_record`` with its own payload read straight back: same status, same
data, and a version bump, an ``update`` revision and a ``RecordUpdated`` all
the same. A history nobody can read is the cost, and the toast said "12
records published" about the three that moved.

A no-op is now a turn of its own: nothing written, counted as ``unchanged``.
The distinction the module already draws for an import (a row the file agrees
with is *skipped*, not updated) is the one drawn here.

``trash``/``restore``/``purge`` are deliberately not like this: they change a
record's existence, and a caller acting on a list that has moved underneath
them has to be told rather than quietly agreed with.
"""

from __future__ import annotations

import pytest_asyncio
from sm_records.contracts.events import RecordUpdated

from tests.app_harness import ADMIN, roles
from tests.bulk_helpers import API, bulk, make_product, read
from tests.events_harness import Recorder, recorder


@pytest_asyncio.fixture
async def bus(client) -> Recorder:
    return recorder(client)


@pytest_asyncio.fixture
async def product(client) -> dict:
    return await make_product(client)


async def _record(client, name: str, *, status: str) -> str:
    resp = await client.post(
        API,
        json={"data": {"name": name, "topic": "news"}, "status": status},
        headers=roles(ADMIN),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()["uuid"]


async def _revision_events(client, uuid: str) -> list[str]:
    resp = await client.get(f"{API}/{uuid}/revisions", headers=roles(ADMIN))
    assert resp.status_code == 200, resp.text
    return [item["event"] for item in resp.json()["items"]]


async def test_publishing_a_published_record_writes_nothing(client, product, bus):
    uuid = await _record(client, "One", status="published")
    before = (await read(client, uuid)).json()
    assert before["version"] == 1
    bus.seen.clear()
    bus.committed.clear()

    resp = await bulk(client, "publish", [uuid])

    assert resp.status_code == 200, resp.text
    assert resp.json() == {
        "action": "publish",
        "requested": 1,
        "changed": 0,
        "unchanged": 1,
        "cascaded": 0,
    }
    after = (await read(client, uuid)).json()
    assert after["version"] == 1
    assert after["status"].lower() == "published"
    assert after["updated_at"] == before["updated_at"]
    assert await _revision_events(client, uuid) == ["create"]
    assert bus.only(RecordUpdated) == []


async def test_unpublishing_a_draft_is_the_same_no_op(client, product, bus):
    uuid = await _record(client, "One", status="draft")
    bus.seen.clear()

    resp = await bulk(client, "unpublish", [uuid])

    assert resp.status_code == 200, resp.text
    assert (resp.json()["changed"], resp.json()["unchanged"]) == (0, 1)
    assert (await read(client, uuid)).json()["version"] == 1
    assert await _revision_events(client, uuid) == ["create"]
    assert bus.only(RecordUpdated) == []


async def test_a_real_transition_still_bumps_and_still_publishes(client, product, bus):
    """The guard on the exemption: only the no-op is exempt."""
    uuid = await _record(client, "One", status="draft")
    bus.seen.clear()
    bus.committed.clear()

    resp = await bulk(client, "publish", [uuid])

    assert resp.status_code == 200, resp.text
    assert (resp.json()["changed"], resp.json()["unchanged"]) == (1, 0)
    assert (await read(client, uuid)).json()["version"] == 2
    assert await _revision_events(client, uuid) == ["update", "create"]
    (event,) = bus.only(RecordUpdated)
    assert (event.uuid, event.status_before, event.status_after) == (uuid, "draft", "published")
    assert all(bus.committed)


async def test_a_mixed_batch_counts_each_half(client, product, bus):
    """The number the operator reconciles against the list: two selected, one
    of them already published, one event and one bumped version."""
    moving = await _record(client, "Draft", status="draft")
    already = await _record(client, "Live", status="published")
    bus.seen.clear()

    resp = await bulk(client, "publish", [moving, already])

    assert resp.status_code == 200, resp.text
    assert resp.json() == {
        "action": "publish",
        "requested": 2,
        "changed": 1,
        "unchanged": 1,
        "cascaded": 0,
    }
    assert [event.uuid for event in bus.only(RecordUpdated)] == [moving]
    assert (await read(client, moving)).json()["version"] == 2
    assert (await read(client, already)).json()["version"] == 1


async def test_a_no_op_still_makes_its_version_check(client, product):
    """``expected_versions`` is about the list the selection came from, so a
    stale one is still a refusal — the record being already published says
    nothing about whether the operator was looking at the current row."""
    uuid = await _record(client, "One", status="published")

    resp = await bulk(client, "publish", [uuid], expected_versions={uuid: 99})

    assert resp.status_code == 409, resp.text
    assert resp.json()["report"]["failed"][0]["uuid"] == uuid
