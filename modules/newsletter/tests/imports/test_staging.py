"""Staging an export: counts, precedence (R3, Review Focus 1), errors, limits, tenant pin."""

from __future__ import annotations

import io

import pytest
import pytest_asyncio
from sm_newsletter.core.errors_import import ImportTooManyRows, ImportTooManyTags
from sm_newsletter.core.suppression import email_hash
from sm_newsletter.core.tenancy import tenant_scope
from sm_newsletter.imports import staging
from sm_newsletter.imports.archive import sources
from sm_newsletter.models import ImportEntry, ImportJob
from sqlalchemy import func, select

from tests.imports.fixtures import csv_bytes
from tests.imports.world import FIELDS, HEAD, NOW, job_of, rows_of, staged, upload
from tests.support.app import build_app
from tests.support.import_world import CLEAN, SUB, UNSUB
from tests.support.records_seed import seed_list

pytestmark = pytest.mark.unbound_tenant


@pytest_asyncio.fixture
async def state():
    _app, st = await build_app()
    await seed_list(st, "default", fields=FIELDS)
    yield st
    await st.engine.dispose()


async def test_stage_counts_kinds_and_columns(state):
    jid = await staged(
        state,
        upload(
            SUB,
            [
                ["a@x.org", "Ada", "L", 'VIP,"Customers, 2020"'],
                ["b@x.org", "Bo", "M", '"VIP","Events"'],
                ["c@x.org", "Cy", "N", "VIP"],
            ],
        ),
        upload(UNSUB, [["d@x.org", "Di", "O", ""]]),
        upload(CLEAN, [["e@x.org", "Ed", "P", ""]]),
    )
    job = await job_of(state, jid)
    assert job.status == "staged"
    assert (job.total, job.duplicates, job.invalid) == (5, 0, 0)
    assert job.files == [
        {"name": SUB, "kind": "subscribed", "rows": 3},
        {"name": UNSUB, "kind": "unsubscribed", "rows": 1},
        {"name": CLEAN, "kind": "cleaned", "rows": 1},
    ]
    assert [c["header"] for c in job.columns] == ["First Name", "Last Name"]
    assert [c["key"] for c in job.columns] == ["first name", "last name"]
    found = {t["label"]: t for t in job.tags_found}
    assert found["VIP"]["count"] == 3 and found["VIP"]["value"] == "vip"
    assert found["Events"]["count"] == 1 and found["Events"]["value"] == "events"
    assert found["Customers, 2020"]["count"] == 1
    assert "," not in found["Customers, 2020"]["value"]
    assert job.tags_found[0]["label"] == "VIP"
    assert job.mapping == {"fields": {"0": "first_name", "1": "last_name"}, "tags": True}
    rows = {r.email: r for r in await rows_of(state, jid)}
    assert rows["a@x.org"].fields == {"0": "Ada", "1": "L"}
    assert rows["a@x.org"].tags == ["VIP", "Customers, 2020"]
    assert rows["a@x.org"].outcome is None
    assert rows["a@x.org"].email_hash == email_hash("a@x.org")


async def test_precedence_cleaned_beats_subscribed_any_spelling(state):
    jid = await staged(
        state,
        upload(SUB, [["Ada@X.org", "Ada", "L", ""], ["b@x.org", "", "", ""]]),
        upload(CLEAN, [["ada@x.org ", "", "", ""]]),
    )
    job = await job_of(state, jid)
    assert (job.total, job.duplicates) == (2, 1)
    by = {r.email: r.kind for r in await rows_of(state, jid)}
    assert by == {"ada@x.org": "cleaned", "b@x.org": "subscribed"}
    assert [f["rows"] for f in job.files] == [1, 1]  # cleaned 1, subscribed 1 (staged)


async def test_precedence_unsubscribed_beats_subscribed(state):
    jid = await staged(
        state,
        upload(UNSUB, [["ada@x.org", "", "", ""]]),
        upload(SUB, [["ADA@x.org", "Ada", "", ""]]),
    )
    job = await job_of(state, jid)
    assert (job.total, job.duplicates) == (1, 1)
    assert [r.kind for r in await rows_of(state, jid)] == ["unsubscribed"]


async def test_cleaned_beats_unsubscribed(state):
    jid = await staged(
        state,
        upload(SUB, [["z@x.org", "", "", ""]]),
        upload(UNSUB, [["ada@x.org", "", "", ""]]),
        upload(CLEAN, [["ada@x.org", "", "", ""]]),
    )
    assert {r.email: r.kind for r in await rows_of(state, jid)} == {
        "z@x.org": "subscribed",
        "ada@x.org": "cleaned",
    }


async def test_duplicate_in_one_file_counted_once(state):
    jid = await staged(state, upload(SUB, [["a@x.org", "A1", "", ""], ["A@x.org", "A2", "", ""]]))
    job = await job_of(state, jid)
    assert (job.total, job.duplicates) == (1, 1)
    assert (await rows_of(state, jid))[0].fields == {"0": "A1"}  # first wins


async def test_invalid_rows_reported_not_staged(state):
    jid = await staged(
        state,
        upload(
            SUB,
            [
                ["a@x.org", "", "", ""],
                ["nope", "", "", ""],
                ["b@x.org", "", "", ""],
                ["", "x", "", ""],
            ],
        ),
    )
    job = await job_of(state, jid)
    assert (job.total, job.invalid) == (2, 2)
    assert job.errors[0] == {"file": 0, "line": 3, "code": "invalid_email", "field": None}
    assert job.errors_total == 2
    assert all("nope" not in str(e) for e in job.errors)


async def test_ignored_file_not_staged(state):
    jid = await staged(
        state,
        upload(SUB, [["a@x.org", "", "", ""]]),
        upload("nonsubscribed_members_export.csv", [["n@x.org", "", "", ""]]),
    )
    job = await job_of(state, jid)
    assert job.total == 1
    assert job.files[1] == {
        "name": "nonsubscribed_members_export.csv",
        "kind": "ignored",
        "rows": 0,
    }


async def test_too_many_rows_refused(state, monkeypatch):
    monkeypatch.setattr(staging, "MAX_ROWS", 3)
    files = [upload(SUB, [[f"u{i}@x.org", "", "", ""] for i in range(4)])]
    with tenant_scope("default"):
        async with state.session_factory() as s:
            with pytest.raises(ImportTooManyRows):
                await staging.stage(
                    s, tenant_id="default", list_type_key="news", sources=sources(files),
                    created_by=None, now=NOW,
                )  # fmt: skip
            await s.rollback()
        async with state.session_factory() as s:
            assert (await s.execute(select(func.count()).select_from(ImportJob))).scalar_one() == 0
            assert (
                await s.execute(select(func.count()).select_from(ImportEntry))
            ).scalar_one() == 0


async def test_too_many_new_tags_refused(state, monkeypatch):
    monkeypatch.setattr(staging, "MAX_NEW_TAGS", 2)
    files = [upload(SUB, [["a@x.org", "", "", "t1,t2,t3"]])]
    with tenant_scope("default"):
        async with state.session_factory() as s:
            with pytest.raises(ImportTooManyTags):
                await staging.stage(
                    s, tenant_id="default", list_type_key="news", sources=sources(files),
                    created_by=None, now=NOW,
                )  # fmt: skip


async def test_existing_tags_count_towards_the_limit(state, monkeypatch):
    """T6a: every distinct label counts, existing choices too, so ``tags_found`` always holds
    every label a row carries and none is dropped at apply."""
    monkeypatch.setattr(staging, "MAX_NEW_TAGS", 2)
    files = [upload(SUB, [["a@x.org", "", "", "VIP,Events,fresh"]])]
    with tenant_scope("default"):
        async with state.session_factory() as s:
            with pytest.raises(ImportTooManyTags):
                await staging.stage(
                    s, tenant_id="default", list_type_key="news", sources=sources(files),
                    created_by=None, now=NOW,
                )  # fmt: skip
    monkeypatch.setattr(staging, "MAX_NEW_TAGS", 3)
    jid = await staged(state, upload(SUB, [["a@x.org", "", "", "VIP,Events,fresh"]]))
    assert {t["label"] for t in (await job_of(state, jid)).tags_found} == {"VIP", "Events", "fresh"}


async def test_stage_pins_the_tenant(state):
    jid = await staged(state, upload(SUB, [["a@x.org", "", "", ""], ["b@x.org", "", "", ""]]))
    assert (await job_of(state, jid)).tenant_id == "default"
    rows = await rows_of(state, jid)
    assert len(rows) == 2 and {r.tenant_id for r in rows} == {"default"}


async def test_unknown_list_is_not_found(state):
    from sm_newsletter.core.errors import NotFound

    with tenant_scope("default"):
        async with state.session_factory() as s:
            with pytest.raises(NotFound):
                await staging.stage(
                    s, tenant_id="default", list_type_key="nope",
                    sources=sources([upload(SUB, [["a@x.org", "", "", ""]])]),
                    created_by=None, now=NOW,
                )  # fmt: skip


class _Tracked(io.BytesIO):
    def __init__(self, data: bytes) -> None:
        super().__init__(data)
        self.opened = 0

    def __enter__(self):
        return self


async def test_owned_streams_are_closed_and_uploads_are_not(state):
    from sm_newsletter.imports.archive import Source

    data = csv_bytes(HEAD, [["a@x.org", "", "", ""]])
    owned, shared = [], _Tracked(data)

    def open_owned():
        owned.append(io.BytesIO(data))
        return owned[-1]

    def open_shared():
        shared.seek(0)
        return shared

    files = [Source(0, SUB, open_owned, owned=True), Source(1, UNSUB, open_shared)]
    with tenant_scope("default"):
        async with state.session_factory() as s:
            await staging.stage(
                s,
                tenant_id="default",
                list_type_key="news",
                sources=files,
                created_by=None,
                now=NOW,
            )
    assert len(owned) == 2 and all(b.closed for b in owned)  # peeked, then staged
    assert not shared.closed
