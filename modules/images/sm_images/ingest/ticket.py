"""The direct-upload ticket: what the signed ``upload_id`` carries.

Signed with the host's ``secret_key`` (``itsdangerous``), **not encrypted**:
the fields are readable base64 JSON, and the token appears in relay part URLs
and so in access logs. Altering or forging it is what is prevented. A tampered,
expired, foreign-tenant or other user's token is a 404 like an unknown one.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from itsdangerous import BadData, URLSafeTimedSerializer

from sm_images import constants
from sm_images.errors import DirectUploadUnsupported, InvalidUpload, UploadNotFound
from sm_images.tenancy import bound_tenant

__all__ = ["Ticket", "load_ticket", "serializer"]

_GONE = "Upload not found"
_NO_SECRET = "Direct uploads need the host's secret_key"
_BAD_PART = "A part is missing or has the wrong size"


@dataclass(frozen=True)
class Ticket:
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
