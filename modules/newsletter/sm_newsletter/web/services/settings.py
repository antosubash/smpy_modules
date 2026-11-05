"""Writing the SMTP password: encrypt, persist through the settings store, hot-swap.

The generic Settings screen refuses newsletter writes (the module registers a
``manage_url``), so this is the only path that stores ``smtp_password``, and it
only ever stores ciphertext.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession

from sm_newsletter.core import constants, crypto
from sm_newsletter.core.settings import NewsletterSettings
from sm_newsletter.web.schemas.settings import SERVER_FIELDS, SettingsOut


async def set_smtp_password(app: FastAPI, db: AsyncSession, password: str) -> None:
    """Persist ``password`` encrypted and hot-swap the live settings."""
    # Plugin imports (settings is a declared dependency), local as ai's are.
    from settings.reload import apply_changes_and_reload
    from settings.service import SettingService
    from settings.store import SettingsStore
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


def read_settings(app: FastAPI) -> SettingsOut:
    """The live settings as the API shows them: the password only as a flag."""
    current = app.state.sm_newsletter.settings
    data = current.model_dump(exclude={"smtp_password"})
    return SettingsOut(**data, has_password=bool(current.smtp_password))


async def update_settings(app: FastAPI, db: AsyncSession, changes: dict[str, Any]) -> bool:
    """Persist ``changes`` and hot-swap; True when the stored password was cleared.

    The merged values are validated as :class:`NewsletterSettings` first. A
    changed server field clears ``smtp_password`` in the same write (R10), so
    the credential is never presented to a server it was not saved for."""
    from settings.reload import apply_changes_and_reload
    from settings.service import SettingService
    from settings.store import SettingsStore
    from simple_module_db import finalize_session

    current = app.state.sm_newsletter.settings
    NewsletterSettings.model_validate({**current.model_dump(), **changes})
    changed = {k: v for k, v in changes.items() if getattr(current, k) != v}
    cleared = bool(current.smtp_password) and any(f in changed for f in SERVER_FIELDS)
    if cleared:
        changed["smtp_password"] = ""
    if changed:
        store = SettingsStore(SettingService(db))
        await apply_changes_and_reload(
            app, app.state.sm.event_bus, store, package=constants.PACKAGE, changes=changed
        )
        await finalize_session(db)
    return cleared
