"""Writing the SMTP password: encrypt, persist through the settings store, hot-swap.

The generic Settings screen refuses newsletter writes (the module registers a
``manage_url``), so this is the only path that stores ``smtp_password``, and it
only ever stores ciphertext.
"""

from __future__ import annotations

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession

from sm_newsletter.core import constants, crypto


async def set_smtp_password(app: FastAPI, db: AsyncSession, password: str) -> None:
    """Persist ``password`` encrypted and hot-swap the live settings."""
    # Plugin imports (settings is a declared dependency), local as ai's are.
    from settings.core.service import SettingService
    from settings.module_settings.reload import apply_changes_and_reload
    from settings.module_settings.store import SettingsStore
    from simple_module_db import finalize_session

    store = SettingsStore(SettingService(db))
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
