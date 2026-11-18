"""The ``records:dates`` source's settings, and their check against the real record types.

A mapping names a type, an indexed date or datetime field of it and, optionally, an end field of
the same kind. Settings are stored in the clear on the calendar, so nothing here is a secret.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field
from sm_events.contracts.extensions import SettingsContext, SourceSettingsError, SourceViewer

from sm_records.contracts.dated import DatedCaller, dated_types
from sm_records.core import constants

__all__ = ["RecordDateMapping", "RecordDatesSettings", "caller_of", "check_settings"]

MAPPINGS_MAX = 5
DURATION_MAX_MINUTES = 1440


class RecordDateMapping(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type_key: Annotated[str, Field(min_length=1, max_length=constants.MAX_KEY_LEN)]
    field: Annotated[str, Field(min_length=1, max_length=constants.MAX_KEY_LEN)]
    end_field: Annotated[str, Field(min_length=1, max_length=constants.MAX_KEY_LEN)] | None = None
    duration_minutes: Annotated[int, Field(ge=1, le=DURATION_MAX_MINUTES)] = 60
    """How long a timed record lasts when it has no usable end."""
    color: Annotated[str, Field(pattern=r"^#[0-9a-f]{6}$")] | None = None


class RecordDatesSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mappings: Annotated[list[RecordDateMapping], Field(min_length=1, max_length=MAPPINGS_MAX)]


def caller_of(viewer: SourceViewer | None) -> DatedCaller | None:
    """``None`` (the public) for no viewer, else the person as records' own rules see them."""
    if viewer is None:
        return None
    return DatedCaller(viewer.roles, viewer.permissions, viewer.role_map)


async def check_settings(sctx: SettingsContext, settings: RecordDatesSettings) -> None:
    """Every mapping must name a type the admin may read and indexed date fields of one kind.
    A type that does not exist and one the admin may not read give the same message."""
    types = {
        t.key: t
        for t in await dated_types(sctx.db, tenant_id=sctx.tenant_id, caller=_required(sctx.viewer))
    }
    for index, mapping in enumerate(settings.mappings):
        where = ("mappings", index)
        found = types.get(mapping.type_key)
        if found is None:
            raise SourceSettingsError(
                (*where, "type_key"), "That record type does not exist, or you may not read it"
            )
        kinds = {key: kind for key, _label, kind in found.fields}
        if mapping.field not in kinds:
            raise SourceSettingsError(
                (*where, "field"), "Choose an indexed date or date-time field of this type"
            )
        if mapping.end_field is None:
            continue
        if mapping.end_field == mapping.field:
            raise SourceSettingsError((*where, "end_field"), "The end must be another field")
        if kinds.get(mapping.end_field) != kinds[mapping.field]:
            raise SourceSettingsError(
                (*where, "end_field"), "The end must be an indexed field of the same kind"
            )


def _required(viewer: SourceViewer) -> DatedCaller:
    caller = caller_of(viewer)
    assert caller is not None
    return caller
