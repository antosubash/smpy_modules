"""What a calendar manager who may not read a record type sees of a mapping to it, and what a
mapping that stopped working says to whoever can fix it."""

from __future__ import annotations

import json

import pytest

pytest.importorskip("sm_events")

from sm_events.contracts.extensions import SettingsContext, SourceError, SourceSettingsError
from sm_records.integrations.events.settings import (
    RecordDateMapping,
    RecordDatesSettings,
    check_settings,
)
from sm_records.integrations.events.source import RecordDatesSource

from tests.integrations.events.support import CALENDAR, context, make_type, viewer

SOURCE = RecordDatesSource()
SECRET = "salary_reviews"


def mapping(type_key="deadlines", field="due", **kw):
    return {"type_key": type_key, "field": field, **kw}


def sctx(db, who, preserved=()):
    return SettingsContext(
        tenant_id="default", viewer=who, calendar=CALENDAR, db=db, preserved=tuple(preserved)
    )


async def seed(db):
    await make_type(db)
    await make_type(db, key=SECRET, allowed_roles=["boss"])


async def test_a_manager_without_rights_gets_a_placeholder_not_the_mapping(db):
    await seed(db)
    stored = {"mappings": [mapping(), mapping(SECRET, "due", color="#112233")]}
    got = await SOURCE.view_settings(sctx(db, viewer()), stored)
    assert got.settings["mappings"] == [mapping(), {"hidden": True, "token": "h1"}]
    text = json.dumps([got.settings, got.problems])
    for leaked in (SECRET, "#112233"):
        assert leaked not in text
    assert stored["mappings"][1]["type_key"] == SECRET  # the stored settings are not touched


async def test_an_unreadable_type_and_a_missing_one_look_the_same(db):
    await seed(db)
    got = await SOURCE.view_settings(
        sctx(db, viewer()), {"mappings": [mapping(SECRET, "due"), mapping("nonexistent", "x")]}
    )
    assert got.settings["mappings"] == [
        {"hidden": True, "token": "h0"},
        {"hidden": True, "token": "h1"},
    ]
    assert got.problems == ()


async def test_someone_with_rights_sees_everything(db):
    await seed(db)
    stored = {"mappings": [mapping(), mapping(SECRET, "due")]}
    got = await SOURCE.view_settings(sctx(db, viewer("boss")), stored)
    assert got.settings == stored and got.problems == ()


async def test_a_broken_field_is_a_problem_for_someone_who_may_read_the_type(db):
    await seed(db)
    stored = {"mappings": [mapping(field="gone"), mapping(field="title")]}
    got = await SOURCE.view_settings(sctx(db, viewer()), stored)
    assert [(p.loc, p.code) for p in got.problems] == [
        (("mappings", 0, "field"), "field_missing"),
        (("mappings", 1, "field"), "field_not_date"),
    ]


async def test_a_save_puts_the_hidden_mapping_back_byte_identical(db):
    await seed(db)
    stored = {"mappings": [mapping(), mapping(SECRET, "due", color="#112233", end_field=None)]}
    submitted = {"mappings": [mapping(field="at"), {"hidden": True, "token": "h1"}]}
    got = await SOURCE.restore_settings(sctx(db, viewer()), submitted, stored)
    assert json.dumps(got.settings["mappings"][1]) == json.dumps(stored["mappings"][1])
    assert got.settings["mappings"][0]["field"] == "at"
    assert got.preserved == (("mappings", 1),)


async def test_a_placeholder_left_out_stays(db):
    await seed(db)
    stored = {"mappings": [mapping(SECRET, "due"), mapping()]}
    got = await SOURCE.restore_settings(
        sctx(db, viewer()), {"mappings": [mapping(field="at")]}, stored
    )
    assert got.settings["mappings"] == [mapping(field="at"), stored["mappings"][0]]
    assert got.preserved == (("mappings", 1),)


@pytest.mark.parametrize(
    "token",
    [
        {"hidden": True, "token": "h7"},  # no such mapping
        {"hidden": True, "token": "h0"},  # a mapping this caller may read: not theirs to restore
        {"hidden": True, "token": "nonsense"},
        {"hidden": True, "token": "h1", "type_key": SECRET},  # a placeholder carries nothing else
    ],
)
async def test_a_forged_placeholder_is_the_unknown_type_error(db, token):
    await seed(db)
    stored = {"mappings": [mapping(), mapping(SECRET, "due")]}
    with pytest.raises(SourceSettingsError) as caught:
        await SOURCE.restore_settings(sctx(db, viewer()), {"mappings": [token]}, stored)
    unknown = None
    with pytest.raises(SourceSettingsError) as other:
        await check_settings(
            sctx(db, viewer()),
            RecordDatesSettings(mappings=[RecordDateMapping(type_key="nonexistent", field="x")]),
        )
    unknown = other.value
    assert (caught.value.message, caught.value.code) == (unknown.message, unknown.code)


async def test_a_repeated_placeholder_is_refused(db):
    await seed(db)
    stored = {"mappings": [mapping(SECRET, "due")]}
    token = {"hidden": True, "token": "h0"}
    with pytest.raises(SourceSettingsError):
        await SOURCE.restore_settings(sctx(db, viewer()), {"mappings": [token, token]}, stored)


async def test_check_skips_what_was_put_back_but_not_what_was_typed(db):
    await seed(db)
    settings = RecordDatesSettings(mappings=[RecordDateMapping(type_key=SECRET, field="due")])
    await check_settings(sctx(db, viewer(), preserved=[("mappings", 0)]), settings)
    with pytest.raises(SourceSettingsError) as caught:  # typed by the manager: judged
        await check_settings(sctx(db, viewer()), settings)
    assert caught.value.code == "type_unavailable"


async def test_the_codes_of_a_broken_field(db):
    await seed(db)
    for field, code in (("gone", "field_missing"), ("title", "field_not_date")):
        with pytest.raises(SourceSettingsError) as caught:
            await check_settings(
                sctx(db, viewer()),
                RecordDatesSettings(
                    mappings=[RecordDateMapping(type_key="deadlines", field=field)]
                ),
            )
        assert (caught.value.loc, caught.value.code) == ((("mappings", 0, "field")), code)


def cfg(type_key="deadlines", field="due"):
    return RecordDatesSettings(mappings=[RecordDateMapping(type_key=type_key, field=field)])


async def read(db, settings, who):
    return list(
        await SOURCE.occurrences(
            context(db, settings, who),
            __import__("datetime").datetime(2026, 7, 1, tzinfo=__import__("datetime").UTC),
            __import__("datetime").datetime(2026, 8, 1, tzinfo=__import__("datetime").UTC),
        )
    )


async def test_a_deleted_field_is_named_for_a_reader_and_silent_for_anyone_else(db):
    await seed(db)
    with pytest.raises(SourceError) as caught:
        await read(db, cfg(field="gone"), viewer())
    assert caught.value.code == "field_missing"
    assert await read(db, cfg(field="gone"), viewer(perms=())) == []  # not allowed: nothing told
    assert await read(db, cfg(SECRET, "gone"), viewer()) == []  # not theirs: same as no type


async def test_a_deleted_type_is_silent(db):
    await seed(db)
    assert await read(db, cfg("nonexistent", "due"), viewer()) == []
