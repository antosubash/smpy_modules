"""Which GeoJSON properties feed which image field (``ImportJob.mapping``).

Every property is a name, or a dotted path into nested objects
(``meta.photo.url``); an exact key wins over the path. ``url_prop`` is required
for a URL import and ``image_prop`` (base64 data, a data URI allowed) for a
base64 one. Coordinates come from ``lat_prop``/``lng_prop`` when both are given
and valid, else from the feature's geometry. A group comes from
``group_key_prop`` (and ``group_role_prop``), else from ``filename_pattern``
matched against the image's filename.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from sm_images.ingest.imports.filename_pattern import (
    MAX_PATTERN_LENGTH,
    PatternError,
    compile_pattern,
)
from sm_images.models.enums import ImportKind

__all__ = ["GEOJSON_KINDS", "Mapping", "MappingError"]

GEOJSON_KINDS = (ImportKind.GEOJSON_URL, ImportKind.GEOJSON_BASE64)

Prop = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=200)]


class MappingError(ValueError):
    """The mapping cannot drive this kind of import; ``code`` says why."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class Mapping(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url_prop: Prop | None = None
    image_prop: Prop | None = None
    lat_prop: Prop | None = None
    lng_prop: Prop | None = None
    datetime_prop: Prop | None = None
    external_id_prop: Prop | None = None
    group_key_prop: Prop | None = None
    group_role_prop: Prop | None = None
    filename_pattern: str | None = Field(default=None, max_length=MAX_PATTERN_LENGTH)

    @field_validator("filename_pattern")
    @classmethod
    def _pattern(cls, value: str | None) -> str | None:
        if value is None or not value.strip():
            return None
        value = value.strip()
        try:
            compile_pattern(value)
        except PatternError as exc:
            raise ValueError(str(exc)) from exc
        return value

    def require(self, kind: ImportKind) -> Mapping:
        """Raise :class:`MappingError` unless this mapping can drive ``kind``."""
        if kind not in GEOJSON_KINDS:
            raise MappingError("unsupported_kind")
        if kind is ImportKind.GEOJSON_URL and self.url_prop is None:
            raise MappingError("url_prop_required")
        if kind is ImportKind.GEOJSON_BASE64 and self.image_prop is None:
            raise MappingError("image_prop_required")
        return self
