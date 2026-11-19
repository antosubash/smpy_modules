"""The ``records:dates`` source's settings, and ``check_settings`` against the real types."""

from __future__ import annotations

import pytest

pytest.importorskip("sm_events")

from pydantic import ValidationError
from sm_events.contracts.extensions import SettingsContext, SourceSettingsError
from sm_records.integrations.events.settings import (
    RecordDateMapping,
    RecordDatesSettings,
    check_settings,
)

from tests.integrations.events.support import CALENDAR, add, make_type, viewer  # noqa: F401


def mapping(**kw):
    return {"type_key": "deadlines", "field": "due", **kw}


def test_one_to_five_mappings():
    RecordDatesSettings(mappings=[mapping()])
    RecordDatesSettings(mappings=[mapping() for _ in range(5)])
    for bad in ([], [mapping() for _ in range(6)]):
        with pytest.raises(ValidationError):
            RecordDatesSettings(mappings=bad)


@pytest.mark.parametrize(
    "bad",
    [
        {"duration_minutes": 0},
        {"duration_minutes": 1441},
        {"color": "red"},
        {"surprise": 1},
        {"type_key": ""},
    ],
)
def test_mapping_bounds(bad):
    with pytest.raises(ValidationError):
        RecordDateMapping(**mapping(**bad))


def test_mapping_defaults():
    m = RecordDateMapping(**mapping())
    assert (m.end_field, m.duration_minutes, m.color) == (None, 60, None)


async def check(db, *mappings, who=None):
    ctx = SettingsContext(tenant_id="default", viewer=who or viewer(), calendar=CALENDAR, db=db)
    await check_settings(ctx, RecordDatesSettings(mappings=list(mappings)))


async def err(db, *mappings, who=None) -> SourceSettingsError:
    with pytest.raises(SourceSettingsError) as caught:
        await check(db, *mappings, who=who)
    return caught.value


async def test_a_valid_mapping_passes(db):
    await make_type(db)
    await check(
        db,
        RecordDateMapping(**mapping()),
        RecordDateMapping(**mapping(field="at", end_field="ends")),
    )


async def test_check_settings_unknown_type(db):
    await make_type(db)
    e = await err(db, RecordDateMapping(**mapping()), RecordDateMapping(**mapping(type_key="nope")))
    assert e.loc == ("mappings", 1, "type_key")


async def test_check_settings_unreadable_type(db):
    await make_type(db, allowed_roles=["editor"])
    e = await err(db, RecordDateMapping(**mapping()), who=viewer("viewer"))
    assert e.loc == ("mappings", 0, "type_key")  # indistinguishable from an unknown one
    await check(db, RecordDateMapping(**mapping()), who=viewer("editor"))
    denied = await err(db, RecordDateMapping(**mapping()), who=viewer(perms=()))
    assert denied.loc == ("mappings", 0, "type_key")


async def test_check_settings_not_indexed(db):
    await make_type(db)
    e = await err(db, RecordDateMapping(**mapping(field="title")))
    assert e.loc == ("mappings", 0, "field")
    e = await err(db, RecordDateMapping(**mapping(field="gone")))
    assert e.loc == ("mappings", 0, "field")


async def test_check_settings_kind_mismatch(db):
    await make_type(db)
    e = await err(db, RecordDateMapping(**mapping(field="due", end_field="ends")))
    assert e.loc == ("mappings", 0, "end_field")
    e = await err(db, RecordDateMapping(**mapping(end_field="title")))
    assert e.loc == ("mappings", 0, "end_field")


async def test_end_field_differs(db):
    await make_type(db)
    e = await err(db, RecordDateMapping(**mapping(end_field="due")))
    assert e.loc == ("mappings", 0, "end_field")
