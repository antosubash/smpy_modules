"""The wire shapes of the website-submission routes (#101).

``GET /api/records/submissions/{type_key}`` answers a
:class:`SubmissionDefinition` — what a form renders — and ``POST …/submit``
takes a :class:`SubmitBody`. Plain ``SQLModel`` DTOs, per the contracts rule.
Nothing in a definition is trusted back: the server re-reads the type on
submit, and only ``data``, ``consent`` and the hints below come from the
visitor.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import ConfigDict
from sqlmodel import Field, SQLModel

__all__ = [
    "NotificationQueued",
    "SubmissionAccepted",
    "SubmissionConsent",
    "SubmissionDefinition",
    "SubmissionField",
    "SubmitBody",
]

MAX_TOKEN_LEN = 200


class SubmissionField(SQLModel):
    """One input of the form: a field the type lists in ``public_fields``."""

    key: str
    type: str
    label: str
    help: str | None = None
    required: bool = False
    choices: list[dict[str, str]] = Field(default_factory=list)
    constraints: dict[str, Any] = Field(default_factory=dict)
    default: Any = None


class SubmissionConsent(SQLModel):
    """The consent checkbox, with its text in the language asked for."""

    required: bool
    text: str


class SubmissionDefinition(SQLModel):
    kind: Literal["form", "subscription"]
    schema_version: int
    fields: list[SubmissionField]
    consent: SubmissionConsent | None = None
    token: str
    """Signed: send it back with the submission (``public_submissions.tokens``)."""
    captcha: dict[str, str] | None = None
    """Always ``null`` until a CAPTCHA provider is supported."""


class SubmitBody(SQLModel):
    """What a form sends. Unknown top-level keys are ignored, so a newer form
    sending a field this server does not know yet is not refused for it."""

    model_config = ConfigDict(extra="ignore")

    data: dict[str, Any] = Field(default_factory=dict)
    token: str = Field(default="", max_length=MAX_TOKEN_LEN)
    hp: str = ""
    """The honeypot: a hidden input a person never fills in. Unbounded on
    purpose (the body cap bounds it): a length refusal would tell a bot it was
    caught, where any value is the same silent 202."""
    consent: bool = False
    block: str | None = Field(default=None, max_length=100)
    """A hint naming the page block that sent it (``sm_source_block``)."""
    locale: str | None = Field(default=None, max_length=16)
    """The page's language (``sm_locale``, and the consent text's)."""


class SubmissionAccepted(SQLModel):
    ok: bool = True


class NotificationQueued(SQLModel):
    """``POST …/submission/resend``: the notification will be sent again."""

    queued: bool = True
