"""The CAPTCHA secret at rest (#350): every supported write stores ``enc:v2:``,
a row stored before 0.0.16 still verifies until startup seals it, and one no
key opens refuses the submission (503) without ever logging the value."""

from __future__ import annotations

import json
import logging

import pytest
from settings.core.service import SettingService
from settings.module_settings.reload import apply_changes_and_reload
from settings.module_settings.store import SettingsStore
from simple_module_db.stored_settings import Setting, settings_table_clause
from sm_records.core import constants, crypto
from sm_records.core.settings import RecordsSettings
from sm_records.public_submissions import captcha_secret
from sqlalchemy import insert, select

from tests.public_submissions.test_public_submissions_captcha import ON
from tests.support.submissions_http import configure, contact_type, records_of, send

SECRET = "turnstile-secret-1"


@pytest.fixture
async def settings_db(site):
    """The harness database with the framework's ``settings_setting`` table."""
    db = site.app.state.sm.db
    async with db.engine.begin() as conn:
        await conn.run_sync(lambda c: Setting.__table__.create(c, checkfirst=True))
    return db


async def _row(db) -> tuple[str, str] | None:
    table = settings_table_clause()
    async with db.session_factory() as session:
        found = await session.execute(
            select(table.c.value, table.c.value_type).where(table.c.key == captcha_secret.KEY)
        )
        row = found.first()
    return (row[0], row[1]) if row is not None else None


async def _put_row(db, value: str, value_type: str = "string") -> None:
    async with db.session_factory() as session:
        await session.execute(
            insert(settings_table_clause()).values(
                scope="system",
                scope_id="",
                key=captcha_secret.KEY,
                value=value,
                value_type=value_type,
            )
        )
        await session.commit()


async def test_an_encrypted_secret_verifies(site, provider):
    configure(site, **{**ON, captcha_secret.FIELD: crypto.encrypt_value(SECRET)})
    await contact_type(site)
    assert (await send(site, captcha_response="good")).status_code == 202
    assert provider.asked[0][1]["secret"] == [SECRET]


async def test_a_plaintext_secret_still_verifies(site, provider):
    configure(site, **{**ON, captcha_secret.FIELD: SECRET})
    await contact_type(site)
    assert (await send(site, captcha_response="good")).status_code == 202
    assert provider.asked[0][1]["secret"] == [SECRET]


async def test_an_unreadable_secret_refuses_and_never_logs_it(site, provider, caplog):
    other = crypto.encrypt_value(SECRET)
    site.app.state.sm.settings.secret_key = "a-rotated-key"
    configure(site, **{**ON, captcha_secret.FIELD: other})
    await contact_type(site)
    with caplog.at_level(logging.DEBUG):
        refused = await send(site, captcha_response="good")
    assert refused.status_code == 503 and refused.json()["code"] == "captcha_unavailable"
    assert provider.asked == [] and await records_of(site) == []
    logged = "\n".join(r.getMessage() for r in caplog.records)
    assert "CaptchaSecretUnreadableError" in logged
    assert SECRET not in logged and other not in logged


async def test_the_settings_screen_write_stores_it_encrypted(site, settings_db):
    """The framework's own write path (PUT /api/settings/modules/sm_records)
    stores a json field's validated dump — the sealed value, not the text sent.
    If a framework release stops doing that, this fails."""
    app = site.app
    async with settings_db.session_factory() as session:
        store = SettingsStore(SettingService(session))
        await apply_changes_and_reload(
            app,
            app.state.sm.event_bus,
            store,
            package=constants.PACKAGE,
            changes={captcha_secret.FIELD: f"  {SECRET} "},
        )
        await session.commit()
    value, value_type = await _row(settings_db)
    assert value_type == "json"
    stored = json.loads(value)
    assert stored.startswith(crypto.ENC_V2) and SECRET not in value
    assert crypto.decrypt_value(stored, captcha_secret.FIELD) == SECRET


async def test_startup_seals_a_legacy_plaintext_row(settings_db):
    await _put_row(settings_db, SECRET)
    sealed = await captcha_secret.seal_stored(settings_db.session_factory)
    value, value_type = await _row(settings_db)
    assert value == sealed and value_type == "string"
    assert value.startswith(crypto.ENC_V2)
    assert crypto.decrypt_value(value, captcha_secret.FIELD) == SECRET
    assert await captcha_secret.seal_stored(settings_db.session_factory) is None, "a no-op"


async def test_startup_seals_a_plaintext_json_row(settings_db):
    await _put_row(settings_db, json.dumps(SECRET), "json")
    await captcha_secret.seal_stored(settings_db.session_factory)
    value, _ = await _row(settings_db)
    assert crypto.decrypt_value(json.loads(value), captcha_secret.FIELD) == SECRET


async def test_startup_updates_the_live_settings(site, settings_db):
    await _put_row(settings_db, SECRET)
    configure(site, **{**ON, captcha_secret.FIELD: SECRET})
    module = type("M", (), {"db": settings_db})()
    await captcha_secret.seal_at_startup(site.app, module)
    live = getattr(site.app.state, constants.PACKAGE).settings
    assert live.public_submissions_captcha_secret.startswith(crypto.ENC_V2)
    assert captcha_secret.secret(live) == SECRET


async def test_the_seal_never_overwrites_a_concurrent_change(settings_db):
    """Compare-and-set: the row changes between the read and the write, so the
    write matches nothing and the newer value stays."""
    await _put_row(settings_db, SECRET)
    newer = crypto.encrypt_value("saved-meanwhile")
    table = settings_table_clause()

    class _Racing:
        """A session whose first UPDATE is preceded by another writer's."""

        def __init__(self) -> None:
            self.ctx = settings_db.session_factory()

        async def __aenter__(self):
            session = await self.ctx.__aenter__()
            original = session.execute

            async def execute(statement, *args, **kwargs):
                if getattr(statement, "is_update", False):
                    changed = table.update().where(table.c.key == captcha_secret.KEY)
                    await original(changed.values(value=newer))
                return await original(statement, *args, **kwargs)

            session.execute = execute
            return session

        async def __aexit__(self, *exc):
            return await self.ctx.__aexit__(*exc)

    assert await captcha_secret.seal_stored(_Racing) is None
    value, _ = await _row(settings_db)
    assert value == newer


async def test_a_live_app_without_a_key_refuses_to_store_it_in_the_clear(site, settings_db):
    """Fail closed: an attached app whose secret_key is empty makes the dump
    raise, so the Settings write path stores nothing rather than plaintext."""
    app = site.app
    app.state.sm.settings.secret_key = ""
    assert crypto.has_secret_provider()
    with pytest.raises(Exception, match="secret_key"):
        RecordsSettings(**{captcha_secret.FIELD: SECRET}).model_dump()
    async with settings_db.session_factory() as session:
        store = SettingsStore(SettingService(session))
        with pytest.raises(Exception, match="secret_key"):
            await apply_changes_and_reload(
                app,
                app.state.sm.event_bus,
                store,
                package=constants.PACKAGE,
                changes={captcha_secret.FIELD: SECRET},
            )
        await session.rollback()
    assert await _row(settings_db) is None
