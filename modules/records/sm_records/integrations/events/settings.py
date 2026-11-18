"""The ``records:dates`` source's settings, and their check against the real record types.

A mapping names a type, an indexed date or datetime field of it and, optionally, an end field of
the same kind. Settings are stored in the clear on the calendar, so nothing here is a secret.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field
from sm_events.contracts.extensions import SettingsContext, SourceSettingsError, SourceViewer

from sm_records.contracts.dated import DatedCaller
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
    """Every mapping must name a type the caller may read and indexed date fields of one kind.
    A type that does not exist and one the caller may not read give the same message. A mapping
    ``restore_settings`` put back from what is stored (``sctx.preserved``) is not judged: the
    caller could not see it."""
    from sm_records.integrations.events.visibility import UNAVAILABLE, readable_types

    types = await readable_types(sctx.db, sctx.tenant_id, _required(sctx.viewer))
    for index, mapping in enumerate(settings.mappings):
        where = ("mappings", index)
        if where in sctx.preserved:
            continue
        found = types.get(mapping.type_key)
        if found is None:
            raise SourceSettingsError((*where, "type_key"), UNAVAILABLE, "type_unavailable")
        declared, dated = found
        for name in ("field", "end_field"):
            value = getattr(mapping, name)
            if value is None:
                continue
            if value not in declared:
                raise SourceSettingsError(
                    (*where, name), "This field no longer exists on this type", "field_missing"
                )
            if value not in dated:
                raise SourceSettingsError(
                    (*where, name),
                    "Choose an indexed date or date-time field of this type",
                    "field_not_date",
                )
        if mapping.end_field is None:
            continue
        if mapping.end_field == mapping.field:
            raise SourceSettingsError(
                (*where, "end_field"), "The end must be another field", "end_same"
            )
        if dated[mapping.end_field] != dated[mapping.field]:
            raise SourceSettingsError(
                (*where, "end_field"),
                "The end must be an indexed field of the same kind",
                "end_kind",
            )


def _required(viewer: SourceViewer) -> DatedCaller:
    caller = caller_of(viewer)
    assert caller is not None
    return caller
