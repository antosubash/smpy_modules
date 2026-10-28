"""Enumerations stored by the images tables.

String enums are stored through ``SAEnum`` (a native type on Postgres, a
VARCHAR on SQLite), the way records stores ``RecordStatus``. ``LocationSource``
is the exception: it is a precedence, and SQL has to compare it
(``WHERE location_source < :incoming``), so it is a small integer.
"""

from __future__ import annotations

import enum


class Visibility(str, enum.Enum):  # noqa: UP042
    PRIVATE = "private"
    INTERNAL = "internal"
    PUBLIC = "public"


class LocationSource(enum.IntEnum):
    """Where a coordinate came from. A higher value is never overwritten by a lower one."""

    EXIF = 1
    IMPORT_ = 2
    MANUAL = 3


class StepStatus(str, enum.Enum):  # noqa: UP042
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    SKIPPED = "skipped"
    FAILED = "failed"


class ReviewStatus(str, enum.Enum):  # noqa: UP042
    UNREVIEWED = "unreviewed"
    ACCEPTED = "accepted"
    CORRECTED = "corrected"
    REJECTED = "rejected"


class ImportKind(str, enum.Enum):  # noqa: UP042
    GEOJSON_URL = "geojson_url"
    GEOJSON_BASE64 = "geojson_base64"
    ZIP = "zip"


class JobStatus(str, enum.Enum):  # noqa: UP042
    UPLOADING = "uploading"
    """A ZIP import waiting for its archive; ``extract`` seals it (``running``)."""
    PENDING = "pending"
    STAGING = "staging"
    RUNNING = "running"
    PAUSED = "paused"
    RESETTING = "resetting"
    """A restart or retry-failed is resetting items (``ImportJob.reset_mode``)."""
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ItemStatus(str, enum.Enum):  # noqa: UP042
    PENDING = "pending"
    DONE = "done"
    DUPLICATE = "duplicate"
    FAILED = "failed"


class PromptScope(str, enum.Enum):  # noqa: UP042
    IMAGE = "image"
    GROUP = "group"


class UploadStatus(str, enum.Enum):  # noqa: UP042
    """A direct upload's lifecycle (``images_upload_session``). Leaving ``open``
    is a claim: whoever moves a session to ``completing`` or ``aborted`` owns it."""

    OPEN = "open"
    COMPLETING = "completing"
    COMPLETED = "completed"
    ABORTED = "aborted"


class PromptInputs(str, enum.Enum):  # noqa: UP042
    IMAGES = "images"
    RESULTS = "results"
    BOTH = "both"
