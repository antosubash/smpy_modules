"""Image request bodies (bounded) and responses (not: a stored row that predates
a bound must still serialise)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from sm_images.core import constants
from sm_images.ingest.meta import UploadMeta
from sm_images.models import LocationSource

_SOURCE_NAMES = {s: s.name.lower().rstrip("_") for s in LocationSource}

Filename = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=constants.FILENAME_MAX)
]


class StepRunOut(BaseModel):
    """One step's state for one image, with the output the result view renders."""

    step: str
    status: str
    step_version: int | None
    error_code: str | None
    error_message: str | None
    finished_at: datetime | None
    output: dict[str, Any] | None
    output_visible: bool = False
    """True when the caller may see ``output``/``error_message`` (an editor), so
    ``output is None`` then means the step produced none, not that it is withheld."""
    label: str | None = None
    """A prompt step's prompt name; ``None`` for a built-in step (the client
    names it) and for a deleted prompt (the step id is the fallback)."""
    answer: dict[str, Any] | None = None
    """A prompt step's answer: ``{"data", "text"}`` (``services.prompt_answers``)."""


class ImageOut(BaseModel):
    id: uuid.UUID
    collection_id: uuid.UUID
    filename: str
    content_type: str
    size_bytes: int
    width: int | None
    height: int | None
    sha256: str | None
    has_display: bool
    lat: float | None
    lng: float | None
    location_source: str | None
    captured_at: datetime | None
    camera_make: str | None
    camera_model: str | None
    external_source: str | None
    external_id: str | None
    properties: dict[str, Any] | None
    group_id: uuid.UUID | None
    group_role: str | None
    created_at: datetime | None
    created_by: str | None
    thumb_url: str | None = None
    """The versioned ``small`` rendition (``sm_images.serving.urls``); ``None`` until the
    pipeline has produced one for the current display copy."""
    display_url: str | None = None
    """The versioned display copy; the original's bytes when there is none."""
    group_key: str | None = None
    """Only on the detail response: the key of the group ``group_id`` names."""
    step_runs: list[StepRunOut] | None = None
    """Only on the detail response (``present_detail``); lists leave it ``None``."""

    @classmethod
    def from_row(
        cls, row: Any, *, thumb_url: str | None = None, display_url: str | None = None
    ) -> ImageOut:
        source = row.location_source
        return cls(
            **{name: getattr(row, name) for name in _PLAIN},
            has_display=row.display_key is not None,
            location_source=None if source is None else _SOURCE_NAMES[LocationSource(source)],
            thumb_url=thumb_url,
            display_url=display_url,
        )


_COMPUTED = {
    "has_display",
    "location_source",
    "thumb_url",
    "display_url",
    "group_key",
    "step_runs",
}
_PLAIN = tuple(name for name in ImageOut.model_fields if name not in _COMPUTED)


class ImagePageOut(BaseModel):
    items: list[ImageOut]
    next_cursor: str | None
    total: int | None


class UploadResult(BaseModel):
    """One file's outcome. ``status`` is ``created`` or ``duplicate`` with the
    image ``id``; in a batch a refused file is ``error`` with ``code``/``detail``."""

    filename: str | None = None
    status: Literal["created", "duplicate", "error"]
    id: uuid.UUID | None = None
    code: str | None = None
    detail: str | None = None


class BatchOut(BaseModel):
    results: list[UploadResult]


class Base64Upload(UploadMeta):
    """``data`` is plain base64 or a ``data:image/...;base64,`` URL. Its length is
    bounded by the request body limit and checked against ``max_image_bytes``
    before decoding."""

    filename: Filename | None = None
    data: str


class DirectCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    filename: Filename
    size: int = Field(ge=1)
    content_type: str | None = Field(default=None, max_length=100)


class DirectCreated(BaseModel):
    upload_id: str
    """Opaque and signed; every later call names it."""
    part_size: int
    part_urls: list[str]
    """One per part, in order. Presigned (PUT straight to storage) or, on a backend
    that cannot presign, this app's relay route."""
    direct: bool
    expires_in: int


class PartIn(BaseModel):
    no: int = Field(ge=1)
    etag: str | None = Field(default=None, max_length=200)


class PartOut(BaseModel):
    no: int
    etag: str
    size: int


class DirectComplete(BaseModel):
    model_config = ConfigDict(extra="forbid")

    parts: list[PartIn] = Field(default_factory=list, max_length=constants.DIRECT_MAX_PARTS)
    filename: Filename | None = None
    metadata: UploadMeta | None = None


class ImagePatch(BaseModel):
    """Edit an image: its manual location (``lat`` and ``lng`` together, ``null``
    clears) and/or its group (``group_id``, ``null`` leaves the group and so the
    role) and ``group_role``. Only the fields sent change."""

    model_config = ConfigDict(extra="forbid")

    lat: float | None = Field(default=None, ge=-90, le=90)
    lng: float | None = Field(default=None, ge=-180, le=180)
    group_id: uuid.UUID | None = None
    group_role: str | None = Field(default=None, max_length=constants.GROUP_ROLE_MAX)
