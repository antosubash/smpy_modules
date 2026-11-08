"""Request and response bodies of the campaigns API.

Submitted text that ends up in a mail header (subject, preheader, from name,
reply-to) refuses line breaks and control characters (ruling C6). Routes
validate through :func:`parse_payload`, whose 422 names the field and never the
value: FastAPI's own validation error would echo the input back.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any

from pydantic import (
    AfterValidator,
    BaseModel,
    BeforeValidator,
    ConfigDict,
    EmailStr,
    Field,
    StrictInt,
    ValidationError,
    field_validator,
    model_validator,
)

from sm_newsletter.campaigns.lifecycle import split_paused
from sm_newsletter.content.merge import check_merge, check_no_capability
from sm_newsletter.core.constants import MAX_AUDIENCE_LEN, MAX_TYPE_KEY_LEN
from sm_newsletter.core.errors import InvalidCampaign, NewsletterError
from sm_newsletter.core.headers import check_header_text


def _header(field: str) -> AfterValidator:
    return AfterValidator(lambda v: v if v is None else check_header_text(v, field=field))


def _merge(value: str | None) -> str | None:
    if value is not None:
        check_merge(value)
    return value


def _no_capability(field: str) -> AfterValidator:
    return AfterValidator(lambda v: v if v is None else check_no_capability(v, field=field))


def _blank_is_none(value: Any) -> Any:
    return None if isinstance(value, str) and not value.strip() else value


def _not_blank(value: str) -> str:
    if not value.strip():
        raise ValueError("must not be blank")
    return value


Name = Annotated[str, Field(min_length=1, max_length=200), AfterValidator(_not_blank)]
ListKey = Annotated[str, Field(min_length=1, max_length=MAX_TYPE_KEY_LEN)]
# Merge fields follow the body's rule: an unknown or malformed ``{{…}}`` is refused,
# and so is one that carries a send token (amendment A7).
Subject = Annotated[
    str,
    Field(max_length=300),
    _header("subject"),
    AfterValidator(_merge),
    _no_capability("subject"),
]
Preheader = Annotated[
    str,
    Field(max_length=300),
    _header("preheader"),
    AfterValidator(_merge),
    _no_capability("preheader"),
]
FromName = Annotated[str | None, Field(max_length=200), _header("from_name")]
# Checked for control characters before the address parser sees it.
ReplyTo = Annotated[
    EmailStr | None,
    BeforeValidator(_blank_is_none),
    BeforeValidator(lambda v: check_header_text(v, field="reply_to") if isinstance(v, str) else v),
]


class CampaignCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: Name
    list_type_key: ListKey
    subject: Subject = ""
    preheader: Preheader = ""


# Columns that are ``NOT NULL``: a PATCH may leave them out, never null them.
_NOT_NULL = ("name", "subject", "preheader", "list_type_key", "audience", "body")


class CampaignPatch(BaseModel):
    """Only the fields sent are written; ``expected_revision`` is the revision
    the editor read (409 ``stale`` when the campaign moved on)."""

    model_config = ConfigDict(extra="forbid")

    expected_revision: StrictInt
    name: Name | None = None
    subject: Subject | None = None
    preheader: Preheader | None = None
    from_name: FromName = None
    reply_to: ReplyTo = None
    list_type_key: ListKey | None = None
    audience: Annotated[str, Field(min_length=1, max_length=MAX_AUDIENCE_LEN)] | None = None
    body: Any = None
    """Validated by the service with ``parse_body`` (422 ``invalid_body``)."""

    @field_validator(*_NOT_NULL, mode="before")
    @classmethod
    def _not_null(cls, value: Any) -> Any:
        # Runs only for a field that was sent: defaults are not validated.
        if value is None:
            raise ValueError("must not be null")
        return value

    def changes(self) -> dict[str, Any]:
        """The fields sent, minus ``expected_revision``."""
        return self.model_dump(exclude_unset=True, exclude={"expected_revision", "body"}) | (
            {"body": self.body} if "body" in self.model_fields_set else {}
        )


class CampaignSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    subject: str
    status: str
    list_type_key: str
    revision: int
    updated_at: datetime | None
    recipient_count: int
    sent_count: int
    started_at: datetime | None
    finished_at: datetime | None


class CampaignDetail(CampaignSummary):
    preheader: str
    from_name: str | None
    reply_to: str | None
    audience: str
    body: list[dict[str, Any]]
    scheduled_at: datetime | None
    paused_code: str | None
    paused_detail: str | None
    failed_count: int
    bounced_count: int
    suppressed_count: int
    unsubscribe_count: int

    @model_validator(mode="before")
    @classmethod
    def _split_paused(cls, data: Any) -> Any:
        """The stored ``"<code>|<detail>"`` reason as two fields (ruling S13)."""
        if isinstance(data, dict) or not hasattr(data, "paused_reason"):
            return data
        code, detail = split_paused(data.paused_reason)
        own = {n: getattr(data, n) for n in cls.model_fields if hasattr(data, n)}
        return own | {"paused_code": code, "paused_detail": detail}


class CampaignListItem(CampaignSummary):
    """A list row: unique opens and clicks of ``sent`` rows (B5), which only the
    list computes (the detail has no such field)."""

    opens_unique_accepted: int = 0
    clicks_unique_accepted: int = 0


class CampaignPage(BaseModel):
    items: list[CampaignListItem]
    total: int


def parse_payload[M: BaseModel](
    model: type[M], raw: object, *, error: type[NewsletterError] = InvalidCampaign
) -> M:
    """``model`` from a request body, or :class:`InvalidCampaign` naming the
    field and the error type - never pydantic's message or input, which can
    quote the value."""
    try:
        return model.model_validate(raw)
    except ValidationError as exc:
        err = exc.errors(include_input=False, include_url=False, include_context=False)[0]
        loc = err["loc"]
        # An unknown key is the client's text too: named only when it is a field.
        field = str(loc[0]) if loc and loc[0] in model.model_fields else "payload"
        reason = "invalid value" if err["type"] == "value_error" else err["type"]
        raise error(f"{field}: {reason}") from None
