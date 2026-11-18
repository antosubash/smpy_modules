"""A calendar's source entries: the tolerant reader and the validated write."""

from __future__ import annotations

import logging

import pytest
from fastapi.exceptions import RequestValidationError
from sm_events.calendar import registry, source_entries
from sm_events.calendar.extension_types import SourceViewer
from sm_events.core import errors_extensions as err
from sm_events.models import Calendar

from tests.support.access import seed_calendars
from tests.support.sources import FakeSource, SettingsSource, install

VIEWER = SourceViewer(user_id="o", roles=(), permissions=frozenset({"events.view"}))


class In:
    def __init__(self, id, settings=None):
        self.id, self.settings = id, settings or {}


@pytest.fixture
def desk(monkeypatch):
    source = SettingsSource()
    plain = FakeSource("acme:plain")
    install(monkeypatch, source, plain)
    yield source
    registry.reset_registry()


async def write(db, cal, *incoming):
    return await source_entries.write_entries(db, "default", VIEWER, cal, list(incoming))


def test_reads_legacy_strings():
    got = source_entries.read(["acme:x", {"id": "acme:y", "settings": {"a": 1}}])
    assert [(e.id, e.settings) for e in got] == [("acme:x", {}), ("acme:y", {"a": 1})]


def test_drops_malformed_and_logs(caplog):
    raw = [1, None, {"settings": {}}, {"id": "a", "settings": "x"}, {"id": "ok"}, "ok", "dup"]
    with caplog.at_level(logging.WARNING):
        got = source_entries.read([*raw, "dup"])
    assert [e.id for e in got] == ["ok", "dup"]
    assert "dropped" in caplog.text
    assert source_entries.read(None) == [] and source_entries.read({"a": 1}) == []


def test_reader_is_bounded():
    got = source_entries.read([f"s{i}" for i in range(50)])
    assert len(got) == 8


async def test_settings_validated_and_dumped(db, desk):
    cal = (await seed_calendars(db))["P"]
    (entry,) = await write(db, cal, In("acme:desk", {"field": "x", "count": "3"}))
    assert entry.settings == {"field": "x", "count": 3}
    assert cal.sources == [{"id": "acme:desk", "settings": {"field": "x", "count": 3}}]


async def test_source_without_model_needs_empty(db, desk):
    cal = (await seed_calendars(db))["P"]
    await write(db, cal, In("acme:plain"))
    with pytest.raises(RequestValidationError) as caught:
        await write(db, cal, In("acme:plain", {"a": 1}))
    assert caught.value.errors()[0]["loc"] == ("body", "sources", 0, "settings")


async def test_invalid_settings_loc_and_no_echo(db, desk):
    cal = (await seed_calendars(db))["P"]
    with pytest.raises(RequestValidationError) as caught:
        await write(db, cal, In("acme:plain"), In("acme:desk", {"count": "hunter2"}))
    (error,) = caught.value.errors()
    assert error["loc"] == ("body", "sources", 1, "settings", "count")
    assert "hunter2" not in str(error)
    with pytest.raises(RequestValidationError):
        await write(db, cal, In("acme:desk", {"unknown": 1}))  # extra='forbid'


async def test_settings_size_capped(db, desk):
    cal = (await seed_calendars(db))["P"]
    with pytest.raises(RequestValidationError):
        await write(db, cal, In("acme:desk", {"field": "x" * 20_000}))


async def test_unknown_kept_only_if_unchanged(db, desk):
    cal = (await seed_calendars(db))["P"]
    cal.sources = [{"id": "gone:thing", "settings": {"b": 1, "a": [1]}}]
    with pytest.raises(err.UnknownSource):
        await write(db, cal, In("gone:thing", {"a": [1], "b": 2}))
    with pytest.raises(err.UnknownSource):
        await write(db, cal, In("never:seen"))
    (kept,) = await write(db, cal, In("gone:thing", {"a": [1], "b": 1}))
    assert kept.settings == {"b": 1, "a": [1]}
    assert cal.sources == [{"id": "gone:thing", "settings": {"b": 1, "a": [1]}}]


async def test_builtin_refused(db, desk):
    cal = (await seed_calendars(db))["P"]
    with pytest.raises(err.BuiltinSource):
        await write(db, cal, In("events"))


async def test_duplicate_and_max(db, desk):
    cal = (await seed_calendars(db))["P"]
    with pytest.raises(err.DuplicateSource):
        await write(db, cal, In("acme:plain"), In("acme:plain"))
    with pytest.raises(err.TooManySources):
        await write(db, cal, *[In(f"x:s{i}") for i in range(9)])


async def test_check_settings_error_loc(db, desk):
    cal = (await seed_calendars(db))["P"]
    with pytest.raises(RequestValidationError) as caught:
        await write(db, cal, In("acme:desk", {"field": "bad"}))
    (error,) = caught.value.errors()
    assert list(error["loc"]) == ["body", "sources", 0, "settings", "field"]
    assert error["msg"] == "That field is not allowed"
    assert cal.sources == []


async def test_check_settings_gets_the_model_and_context(db, desk):
    cal = (await seed_calendars(db))["P"]
    await write(db, cal, In("acme:desk", {"field": "ok"}))
    ((sctx, settings),) = desk.checked
    assert settings.field == "ok"
    assert (sctx.tenant_id, sctx.viewer, sctx.calendar.slug) == ("default", VIEWER, "private")


async def test_check_settings_timeout_is_503(db, desk, monkeypatch):
    from sm_events.core import constants

    monkeypatch.setattr(constants, "SOURCE_TIMEOUT_SECONDS", 0.05)
    cal = (await seed_calendars(db))["P"]
    with pytest.raises(err.SourceUnavailable):
        await write(db, cal, In("acme:desk", {"field": "slow"}))


async def test_check_settings_exception_is_503_and_never_logs_its_message(db, desk, caplog):
    cal = (await seed_calendars(db))["P"]
    with caplog.at_level(logging.ERROR), pytest.raises(err.SourceUnavailable):
        await write(db, cal, In("acme:desk", {"field": "boom"}))
    assert "RuntimeError" in caplog.text and "leaked" not in caplog.text


async def test_check_settings_bad_sql_keeps_transaction(db, desk):
    """After a failing statement the request's transaction still works (on Postgres a bad
    statement aborts it unless it ran in a savepoint)."""
    from sqlalchemy import select

    cal = (await seed_calendars(db))["P"]
    with pytest.raises(err.SourceUnavailable):
        await write(db, cal, In("acme:desk", {"field": "sql"}))
    (await db.execute(select(Calendar))).scalars().all()
    (entry,) = await write(db, cal, In("acme:plain"))
    assert entry.id == "acme:plain"
    await db.commit()


def test_shown_hides_settings_without_the_right(desk):
    raw = [{"id": "acme:desk", "settings": {"field": "x"}}, "gone:y"]
    hidden = source_entries.shown(raw, with_settings=False)
    assert [(s["id"], s["settings"], s["installed"]) for s in hidden] == [
        ("acme:desk", {}, True),
        ("gone:y", {}, False),
    ]
    full = source_entries.shown(raw, with_settings=True)
    assert full[0]["settings"] == {"field": "x"} and full[0]["label_key"] == "acme.fake"
