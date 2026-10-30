"""The direct-upload ticket: what the signed ``upload_id`` carries.

Signed with the host's ``secret_key`` (``itsdangerous``), **not encrypted**:
the fields are readable base64 JSON, and the token appears in relay part URLs
and so in access logs. Altering or forging it is what is prevented. A tampered,
expired, foreign-tenant or other user's token is a 404 like an unknown one.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import PurePosixPath

from itsdangerous import BadData, URLSafeTimedSerializer

from sm_images.core import constants
from sm_images.core.errors import (
    DirectUploadUnsupported,
    InvalidUpload,
    UnsupportedType,
    UploadNotFound,
)
from sm_images.ingest.sniff import EXTENSIONS
from sm_images.tenancy import bound_tenant

__all__ = ["Ticket", "declared_type", "load_ticket", "serializer"]

_GONE = "Upload not found"
_NO_SECRET = "Direct uploads need the host's secret_key"
_BAD_PART = "A part is missing or has the wrong size"
_BAD_TYPE = "The upload is not a supported image of the declared type"


@dataclass(frozen=True)
class Ticket:
    session: str
    """The ``images_upload_session`` row's id: the state, which this handle only names."""
    key: str
    upload: str
    collection: str
    image: str
    tenant: str
    owner: str
    size: int
    part_size: int
    filename: str
    content_type: str
    kind: str = "image"
    """``image`` (completed by ``/complete``) or ``zip`` (sealed by its import's
    ``extract``; ``/complete`` refuses it)."""

    @property
    def parts(self) -> int:
        return math.ceil(self.size / self.part_size)

    def part_bytes(self, no: int) -> int:
        if not 1 <= no <= self.parts:
            raise InvalidUpload(_BAD_PART, constants.CODE_PARTS_MISMATCH)
        return self.part_size if no < self.parts else self.size - (self.parts - 1) * self.part_size


def serializer(secret: str) -> URLSafeTimedSerializer:
    if not secret:
        raise DirectUploadUnsupported(_NO_SECRET)
    return URLSafeTimedSerializer(secret, salt=constants.DIRECT_TOKEN_SALT)


def load_ticket(token: str, *, secret: str, owner: str | None) -> Ticket:
    """The signed ticket, if it is this caller's, in the bound tenant, and unexpired."""
    try:
        raw = serializer(secret).loads(token, max_age=constants.DIRECT_UPLOAD_TTL_SECONDS)
        ticket = Ticket(**raw)
    except (BadData, TypeError) as exc:
        raise UploadNotFound(_GONE) from exc
    if owner is None or ticket.owner != owner or ticket.tenant != bound_tenant():
        raise UploadNotFound(_GONE)
    return ticket


def declared_type(filename: str, content_type: str | None) -> str:
    """The accepted type the client declared (content type, else extension); 415 if none."""
    if content_type in EXTENSIONS:
        return content_type
    suffix = PurePosixPath(filename).suffix.lower().lstrip(".")
    by_ext = {ext: ctype for ctype, ext in EXTENSIONS.items()}
    by_ext |= {"jpeg": "image/jpeg", "tiff": "image/tiff", "heif": "image/heif"}
    # Browsers send octet-stream for types they do not know (HEIC): the extension
    # decides, and ``complete`` holds the sniffed bytes to that type.
    if content_type in (None, "application/octet-stream") and suffix in by_ext:
        return by_ext[suffix]
    raise UnsupportedType(_BAD_TYPE)
