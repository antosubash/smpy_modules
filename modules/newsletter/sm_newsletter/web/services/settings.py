"""Writing the SMTP password: encrypt, persist through the settings store, hot-swap.

The generic Settings screen refuses newsletter writes (the module registers a
``manage_url``), so this is the only path that stores ``smtp_password``, and it
only ever stores ciphertext.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from simple_module_core.settings_hydrate import hydrate_settings
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from sm_newsletter.core import constants, crypto
from sm_newsletter.core.settings import NewsletterSettings
from sm_newsletter.web.schemas.settings import SERVER_FIELDS, SettingsOut

# Arbitrary fixed key for the Postgres advisory lock that orders settings writes.
_WRITE_LOCK_KEY = 7_204_117_302


@asynccontextmanager
async def _serialized_writes(app: FastAPI, db: AsyncSession) -> AsyncIterator[None]:
    """One settings write at a time, from reading the stored state to the commit.

    The relay write decides whether to clear the password from what is stored, so
    a password write that commits in between would survive a change of server and
    be sent to the new host. Within a process an ``asyncio.Lock`` orders the
    writers (SQLite, a single process); on Postgres a transaction-scoped advisory
    lock does it across workers and is released by the commit the caller makes
    before leaving the block.
    """
    lock = getattr(app.state, "sm_newsletter_write_lock", None)
    if lock is None:
        lock = app.state.sm_newsletter_write_lock = asyncio.Lock()
    async with lock:
        bind = db.get_bind()
        if bind.dialect.name == "postgresql":
            await db.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _WRITE_LOCK_KEY})
        yield


async def set_smtp_password(app: FastAPI, db: AsyncSession, password: str) -> None:
    """Persist ``password`` encrypted and hot-swap the live settings."""
    # Plugin imports (settings is a declared dependency), local as ai's are.
    from settings.reload import apply_changes_and_reload
    from settings.service import SettingService
    from settings.store import SettingsStore
    from simple_module_db import finalize_session

    store = SettingsStore(SettingService(db))
    async with _serialized_writes(app, db):
        await apply_changes_and_reload(
            app,
            app.state.sm.event_bus,
            store,
            package=constants.PACKAGE,
            changes={"smtp_password": crypto.encrypt_value(password)},
        )
        # The reload runs after the commit; commit now so the live settings carry
        # the new value when the response is built.
        await finalize_session(db)


def read_settings(app: FastAPI) -> SettingsOut:
    """The live settings as the API shows them: the password only as a flag."""
    current = app.state.sm_newsletter.settings
    data = current.model_dump(exclude={"smtp_password"})
    return SettingsOut(**data, has_password=bool(current.smtp_password))


async def update_settings(app: FastAPI, db: AsyncSession, changes: dict[str, Any]) -> bool:
    """Persist ``changes`` and hot-swap; True when a stored password was cleared.

    The merged values are validated as :class:`NewsletterSettings` first. A
    changed server field clears ``smtp_password`` in the same write (R10), so
    the credential is never presented to a server it was not saved for. The
    comparison is against the *stored* settings, read under the write lock, not
    the live copy, and the clear is unconditional on a relay change."""
    from settings.reload import apply_changes_and_reload
    from settings.service import SettingService
    from settings.store import SettingsStore
    from simple_module_db import finalize_session

    store = SettingsStore(SettingService(db))
    async with _serialized_writes(app, db):
        current = await hydrate_settings(NewsletterSettings, store, constants.PACKAGE, lenient=True)
        NewsletterSettings.model_validate({**current.model_dump(), **changes})
        changed = {k: v for k, v in changes.items() if getattr(current, k) != v}
        moved = any(f in changed for f in SERVER_FIELDS)
        cleared = moved and bool(current.smtp_password)
        if moved:
            changed["smtp_password"] = ""
        if changed:
            await apply_changes_and_reload(
                app, app.state.sm.event_bus, store, package=constants.PACKAGE, changes=changed
            )
            await finalize_session(db)
    return cleared
