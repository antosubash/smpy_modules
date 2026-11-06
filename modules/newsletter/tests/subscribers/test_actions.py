"""Tag, untag and the admin unsubscribe (PR 6, Task 9; G14)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
import pytest_asyncio
from sm_newsletter.core.errors import NotFound
from sm_newsletter.core.errors_audience import InvalidQuery, NotSubscribed, UnknownTag
from sm_newsletter.core.tenancy import tenant_scope
from sm_newsletter.subscribers.actions import set_subscriber_tags, unsubscribe_subscriber
from sm_records.contracts.events import RecordUpdated, SubscriptionChanged

from tests.support.app import build_app
from tests.support.records_seed import TAGS, restrict_list, seed_list, seed_subscriber
from tests.support.unsub_world import status_of_uuid, suppressions

pytestmark = pytest.mark.unbound_tenant

ADA = "ada@example.org"
NOW = datetime.now(UTC)


@pytest_asyncio.fixture
async def world():
    app, state = await build_app()
    seen: list[Any] = []

    async def spy(event: Any) -> None:
        seen.append(event)

    app.state.sm.event_bus.subscribe(RecordUpdated, spy)
    app.state.sm.event_bus.subscribe(SubscriptionChanged, spy)
    await seed_list(state, "default", fields=[TAGS])
    yield app, state, seen
    await state.engine.dispose()


async def _tags(world, uuid, *, add=(), remove=(), tenant="default", key="news", roles=None):
    app, state, _ = world
    with tenant_scope(tenant):
        async with state.session_factory() as s:
            return await set_subscriber_tags(
                app,
                s,
                tenant_id=tenant,
                list_type_key=key,
                uuid=uuid,
                add=list(add),
                remove=list(remove),
                roles=roles,
            )


async def _unsub(world, uuid, *, tenant="default", key="news", roles=None):
    app, state, _ = world
    with tenant_scope(tenant):
        async with state.session_factory() as s:
            return await unsubscribe_subscriber(
                app, s, tenant_id=tenant, list_type_key=key, uuid=uuid, roles=roles, now=NOW
            )


async def test_add_and_remove_tags(world):
    _, state, seen = world
    uuid = await seed_subscriber(state, "default", ADA, "confirmed", data={"tags": ["vip"]})
    hit = await _tags(world, uuid, add=["events"], remove=["vip"])
    assert hit.tags == ["events"]
    assert [type(e) for e in seen] == [RecordUpdated]
    again = await _tags(world, uuid, add=["events"])
    assert again.tags == ["events"] and len(seen) == 1


async def test_unknown_tag_refused_nothing_written(world):
    _, state, seen = world
    uuid = await seed_subscriber(state, "default", ADA, "confirmed", data={"tags": ["vip"]})
    with pytest.raises(UnknownTag) as err:
        await _tags(world, uuid, add=["events", "SECRETTAG"])
    assert "SECRETTAG" not in str(err.value.detail)
    assert seen == []
    assert (await _tags(world, uuid)).tags == ["vip"]
    # a choice deleted since may still be removed
    assert (await _tags(world, uuid, remove=["gone"])).tags == ["vip"]


async def test_tag_input_bounds(world):
    _, state, _ = world
    uuid = await seed_subscriber(state, "default", ADA, "confirmed", data={"tags": []})
    for add, remove in ((["vip"] * 21, []), ([], ["x"] * 21), ([""], []), ([], [""])):
        with pytest.raises(InvalidQuery):
            await _tags(world, uuid, add=add, remove=remove)


async def test_list_without_tags_field_refuses(world):
    _, state, _ = world
    await seed_list(state, "default", key="plain")
    uuid = await seed_subscriber(state, "default", ADA, "confirmed", key="plain")
    with pytest.raises(UnknownTag):
        await _tags(world, uuid, add=["vip"], key="plain")


async def test_tag_missing_subscriber_404(world):
    with pytest.raises(NotFound):
        await _tags(world, "a" * 32, add=["vip"])


async def test_unsubscribe_writes_records_and_suppression_together(world):
    _, state, seen = world
    uuid = await seed_subscriber(state, "default", ADA, "confirmed")
    hit = await _unsub(world, uuid)
    assert hit.status == "unsubscribed"
    assert await status_of_uuid(state, "default", uuid) == "unsubscribed"
    assert await suppressions(state, "default") == [("unsubscribed", "news", "admin")]
    assert [type(e) for e in seen if isinstance(e, SubscriptionChanged)] == [SubscriptionChanged]


async def test_unsubscribe_pending_is_not_subscribed(world):
    _, state, seen = world
    uuid = await seed_subscriber(state, "default", ADA, "pending")
    with pytest.raises(NotSubscribed):
        await _unsub(world, uuid)
    assert await suppressions(state, "default") == [] and seen == []
    assert await status_of_uuid(state, "default", uuid) == "pending"


async def test_unsubscribe_twice_second_is_409(world):
    _, state, seen = world
    uuid = await seed_subscriber(state, "default", ADA, "confirmed")
    await _unsub(world, uuid)
    with pytest.raises(NotSubscribed):
        await _unsub(world, uuid)
    assert len(await suppressions(state, "default")) == 1 and len(seen) == 1


async def test_unsubscribe_missing_or_trashed_404(world):
    _, state, _ = world
    trashed = await seed_subscriber(state, "default", ADA, "confirmed", trashed=True)
    for uuid in (trashed, "b" * 32):
        with pytest.raises(NotFound):
            await _unsub(world, uuid)
    assert await suppressions(state, "default") == []


async def test_actions_pin_the_tenant(world):
    _, state, seen = world
    await seed_list(state, "other", fields=[TAGS])
    uuid = await seed_subscriber(state, "other", ADA, "confirmed", data={"tags": ["vip"]})
    with pytest.raises(NotFound):
        await _tags(world, uuid, add=["events"])
    with pytest.raises(NotFound):
        await _unsub(world, uuid)
    assert await status_of_uuid(state, "other", uuid) == "confirmed"
    assert await suppressions(state, "other") == [] and seen == []


async def test_restricted_list_actions_404(world):
    _, state, seen = world
    uuid = await seed_subscriber(state, "default", ADA, "confirmed", data={"tags": []})
    await restrict_list(state, "default", "news", ["editor"])
    with pytest.raises(NotFound):
        await _tags(world, uuid, add=["vip"], roles=["viewer"])
    with pytest.raises(NotFound):
        await _unsub(world, uuid, roles=["viewer"])
    assert await status_of_uuid(state, "default", uuid) == "confirmed" and seen == []
    assert (await _unsub(world, uuid, roles=["editor"])).status == "unsubscribed"
