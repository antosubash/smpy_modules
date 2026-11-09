#!/usr/bin/env python
"""Run one bounded analytics retention sweep from the repository root."""

import asyncio

from headless_settings import headless_settings
from settings.core.service import SettingService
from settings.module_settings.store import SettingsStore
from simple_module_core.settings_hydrate import hydrate_settings
from simple_module_hosting import create_app
from sm_analytics.core.settings import AnalyticsSettings


async def run() -> int:
    app = create_app(headless_settings())
    state = app.state.sm_analytics
    try:
        async with app.state.sm.db.session_factory() as db:
            state.settings = await hydrate_settings(
                AnalyticsSettings, SettingsStore(SettingService(db)), "sm_analytics"
            )
        count = await state.sweep(app.state.sm.db.session_factory)
        print(f"Deleted {count} expired analytics events (up to 5000 per tenant).")
        return 0
    finally:
        await state.stop()
        await app.state.sm.db.engine.dispose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(run()))
