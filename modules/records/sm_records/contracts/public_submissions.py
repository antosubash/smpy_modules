"""The ``records_type.public_submissions`` config — what a record type that
accepts submissions from the website is configured to accept (#101).

Plain ``SQLModel`` DTOs, per the contracts rule. The column is plain JSON and
stores :meth:`PublicSubmissionsConfig.model_dump` of this shape; ``TypeRead``
reads it back as a plain ``dict`` rather than through this class, so a stored
row that predates a bound added here still reads (the billing ``PlanOut``
lesson in ``CLAUDE.md``). What the shape alone cannot say — the rules that need
the type's fields or its ``is_public`` — is
:func:`sm_records.public_submissions.config.settle`.
"""

from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict, field_validator
from sqlmodel import Field, SQLModel

from sm_records.schema._builders import _check_email

__all__ = [
    "KIND_FORM",
    "KIND_SUBSCRIPTION",
    "MAX_CONSENT_TEXT_LEN",
    "MAX_NOTIFY_TO",
    "ConsentConfig",
    "PublicSubmissionsConfig",
    "SubmissionKind",
]

KIND_FORM = "form"
"""A contact-form type: every submission is a new record."""
KIND_SUBSCRIPTION = "subscription"
"""A newsletter type: one record per address, with a double opt-in."""

SubmissionKind = Literal["form", "subscription"]

MAX_NOTIFY_TO = 10
MAX_CONSENT_TEXT_LEN = 2000


class ConsentConfig(SQLModel):
    """A checkbox the visitor must tick when ``required``. ``text`` is keyed by
    content locale; the visitor's is snapshotted into ``sm_consent_text``."""

    model_config = ConfigDict(extra="forbid")

    required: bool = False
    text: dict[str, str] = Field(default_factory=dict)


class PublicSubmissionsConfig(SQLModel):
    """One record type's public-submissions settings.

    ``kind`` is set once: clearing or changing it is a 409
    (``public_submissions.config.check_change``). ``enabled`` is the switch the
    type editor labels "Accept submissions from the website".
    """

    model_config = ConfigDict(extra="forbid")

    kind: SubmissionKind
    enabled: bool = False
    public_fields: list[str] = Field(default_factory=list)
    """Allowlist of ordinary field keys a visitor may fill, in render order."""
    notify_to: list[str] = Field(default_factory=list, max_length=MAX_NOTIFY_TO)
    """Form kind: who is told about each submission. Empty stores and sends nothing."""
    consent: ConsentConfig = Field(default_factory=ConsentConfig)
    double_opt_in: bool = True
    """Subscription kind only. Off requires ``consent.required``."""
    retention_days: int = Field(default=365, ge=0)
    """Form kind: records older than this are purged. ``0`` keeps them."""
    pending_purge_days: int = Field(default=30, ge=1)
    """Subscription kind: never-confirmed records are purged after this."""

    @field_validator("notify_to")
    @classmethod
    def _emails(cls, value: list[str]) -> list[str]:
        out: list[str] = []
        for address in value:
            cleaned = address.strip()
            _check_email(cleaned)
            if cleaned not in out:
                out.append(cleaned)
        return out

    @field_validator("public_fields")
    @classmethod
    def _unique_keys(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("public_fields names a field twice")
        return value
