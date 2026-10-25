"""``_schema.normalise`` plus the one check it cannot make synchronously.

A proposed schema's patterned defaults are matched in the pattern worker
(``services._patterns.check_defaults``), never on the event loop. Every type
create, update, rollback and schema preview or apply calls this instead of
``normalise`` directly.
"""

from __future__ import annotations

from typing import Any

from sm_records.services._patterns import check_defaults
from sm_records.services._schema import normalise
from sm_records.settings import RecordsSettings

__all__ = ["normalise_checked"]


async def normalise_checked(
    fields_raw: list[dict[str, Any]], settings: RecordsSettings, *, kind: str | None = None
) -> Any:
    defs, fields = normalise(fields_raw, settings, kind=kind)
    await check_defaults(defs)
    return defs, fields
