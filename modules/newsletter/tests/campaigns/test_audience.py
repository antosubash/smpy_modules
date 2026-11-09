"""A campaign's audience: the forms it takes and the filter terms it resolves to."""

from __future__ import annotations

import pytest
from simple_module_db import finalize_session
from sm_newsletter.campaigns.audience import (
    Audience,
    audience_count,
    audience_filters,
    parse_audience,
)
from sm_newsletter.core.errors_audience import (
    InvalidAudience,
    SegmentListMismatch,
    UnknownSegment,
    UnknownTag,
)
from sm_newsletter.core.tenancy import tenant_scope
from sm_newsletter.models import Segment

from tests.support.records_seed import TAGS, restrict_list, seed_list, seed_subscriber

T = "default"


async def _segment(db, *, key="news", tenant=T, filters=("tags:in:vip",)) -> int:
    with tenant_scope(tenant):
        seg = Segment(tenant_id=tenant, name=f"s-{key}", list_type_key=key, filters=list(filters))
        db.add(seg)
        await finalize_session(db)
        return seg.id


async def _filters(db, audience, *, key="news", tenant=T, roles=None):
    return await audience_filters(
        db, tenant_id=tenant, list_type_key=key, audience=audience, roles=roles
    )


def test_parse_audience_forms():
    assert parse_audience("all") == Audience("all")
    assert parse_audience("tag:vip") == Audience("tag", tag="vip")
    assert parse_audience("segment:12") == Audience("segment", segment_id=12)
    assert parse_audience(f"segment:{2**31 - 1}").segment_id == 2**31 - 1
    assert parse_audience("tag:" + "x" * 100).tag == "x" * 100
    for raw in (
        "tag:",
        "tag:" + "x" * 101,
        "tag:a\nb",
        "segment:0",
        "segment:012",
        "segment:abc",
        "segment:-1",
        "segment:99999999999",
        f"segment:{2**31}",
        "other:x",
        "",
    ):
        with pytest.raises(InvalidAudience) as err:
            parse_audience(raw)
        assert err.value.detail == InvalidAudience.detail  # never the submitted value


async def test_tag_filters_and_unknown_tag(db_state, db):
    await seed_list(db_state, T, fields=[TAGS])
    await seed_list(db_state, T, "plain")
    assert await _filters(db, "all") == []
    assert await _filters(db, "tag:vip") == ["tags:eq:vip"]
    with pytest.raises(UnknownTag):
        await _filters(db, "tag:nope")
    with pytest.raises(UnknownTag):
        await _filters(db, "tag:vip", key="plain")


async def test_segment_filters_mismatch_and_unknown(db_state, db):
    await seed_list(db_state, T, fields=[TAGS])
    await seed_list(db_state, T, "other", fields=[TAGS])
    sid = await _segment(db)
    assert await _filters(db, f"segment:{sid}") == ["tags:in:vip"]
    with pytest.raises(SegmentListMismatch):
        await _filters(db, f"segment:{sid}", key="other")
    with pytest.raises(UnknownSegment):
        await _filters(db, f"segment:{sid + 100}")


async def test_segment_on_unreadable_list_is_unknown(db_state, db):
    await seed_list(db_state, T, fields=[TAGS])
    await seed_list(db_state, T, "other", fields=[TAGS])
    sid = await _segment(db, key="other")
    await restrict_list(db_state, T, "other", ["editor"])
    with pytest.raises(UnknownSegment):
        await _filters(db, f"segment:{sid}", roles=[])
    with pytest.raises(SegmentListMismatch):
        await _filters(db, f"segment:{sid}", roles=["editor"])


@pytest.mark.unbound_tenant
async def test_segment_of_other_tenant_is_unknown(db_state, db):
    await seed_list(db_state, T, fields=[TAGS])
    await seed_list(db_state, "b", fields=[TAGS])
    sid = await _segment(db, tenant="b")
    with tenant_scope(T), pytest.raises(UnknownSegment):
        await _filters(db, f"segment:{sid}")
    with tenant_scope("b"):
        assert await _filters(db, f"segment:{sid}", tenant="b") == ["tags:in:vip"]


async def test_audience_count(db_state, db):
    await seed_list(db_state, T, fields=[TAGS])
    await seed_subscriber(db_state, T, "a@example.org", "confirmed", data={"tags": ["vip"]})
    await seed_subscriber(db_state, T, "b@example.org", "confirmed", data={"tags": ["events"]})
    await seed_subscriber(db_state, T, "c@example.org", "pending", data={"tags": ["vip"]})
    count = await audience_count(
        db, tenant_id=T, list_type_key="news", audience="tag:vip", roles=None
    )
    assert count == 1
    everyone = await audience_count(
        db, tenant_id=T, list_type_key="news", audience="all", roles=None
    )
    assert everyone == 2
