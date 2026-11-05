"""Segments: the store, tenant pinning, list narrowing and compiled terms."""

from __future__ import annotations

from datetime import timedelta

import pytest
from simple_module_db import finalize_session
from sm_newsletter.core.clock import utcnow
from sm_newsletter.core.errors import NotFound, UnknownList
from sm_newsletter.core.errors_audience import InvalidSegment, SegmentInUse, SegmentNameTaken
from sm_newsletter.core.tenancy import tenant_scope
from sm_newsletter.models import Campaign
from sm_newsletter.segments import store
from sm_newsletter.segments.rules import Rule, compile_rules
from sm_records.contracts.newsletter import count_subscribers
from sqlalchemy import update

from tests.support.campaign_world import seed_campaign
from tests.support.records_seed import TAGS, restrict_list, seed_list, seed_subscriber

T = "default"
NOBODY: list[str] = []


def _tag_rule(op="any", value=("vip",)) -> Rule:
    return Rule(field="tags", op=op, value=list(value))


async def _world(db_state):
    await seed_list(db_state, T, fields=[TAGS])
    await seed_subscriber(db_state, T, "a@example.org", "confirmed", data={"tags": ["vip"]})
    await seed_subscriber(db_state, T, "b@example.org", "confirmed", data={"tags": ["events"]})
    await seed_subscriber(db_state, T, "c@example.org", "pending", data={"tags": ["vip"]})


async def _create(db, name="VIPs", rules=None, roles=NOBODY, tenant=T):
    with tenant_scope(tenant):
        seg = await store.create_segment(
            db,
            tenant_id=tenant,
            roles=roles,
            name=name,
            list_type_key="news",
            rules=rules if rules is not None else [_tag_rule()],
        )
        await finalize_session(db)
        return seg


async def test_create_compiles_and_counts(db_state, db):
    await _world(db_state)
    seg = await _create(db)
    assert seg.filters == ["tags:in:vip"]
    assert seg.rules == [{"field": "tags", "op": "any", "value": ["vip"]}]
    count = await store.preview(
        db, tenant_id=T, roles=NOBODY, list_type_key="news", rules=[_tag_rule()]
    )
    assert count == 1


async def test_create_refusals(db_state, db):
    await _world(db_state)
    with pytest.raises(UnknownList):
        await store.create_segment(
            db, tenant_id=T, roles=NOBODY, name="x", list_type_key="nope", rules=[]
        )
    with pytest.raises(InvalidSegment) as bad:
        await _create(db, name="bad", rules=[_tag_rule(value=("SECRET-VALUE",))])
    assert str(bad.value).startswith("rules[0]:") and "SECRET-VALUE" not in str(bad.value)
    await _create(db)
    with pytest.raises(SegmentNameTaken):
        await _create(db)


async def test_update_recompiles_rules_and_filters_together(db_state, db):
    await _world(db_state)
    seg = await _create(db)
    with tenant_scope(T):
        out = await store.update_segment(
            db,
            tenant_id=T,
            segment_id=seg.id,
            roles=NOBODY,
            name="Events",
            rules=[_tag_rule(value=("events",))],
        )
        await finalize_session(db)
    assert out.name == "Events"
    assert out.filters == ["tags:in:events"]
    assert out.rules[0]["value"] == ["events"]
    with tenant_scope(T), pytest.raises(InvalidSegment):
        await store.update_segment(
            db,
            tenant_id=T,
            segment_id=seg.id,
            roles=NOBODY,
            name=None,
            rules=[Rule(field="nope", op="is", value="x")],
        )


async def test_delete_blocked_by_draft_not_by_scheduled(db_state, db):
    await _world(db_state)
    seg = await _create(db)
    cid = await seed_campaign(db_state, T, status="draft")
    async with db_state.session_factory() as s, s.begin():
        await s.execute(
            update(Campaign)
            .where(Campaign.id == cid, Campaign.tenant_id == T)
            .values(audience=f"segment:{seg.id}")
        )
    with tenant_scope(T):
        with pytest.raises(SegmentInUse):
            await store.delete_segment(db, tenant_id=T, segment_id=seg.id, roles=NOBODY)
        async with db_state.session_factory() as s, s.begin():
            await s.execute(
                update(Campaign)
                .where(Campaign.id == cid, Campaign.tenant_id == T)
                .values(status="scheduled")
            )
        await store.delete_segment(db, tenant_id=T, segment_id=seg.id, roles=NOBODY)
        await finalize_session(db)
        with pytest.raises(NotFound):
            await store.get_segment(db, tenant_id=T, segment_id=seg.id, roles=NOBODY)


@pytest.mark.unbound_tenant
async def test_segment_pins_the_tenant(db_state, db):
    await seed_list(db_state, "a", fields=[TAGS])
    await seed_list(db_state, "b", fields=[TAGS])
    seg_b = await _create(db, name="B", tenant="b")
    with tenant_scope("a"):
        with pytest.raises(NotFound):
            await store.get_segment(db, tenant_id="a", segment_id=seg_b.id, roles=NOBODY)
        with pytest.raises(NotFound):
            await store.update_segment(
                db, tenant_id="a", segment_id=seg_b.id, roles=NOBODY, name="Z", rules=None
            )
        with pytest.raises(NotFound):
            await store.delete_segment(db, tenant_id="a", segment_id=seg_b.id, roles=NOBODY)
        assert await store.list_segments(db, tenant_id="a", roles=NOBODY, list_type_key=None) == []
    with tenant_scope("b"):
        got = await store.get_segment(db, tenant_id="b", segment_id=seg_b.id, roles=NOBODY)
        assert got.name == "B"


async def test_restricted_list_segments_hidden(db_state, db):
    await _world(db_state)
    seg = await _create(db)
    await restrict_list(db_state, T, "news", ["editor"])
    with tenant_scope(T):
        assert await store.list_segments(db, tenant_id=T, roles=[], list_type_key=None) == []
        with pytest.raises(NotFound):
            await store.get_segment(db, tenant_id=T, segment_id=seg.id, roles=[])
        shown = await store.list_segments(db, tenant_id=T, roles=["editor"], list_type_key=None)
        assert [s.id for s in shown] == [seg.id]


async def test_preview_counts_confirmed_only(db_state, db):
    await _world(db_state)
    with tenant_scope(T):
        n = await store.preview(db, tenant_id=T, roles=NOBODY, list_type_key="news", rules=[])
        assert n == 2  # the pending one is not counted
        n = await store.preview(
            db, tenant_id=T, roles=NOBODY, list_type_key="news", rules=[_tag_rule()]
        )
        assert n == 1


def _f(key, type_, *choices):
    return {
        "key": key,
        "type": type_,
        "label": key,
        "indexed": True,
        "options": {"choices": [{"value": c, "label": c} for c in choices]} if choices else {},
    }


FIELDS = [
    TAGS,
    _f("plan", "select", "pro", "free"),
    _f("city", "text"),
    _f("age", "integer"),
    _f("vip", "boolean"),
    _f("born", "date"),
]
PEOPLE = [
    ("a@example.org", ["vip", "events"], "pro", "Berlin", 30, True, "1990-05-01"),
    ("b@example.org", ["vip"], "free", "Bonn", 25, False, "1985-01-01"),
    ("c@example.org", [], "pro", "Hamburg", 40, False, "2000-12-31"),
    ("d@example.org", ["events"], "free", "Berlin Mitte", 20, True, "1995-06-15"),
]
TOMORROW = (utcnow() + timedelta(days=1)).date().isoformat()
CASES = [
    ("tags", "any", ["vip"], 2),
    ("tags", "all", ["vip", "events"], 1),
    ("tags", "none", ["vip"], 2),
    ("plan", "is", "pro", 2),
    ("plan", "is_not", "pro", 2),
    ("plan", "any", ["pro", "free"], 4),
    ("city", "is", "Berlin", 1),
    ("city", "contains", "Berlin", 2),
    ("city", "starts_with", "Ham", 1),
    ("age", "is", "30", 1),
    ("age", "is_not", "30", 3),
    ("age", "gt", "30", 1),
    ("age", "gte", "30", 2),
    ("age", "lt", "25", 1),
    ("age", "lte", "25", 2),
    ("vip", "is", "true", 2),
    ("born", "before", "1990-01-01", 1),
    ("born", "since", "1990-01-01", 3),
    ("created_at", "since", TOMORROW, 0),
    ("created_at", "before", TOMORROW, 4),
]


@pytest.mark.parametrize(("field", "op", "value", "expected"), CASES)
async def test_compiled_terms_execute_through_records(db_state, db, field, op, value, expected):
    # Its own key: records caches a payload model by (key, version, type id), so
    # reusing "news" with another schema would serve the wrong validator.
    await seed_list(db_state, T, "wide", fields=FIELDS)
    for email, tags, plan, city, age, vip, born in PEOPLE:
        data = {"tags": tags, "plan": plan, "city": city, "age": age, "vip": vip, "born": born}
        await seed_subscriber(db_state, T, email, "confirmed", "wide", data=data)
    with tenant_scope(T):
        fields = await store.fields_for(db, tenant_id=T, list_type_key="wide")
        terms = compile_rules([Rule(field=field, op=op, value=value)], fields)
        got = await count_subscribers(db, tenant_id=T, type_key="wide", filters=terms)
    assert got == expected, terms
