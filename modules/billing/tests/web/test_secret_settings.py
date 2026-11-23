"""Supported Settings writes seal both Stripe credentials and keep them masked."""

from __future__ import annotations

import json

import pytest
from settings.core.invalidation import reload_package
from settings.core.service import SettingService
from settings.module_settings.store import SettingsStore
from simple_module_db.stored_settings import settings_table_clause
from sm_billing.core import crypto
from sqlalchemy import select

URL = "/api/settings/modules/sm_billing"
FIELDS = ("stripe_secret_key", "stripe_webhook_secret")


async def stored_row(app, field):
    table = settings_table_clause()
    async with app.state.sm.db.session_factory() as session:
        return (
            await session.execute(
                select(table.c.value, table.c.value_type).where(
                    table.c.key == f"sm_billing.{field}", table.c.scope == "system"
                )
            )
        ).one_or_none()


@pytest.mark.parametrize("field", FIELDS)
async def test_generic_settings_seals_the_stored_value_and_masks_responses(app, admin, field):
    plain = "stripe-secret-saved-generically"
    saved = await admin.put(URL, json={field: plain})
    assert saved.status_code == 200, saved.text
    assert plain not in saved.text
    value, value_type = await stored_row(app, field)
    assert value_type == "json"
    sealed = json.loads(value)
    assert sealed.startswith("enc:v2:") and plain not in value
    assert crypto.decrypt_value(sealed, field) == plain
    assert getattr(app.state.sm_billing.settings, field) == sealed
    shown = await admin.get("/api/settings/modules")
    assert shown.status_code == 200, shown.text
    assert plain not in shown.text and sealed not in shown.text


@pytest.mark.parametrize("field", FIELDS)
@pytest.mark.parametrize("empty", ["", None])
async def test_generic_settings_can_clear_a_secret(app, admin, field, empty):
    assert (await admin.put(URL, json={field: "saved-secret"})).status_code == 200
    cleared = await admin.put(URL, json={field: empty})
    assert cleared.status_code == 200, cleared.text
    assert await stored_row(app, field) is None
    assert getattr(app.state.sm_billing.settings, field) == ""


async def test_live_missing_key_refuses_storage(app, admin):
    app.state.sm.settings.secret_key = ""
    with pytest.raises(Exception, match="secret_key"):
        await admin.put(URL, json={FIELDS[0]: "must-not-be-stored"})
    assert await stored_row(app, FIELDS[0]) is None


@pytest.mark.parametrize("field", FIELDS)
async def test_reloading_legacy_string_rows_preserves_the_held_value(app, field):
    async with app.state.sm.db.session_factory() as session:
        store = SettingsStore(SettingService(session))
        await store.set_override("sm_billing", field, "legacy-plaintext", "string")
        await session.commit()
        for _ in range(2):
            await reload_package(app, app.state.sm.event_bus, store, "sm_billing")
            settings = app.state.sm_billing.settings
            settings.model_dump()
            assert getattr(settings, field) == "legacy-plaintext"
    assert await stored_row(app, field) == ("legacy-plaintext", "string")


@pytest.mark.parametrize(
    ("field", "flag"),
    [("stripe_secret_key", "clear_secret_key"), ("stripe_webhook_secret", "clear_webhook_secret")],
)
async def test_connection_blank_keeps_ciphertext_and_explicit_clear_removes_it(
    app, admin, field, flag
):
    connection = "/api/billing/admin/connection"
    saved = await admin.put(connection, json={field: "connection-secret"})
    assert saved.status_code == 200, saved.text
    before = await stored_row(app, field)
    kept = await admin.put(connection, json={field: "  "})
    assert kept.status_code == 200, kept.text
    assert await stored_row(app, field) == before
    cleared = await admin.put(connection, json={flag: True})
    assert cleared.status_code == 200, cleared.text
    assert await stored_row(app, field) is None
    assert getattr(app.state.sm_billing.settings, field) == ""
