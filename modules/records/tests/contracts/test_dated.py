"""``sm_records.contracts.dated``: records of a type with a date in a window."""

from __future__ import annotations

import dataclasses
from datetime import UTC, date, datetime

import pytest
from sm_records.contracts import dated
from sm_records.contracts.dated import (
    MAX_DATED_BATCH,
    DatedQueryError,
    dated_records,
)
from sm_records.core.settings import RecordsSettings
from sm_records.core.tenancy import tenant_scope
from sm_records.models import RecordStatus
from sm_records.records.services import records as record_service

from tests.contracts.dated_support import (  # noqa: F401
    FIELDS,
    HI,
    HI_T,
    LO,
    LO_T,
    SETTINGS,
    VIEW,
    add,
    caller,
    make_type,
    read,
)
from tests.support.app_harness import field  # noqa: F401


async def test_range_half_open_and_sorted(db):
    rtype = await make_type(db)
    for title, due in (
        ("late", "2026-07-20"),
        ("edge", "2026-08-01"),
        ("first", "2026-07-01"),
        ("mid", "2026-07-10"),
        ("before", "2026-06-30"),
    ):
        await add(db, rtype, title, due=due)
    page = await read(db)
    assert [h.display_title for h in page.hits] == ["first", "mid", "late"]  # [lo, hi), ascending
    assert [h.start for h in page.hits] == [date(2026, 7, 1), date(2026, 7, 10), date(2026, 7, 20)]
    assert page.truncated is False
    hit = page.hits[0]
    assert (hit.type_key, hit.end) == ("deadlines", None) and hit.uuid and hit.locale
    assert dataclasses.is_dataclass(hit) and hit.__dataclass_params__.frozen  # type: ignore[attr-defined]


async def test_datetime_field_and_end_field(db):
    rtype = await make_type(db)
    await add(db, rtype, "talk", at="2026-07-05T10:00:00+00:00", ends="2026-07-05T12:00:00+00:00")
    page = await read(db, field="at", lo=LO_T, hi=HI_T, end_field="ends")
    assert page.hits[0].start == datetime(2026, 7, 5, 10, tzinfo=UTC)
    assert page.hits[0].end == datetime(2026, 7, 5, 12, tzinfo=UTC)
    day = await add(db, rtype, "span", due="2026-07-08", until="2026-07-10")
    got = await read(db, end_field="until")
    assert [(h.start, h.end) for h in got.hits] == [(date(2026, 7, 8), date(2026, 7, 10))]
    assert day.uuid


async def test_limit_and_truncated(db):
    rtype = await make_type(db)
    for i in range(5):
        await add(db, rtype, f"r{i}", due=f"2026-07-{i + 1:02d}")
    page = await read(db, limit=3)
    assert [h.display_title for h in page.hits] == ["r0", "r1", "r2"] and page.truncated
    exact = await read(db, limit=5)
    assert len(exact.hits) == 5 and exact.truncated is False
    for bad in (0, -1, MAX_DATED_BATCH + 1, True, 2.5):
        with pytest.raises(ValueError):
            await read(db, limit=bad)


async def test_window_is_bounded(db):
    await make_type(db)
    with pytest.raises(ValueError):
        await read(db, lo=date(2020, 1, 1), hi=date(2026, 1, 1))
    with pytest.raises(ValueError):
        await read(db, lo=HI, hi=LO)


async def test_drafts_never_returned(db):
    rtype = await make_type(db)
    await add(db, rtype, "draft", due="2026-07-05", status=RecordStatus.DRAFT)
    await add(db, rtype, "live", due="2026-07-05")
    who = caller("admin", perms=(VIEW, "records.edit"))
    assert [h.display_title for h in (await read(db, who=who)).hits] == ["live"]


async def test_trash_excluded(db):
    rtype = await make_type(db)
    gone = await add(db, rtype, "gone", due="2026-07-05")
    await add(db, rtype, "kept", due="2026-07-06")
    await record_service.soft_delete_record(db, rtype, gone, settings=SETTINGS)
    assert [h.display_title for h in (await read(db)).hits] == ["kept"]


async def test_unknown_type_or_field_is_empty(db):
    await make_type(db)
    assert (await read(db, "nope")).hits == []
    assert (await read(db, field="nope")).hits == []
    assert (await read(db, "nope", who=None, locale="en")).hits == []


async def test_not_indexed_raises(db):
    await make_type(db)
    with pytest.raises(DatedQueryError) as caught:
        await read(db, field="note")
    assert caught.value.reason == "not_indexed"
    with pytest.raises(DatedQueryError) as caught:
        await read(db, field="title")
    assert caught.value.reason in {"not_indexed", "not_a_date"}


async def test_kind_mismatch_raises(db):
    await make_type(db)
    with pytest.raises(DatedQueryError) as caught:
        await read(db, field="due", lo=LO_T, hi=HI_T)  # datetime bounds on a date field
    assert caught.value.reason == "kind_mismatch"
    with pytest.raises(DatedQueryError) as caught:
        await read(db, field="at", lo=LO, hi=HI)  # date bounds on a datetime field
    assert caught.value.reason == "kind_mismatch"
    with pytest.raises(DatedQueryError) as caught:
        await read(db, field="at", lo=LO_T.replace(tzinfo=None), hi=HI_T.replace(tzinfo=None))
    assert caught.value.reason == "kind_mismatch"  # a naive time means nothing
    with pytest.raises(DatedQueryError) as caught:
        await read(db, field="due", end_field="at")
    assert caught.value.reason == "kind_mismatch"


async def test_translatable_filters_locale(db):
    both = RecordsSettings(content_locales=("en", "de"))
    rtype = await make_type(db, translatable=True)
    await record_service.create_record(
        db,
        rtype,
        data={"title": "hello", "due": "2026-07-05"},
        settings=both,
        status=RecordStatus.PUBLISHED,
        locale="en",
    )
    await record_service.create_record(
        db,
        rtype,
        data={"title": "hallo", "due": "2026-07-05"},
        settings=both,
        status=RecordStatus.PUBLISHED,
        locale="de",
    )
    assert [h.display_title for h in (await read(db, locale="de")).hits] == ["hallo"]
    assert [h.display_title for h in (await read(db, locale="en")).hits] == ["hello"]
    plain = await make_type(db, "plain_t")
    await add(db, plain, "one", due="2026-07-05")
    assert len((await read(db, "plain_t", locale="de")).hits) == 1  # not translatable: every row


@pytest.mark.unbound_tenant
async def test_tenant_pinned(db):
    for tenant, title in (("a", "from-a"), ("b", "from-b")):
        with tenant_scope(tenant):
            rtype = await make_type(db)
            await add(db, rtype, title, due="2026-07-05")
    got = await dated_records(
        db,
        tenant_id="a",
        type_key="deadlines",
        field="due",
        lo=LO,
        hi=HI,
        caller=caller(),
        locale=None,
        limit=10,
    )
    assert [h.display_title for h in got.hits] == ["from-a"]
    for bad in ("a\n", "", None, 5):
        with pytest.raises(ValueError):
            await dated_records(
                db,
                tenant_id=bad,
                type_key="deadlines",
                field="due",
                lo=LO,
                hi=HI,  # type: ignore[arg-type]
                caller=caller(),
                locale=None,
                limit=10,
            )


def test_contract_surface():
    assert sorted(dated.__all__) == sorted(
        [
            "MAX_DATED_BATCH",
            "DatedCaller",
            "DatedHit",
            "DatedPage",
            "DatedQueryError",
            "DatedTypeInfo",
            "dated_field_kind",
            "dated_records",
            "dated_types",
        ]
    )
    assert MAX_DATED_BATCH == 1000
