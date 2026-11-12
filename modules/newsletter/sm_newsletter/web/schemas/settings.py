"""Request and response bodies of the settings API."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, EmailStr, Field, field_validator

from sm_newsletter.core.constants import MAX_EMAIL_LEN
from sm_newsletter.core.headers import check_header_text

# Changing where the relay is, or who logs in to it, clears the stored password:
# otherwise the credential could be sent to a server of the caller's choosing.
SERVER_FIELDS = ("smtp_host", "smtp_port", "smtp_security", "smtp_username")

# Input bounds only; ``SettingsOut`` stays unbounded so a stored value never 500s.
MAX_HOST = 253
MAX_USERNAME = MAX_EMAIL_LEN  # a login is often the address
MAX_FROM_NAME = 200
MAX_PHYSICAL_ADDRESS = 500
MAX_EXTRA_TEST_RECIPIENTS = 20


def _normalised_list(value: Any) -> Any:
    """Stripped, lower-cased, deduplicated (first wins) before validation."""
    if not isinstance(value, list):
        return value
    out: list[Any] = []
    for item in value:
        if isinstance(item, str):
            item = check_header_text(item.strip(), field="test_send_extra_recipients").lower()
        if item not in out:
            out.append(item)
    return out


Address = Annotated[EmailStr, Field(max_length=MAX_EMAIL_LEN)]


class SmtpPasswordUpdate(BaseModel):
    """Unconstrained on purpose: a validation error would echo the submitted
    value (``input``) back. The handler validates and never repeats it."""

    password: str


class SmtpPasswordOut(BaseModel):
    """Whether a password is stored; the value itself is never returned."""

    has_password: bool


class SettingsOut(BaseModel):
    """Every setting but the password, which is only ever reported as present."""

    transport: Literal["smtp", "console"]
    smtp_host: str
    smtp_port: int
    smtp_security: Literal["starttls", "tls"]
    smtp_username: str
    has_password: bool
    from_address: str
    from_name: str
    reply_to: str
    daily_limit: int
    per_minute_limit: int
    tracking_opens: bool
    tracking_clicks: bool
    physical_address: str
    test_send_extra_recipients: list[str]


class SettingsSaved(SettingsOut):
    password_cleared: bool


class SettingsUpdate(BaseModel):
    """A partial update. ``smtp_password`` is not a field and extra keys are
    refused, so it cannot be written here. Routes validate through
    ``parse_payload`` (a 422 that never echoes the input)."""

    model_config = ConfigDict(extra="forbid")

    transport: Literal["smtp", "console"] | None = None
    smtp_host: str | None = Field(default=None, max_length=MAX_HOST)
    smtp_port: int | None = Field(default=None, ge=1, le=65535)
    smtp_security: Literal["starttls", "tls"] | None = None
    smtp_username: str | None = Field(default=None, max_length=MAX_USERNAME)
    from_address: EmailStr | Literal[""] | None = None
    from_name: str | None = Field(default=None, max_length=MAX_FROM_NAME)
    reply_to: EmailStr | Literal[""] | None = None
    daily_limit: int | None = Field(default=None, ge=1)
    per_minute_limit: int | None = Field(default=None, ge=1)
    tracking_opens: bool | None = None
    tracking_clicks: bool | None = None
    physical_address: str | None = Field(default=None, max_length=MAX_PHYSICAL_ADDRESS)
    test_send_extra_recipients: Annotated[
        list[Address] | None,
        Field(max_length=MAX_EXTRA_TEST_RECIPIENTS),
        BeforeValidator(_normalised_list),
    ] = None

    @field_validator("from_address", "from_name", "reply_to")
    @classmethod
    def _no_header_injection(cls, value: str | None, info) -> str | None:
        return value if value is None else check_header_text(value, field=info.field_name)
