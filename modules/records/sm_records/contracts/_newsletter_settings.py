"""The settings a newsletter contract write runs under, fetched by records itself (#336).

A caller passes its ``app`` (``None`` in a worker) instead of records' settings,
so it never reads ``app.state.sm_records`` or knows ``RecordsSettings``' fields.
"""

from __future__ import annotations

from typing import Any

from sm_records.core import constants
from sm_records.core.settings import RecordsSettings


def records_settings(app: Any | None) -> RecordsSettings:
    """Records' settings for one contract call.

    With an ``app``: the instance the host hydrated onto it, which is what
    records' own requests read (``web.deps.get_settings``), so a Settings-screen
    edit applies at once. With ``None`` — a worker, which never builds the app —
    the DB-backed read ``background_tasks`` gives workers, cached about 30 s.
    Without ``background_tasks`` there is no such read: ``RuntimeError``.
    """
    if app is not None:
        return app.state.sm_records.settings
    try:
        from background_tasks import settings_for
    except ImportError as exc:
        raise RuntimeError(
            "records' settings without an app are read through background_tasks "
            "(a worker); pass the app in a web process"
        ) from exc
    return settings_for(RecordsSettings, constants.PACKAGE)
