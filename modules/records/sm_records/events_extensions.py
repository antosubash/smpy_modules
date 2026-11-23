"""Registers records' sources with the events module, when it is installed and loads this file.

The events loader finds this file by name (it is the package's ``events_extensions``) and calls
``register``. Nothing of events is imported until then: records installs and runs without it,
and this file is the only place the optional integration is reached from.
"""

from __future__ import annotations

from typing import Any


def register(registry: Any) -> None:
    from sm_records.integrations.events.registration_provider import provider
    from sm_records.integrations.events.source import RecordDatesSource

    registry.add_source(RecordDatesSource())
    registry.add_registration_provider(provider())
