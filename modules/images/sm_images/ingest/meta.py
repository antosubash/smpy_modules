"""Per-image metadata: the validated wire shape and the service's own record.

:class:`UploadMeta` is what a client sends (a multipart batch's ``metadata``
field keyed by filename, a base64 body, a direct upload's ``complete``). It is
validated *before* anything is stored. :class:`IngestMeta` is what
``IngestService.add_image`` takes from every path, imports included.

A lone latitude or longitude stores no location (the portal's
``test_upload_with_only_latitude_stores_no_location``); ``(0, 0)`` is a valid
location.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Annotated, Any

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    TypeAdapter,
    ValidationError,
    field_validator,
)

from sm_images.core import constants
from sm_images.core.errors import InvalidUpload
from sm_images.models.enums import LocationSource

__all__ = ["IngestMeta", "UploadMeta", "parse_batch_metadata"]

_BAD_METADATA = "The image metadata is not valid"

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


def external_id_text(value: object) -> object:
    """An integer external id as text. Integer ids are common in exports;
    booleans are not ids."""
    if isinstance(value, int) and not isinstance(value, bool):
        return str(value)
    return value


def properties_fit(value: dict[str, Any]) -> bool:
    """Whether ``properties`` serialise within ``PROPERTIES_MAX_BYTES``."""
    size = len(json.dumps(value, separators=(",", ":"), default=str).encode())
    return size <= constants.PROPERTIES_MAX_BYTES


@dataclass(frozen=True)
class IngestMeta:
    lat: float | None = None
    lng: float | None = None
    captured_at: datetime | None = None
    external_source: str | None = None
    external_id: str | None = None
    group_key: str | None = None
    group_role: str | None = None
    properties: dict[str, Any] | None = field(default=None)
    location_source: LocationSource | None = None
    """Where ``lat``/``lng`` came from; ``None`` = the caller typed them (``manual``)."""

    @property
    def located(self) -> bool:
        return self.lat is not None and self.lng is not None


class UploadMeta(BaseModel):
    model_config = ConfigDict(extra="forbid")

    lat: float | None = Field(default=None, ge=-90, le=90)
    lng: float | None = Field(default=None, ge=-180, le=180)
    captured_at: datetime | None = None
    external_source: Annotated[Text, Field(max_length=constants.EXTERNAL_SOURCE_MAX)] | None = None
    external_id: Annotated[Text, Field(max_length=constants.EXTERNAL_ID_MAX)] | None = None
    group_key: Annotated[Text, Field(max_length=constants.GROUP_KEY_MAX)] | None = None
    group_role: Annotated[Text, Field(max_length=constants.GROUP_ROLE_MAX)] | None = None
    properties: dict[str, Any] | None = None

    @field_validator("external_id", mode="before")
    @classmethod
    def _id_as_text(cls, value: object) -> object:
        return external_id_text(value)

    @field_validator("properties")
    @classmethod
    def _bounded(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        if value is not None and not properties_fit(value):
            raise ValueError("properties is too large")
        return value

    def to_ingest(self) -> IngestMeta:
        located = self.lat is not None and self.lng is not None
        captured = self.captured_at
        if captured is not None and captured.tzinfo is None:
            captured = captured.replace(tzinfo=UTC)
        return IngestMeta(
            lat=self.lat if located else None,
            lng=self.lng if located else None,
            captured_at=captured,
            external_source=self.external_source,
            external_id=self.external_id,
            group_key=self.group_key,
            group_role=self.group_role,
            properties=self.properties,
        )


_BATCH = TypeAdapter(dict[str, UploadMeta])


def parse_batch_metadata(raw: str | None) -> dict[str, IngestMeta]:
    """The multipart ``metadata`` field: ``{filename: {...}}``, all or nothing."""
    if not raw:
        return {}
    if len(raw.encode()) > constants.METADATA_MAX_BYTES:
        raise InvalidUpload(_BAD_METADATA, constants.CODE_INVALID_METADATA)
    try:
        parsed = _BATCH.validate_json(raw)
    except ValidationError as exc:
        raise InvalidUpload(_BAD_METADATA, constants.CODE_INVALID_METADATA) from exc
    return {name: meta.to_ingest() for name, meta in parsed.items()}


def normalise(meta: IngestMeta, source: str) -> IngestMeta:
    """An external id always has a source: a NULL source never dedupes."""
    changes: dict[str, Any] = {}
    if meta.external_id is not None and meta.external_source is None:
        changes["external_source"] = source
    if meta.location_source is None:
        changes["location_source"] = LocationSource.MANUAL
    return replace(meta, **changes) if changes else meta
