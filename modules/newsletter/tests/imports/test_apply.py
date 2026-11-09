"""Applying one batch (R2, R3, R15, D8): records first, then suppressions, then outcomes."""

from __future__ import annotations

import json

import pytest
from sm_newsletter.core.suppression import email_hash

from tests.imports.world import FIELDS, upload
from tests.support.app import build_app
from tests.support.import_world import (
    CLEAN,
    SUB,
    UNSUB,
    apply_now,
    job_row,
    outcomes,
    queued,
    records_of,
    run_all,
    set_job,
    set_rows,
    suppress_at,
    suppressed_of,
    suppression_rows,
    tag_choices,
)
from tests.support.records_seed import TAGS, seed_list, seed_subscriber

pytestmark = pytest.mark.unbound_tenant

ADA, BOB, CY, DEE = (f"{n}@example.org" for n in ("ada", "bob", "cy", "dee"))
UNSUB_HEAD = ["Email Address", "First Name", "Last Name", "UNSUB_TIME"]


async def test_apply_writes_records_and_suppressions(state):
    jid = await queued(
        state,
        upload(SUB, [[ADA, "Ada", "L", "VIP"], [BOB, "Bob", "M", ""]]),
        upload(UNSUB, [[CY, "Cy", "N", ""]]),
        upload(CLEAN, [[DEE, "Dee", "O", ""]]),
    )
    result = await apply_now(state, jid)
    records = await records_of(state)
    assert records[ADA].data["sm_status"] == "confirmed"
    assert records[ADA].data["tags"] == ["vip"]
    assert records[ADA].data["first_name"] == "Ada"
    assert records[BOB].data["sm_status"] == "confirmed"
    assert records[CY].data["sm_status"] == "unsubscribed"
    assert DEE not in records
    rows = {(r[0], r[1], r[2], r[3]) for r in await suppression_rows(state)}
    assert rows == {
        (email_hash(CY), "unsubscribed", "news", "import"),
        (email_hash(DEE), "imported_cleaned", "", "import"),
    }
    assert await suppressed_of(state, [ADA, BOB, CY, DEE]) == {CY, DEE}
    counts = (result.created, result.updated, result.skipped, result.suppressed, result.failed)
    assert counts == (2, 0, 0, 2, 0)
    assert result.errors == []
    assert None not in (await outcomes(state, jid)).values()


@pytest.mark.parametrize("indexed", [True, False], ids=["indexed", "not-indexed"])
async def test_tag_values_final_and_distinct(tmp_path, indexed):
    """D8, also on a list whose ``tags`` field is not indexed (T6b): its existing choices are
    still seen, so the label "VIP" never lands on the unrelated existing value ``VIP``."""
    _app, state = await build_app(file=tmp_path / "tags.db")
    choices = {"choices": [{"value": "VIP", "label": "Very important"}]}
    tags = {**TAGS, "indexed": indexed, "options": choices}
    await seed_list(state, "default", fields=[FIELDS[0], FIELDS[1], tags])
    try:
        jid = await queued(
            state,
            upload(SUB, [[ADA, "", "", '"Customers, 2020"'], [BOB, "", "", "Customers; 2020,VIP"]]),
        )
        preview = {t["label"]: t["value"] for t in (await job_row(state, jid)).tags_found}
        assert preview["VIP"] != "VIP"  # staging's preview sees the choice too
        assert await run_all(state.session_factory, jid) == ["done"]
        job = await job_row(state, jid)
        values = {t["label"]: t["value"] for t in job.tags_found}
        assert set(values) == {"Customers, 2020", "Customers; 2020", "VIP"}
        assert len(set(values.values())) == 3
        assert values["VIP"] != "VIP"  # taken by "Very important"
        assert "," not in values["Customers, 2020"]
        choices = await tag_choices(state)
        assert choices["VIP"] == "Very important"
        for label, value in values.items():
            assert choices[value] == label
        records = await records_of(state)
        assert records[ADA].data["tags"] == [values["Customers, 2020"]]
        assert sorted(records[BOB].data["tags"]) == sorted(
            [values["Customers; 2020"], values["VIP"]]
        )
    finally:
        await state.engine.dispose()


async def test_kept_confirmed_gets_no_suppression(state):
    await seed_subscriber(state, "default", ADA, "confirmed")
    jid = await queued(
        state,
        upload(UNSUB, [[ADA, "", "", "2020-01-01 00:00:00"]], headers=UNSUB_HEAD),
    )
    result = await apply_now(state, jid)
    assert (await outcomes(state, jid))[ADA] == "kept_confirmed"
    assert await suppression_rows(state) == []
    assert (result.skipped, result.suppressed) == (1, 0)
    assert (await records_of(state))[ADA].data["sm_status"] == "confirmed"


async def test_invalid_value_reported_as_row_error(tmp_path):
    _app, state = await build_app(file=tmp_path / "invalid.db")
    team = {
        "key": "team",
        "type": "select",
        "label": "Team",
        "options": {"choices": [{"value": "red", "label": "Red"}]},
    }
    await seed_list(state, "default", fields=[*FIELDS, team])
    try:
        head = ["Email Address", "Team"]
        jid = await queued(
            state,
            upload(SUB, [[ADA, "secret-value-9c1"]], headers=head),
            mapping={"fields": {"0": "team"}, "tags": False},
        )
        assert await run_all(state.session_factory, jid) == ["done"]
        job = await job_row(state, jid)
        assert job.errors == [{"file": 0, "line": 2, "code": "invalid_value", "field": "team"}]
        assert job.errors_total == 1
        assert "secret-value-9c1" not in json.dumps(job.model_dump(mode="json"))
        record = (await records_of(state))[ADA]
        assert record.data["sm_status"] == "confirmed"
        assert record.data.get("team") is None
    finally:
        await state.engine.dispose()


async def test_apply_pins_the_tenant(state):
    await seed_list(state, "other", fields=FIELDS)
    await seed_subscriber(state, "other", ADA, "confirmed")
    await suppress_at(state, ADA, "complaint", tenant="other")
    before_records = {k: v.data for k, v in (await records_of(state, "other")).items()}
    before_rows = await suppression_rows(state, "other")
    jid = await queued(
        state, upload(UNSUB, [[ADA, "", "", ""]]), upload(CLEAN, [[BOB, "", "", ""]])
    )
    await apply_now(state, jid)
    assert {k: v.data for k, v in (await records_of(state, "other")).items()} == before_records
    assert await suppression_rows(state, "other") == before_rows
    assert {r[1] for r in await suppression_rows(state)} == {"unsubscribed", "imported_cleaned"}


async def test_label_missing_from_tags_found_is_a_row_error(state):
    """Cannot happen after T6a; if it ever does, the label is reported, not dropped silently."""
    jid = await queued(state, upload(SUB, [[ADA, "", "", "VIP,Events"]]))
    await set_job(state, jid, tags_found=[{"label": "VIP", "value": "vip", "count": 1}])
    result = await apply_now(state, jid)
    assert result.errors == [{"file": 0, "line": 2, "code": "tag_invalid", "field": "tags"}]
    assert (await records_of(state))[ADA].data["tags"] == ["vip"]


async def test_unknown_kind_is_refused_not_suppressed(state):
    jid = await queued(state, upload(CLEAN, [[ADA, "", "", ""]]))
    await set_rows(state, jid, kind="ignored")
    with pytest.raises(ValueError, match="unknown staged row kind"):
        await apply_now(state, jid)
    assert await suppression_rows(state) == []
