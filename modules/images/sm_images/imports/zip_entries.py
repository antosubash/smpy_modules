"""ZIP entries to import items: the root ``metadata.json`` and :func:`entry_item`.

**metadata.json** is applied as in the portal: an object keyed by filename,
each value the image's metadata. The portal's spelling (``latitude``,
``longitude``, ``external_metadata``) and this module's own (``lat``, ``lng``,
``properties``) are both accepted; unknown keys are ignored; a value out of
range or the wrong shape fails the whole job (``metadata_invalid``), as there.
An entry finds its record by its full path in the archive first, then by its
basename (the portal's key). Its ``external_source`` names the id's namespace
(the portal's dedupe key was the pair), with or without an id of its own;
without one it is ``import``.
Coordinates from it are a person's, so they are stored as ``manual``.

**Each entry is one item**, at ``feature_index`` = its place among the entries,
so a resumed run records the same rows and dedupes as a GeoJSON import does.
The external id is the metadata's, or ``sha256("<job>:<index>")`` - stable for
the job, so a replay finds what a killed run created, and two entries with one
name stay two images. A group comes from the metadata's ``group_key``, else
from the mapping's ``filename_pattern`` matched against the basename
(``filename_pattern``'s regex timeout applies).
"""

from __future__ import annotations

import json
import uuid
from collections.abc import Sequence
from typing import Annotated, Any

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    TypeAdapter,
    ValidationError,
    field_validator,
)

from sm_images import constants
from sm_images.imports.features import Parsed, base64_external_id
from sm_images.imports.filename_pattern import canonical_role, group_key, match_group
from sm_images.imports.mapping import Mapping, MappingError
from sm_images.imports.values import parse_datetime
from sm_images.imports.zip_eocd import ZipRejected
from sm_images.imports.zip_safety import Entry

__all__ = ["ZipMeta", "entry_item", "parse_metadata", "zip_mapping"]

Text = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class ZipMeta(BaseModel):
    model_config = ConfigDict(extra="ignore")

    lat: float | None = Field(
        default=None, ge=-90, le=90, validation_alias=AliasChoices("lat", "latitude")
    )
    lng: float | None = Field(
        default=None, ge=-180, le=180, validation_alias=AliasChoices("lng", "longitude")
    )
    captured_at: Any = None
    external_id: Annotated[Text, Field(max_length=constants.EXTERNAL_ID_MAX)] | None = None
    external_source: Annotated[Text, Field(max_length=constants.EXTERNAL_SOURCE_MAX)] | None = None
    group_key: Any = None
    group_role: Any = None
    properties: dict[str, Any] | None = Field(
        default=None, validation_alias=AliasChoices("properties", "external_metadata")
    )

    @field_validator("external_id", mode="before")
    @classmethod
    def _id_as_text(cls, value: object) -> object:
        if isinstance(value, int) and not isinstance(value, bool):
            return str(value)
        return value

    @field_validator("properties")
    @classmethod
    def _bounded(cls, value: dict[str, Any] | None) -> dict[str, Any] | None:
        if value is None:
            return None
        size = len(json.dumps(value, separators=(",", ":"), default=str).encode())
        if size > constants.PROPERTIES_MAX_BYTES:
            raise ValueError("properties is too large")
        return value


_DOC = TypeAdapter(dict[str, ZipMeta])


def parse_metadata(doc: Any) -> dict[str, ZipMeta]:
    try:
        return _DOC.validate_python(doc or {})
    except ValidationError as exc:
        raise ZipRejected("metadata_invalid") from exc


def zip_mapping(raw: dict[str, Any] | None) -> Mapping:
    """A ZIP import maps nothing but ``filename_pattern``; anything else is a
    mistake worth a 422 (``MappingError``)."""
    mapping = Mapping.model_validate(raw or {})
    if mapping.model_dump(exclude_none=True, exclude={"filename_pattern"}):
        raise MappingError("invalid_mapping")
    return mapping


def entry_item(
    entry: Entry,
    metadata: dict[str, ZipMeta],
    mapping: Mapping,
    job_id: uuid.UUID,
    roles: Sequence[str],
) -> Parsed:
    meta = metadata.get(entry.name) or metadata.get(entry.filename) or ZipMeta()
    parsed = Parsed(
        entry.index,
        external_id=meta.external_id or base64_external_id(job_id, entry.index),
        external_source=meta.external_source,
        filename=entry.filename[: constants.FILENAME_MAX],
        captured_at=parse_datetime(meta.captured_at),
        properties=meta.properties or None,
    )
    if meta.lat is not None and meta.lng is not None:
        parsed.lat, parsed.lng = meta.lat, meta.lng
    key = group_key(meta.group_key)
    if key is not None:
        parsed.group_key, parsed.group_role = key, canonical_role(meta.group_role, roles)
    elif mapping.filename_pattern:
        parsed.group_key, parsed.group_role = match_group(
            mapping.filename_pattern, entry.filename, roles
        )
    return parsed
