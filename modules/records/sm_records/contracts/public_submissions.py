"""The ``records_type.public_submissions`` config — what a record type that
accepts submissions from the website is configured to accept (#101).

Plain ``SQLModel`` DTOs, per the contracts rule. The column is plain JSON and
stores :meth:`PublicSubmissionsConfig.model_dump` of this shape; ``TypeRead``
reads it back as a plain ``dict`` rather than through this class, so a stored
row that predates a bound added here still reads (the billing ``PlanOut``
lesson in ``AGENTS.md``). What the shape alone cannot say — the rules that need
the type's fields or its ``is_public`` — is
:func:`sm_records.public_submissions.config.settle`.
"""

from __future__ import annotations

from typing import Literal

from pydantic import ConfigDict, field_validator, model_validator
from sqlmodel import Field, SQLModel

from sm_records.schema._builders import _check_email

__all__ = [
    "DEFAULT_PENDING_HOLD_HOURS",
    "KIND_FORM",
    "KIND_REGISTRATION",
    "KIND_SUBSCRIPTION",
    "MAX_CONSENT_TEXT_LEN",
    "MAX_NOTIFY_TO",
    "MAX_PENDING_HOLD_HOURS",
    "MAX_RETENTION_DAYS",
    "ConsentConfig",
    "PublicSubmissionsConfig",
    "SubmissionKind",
]

KIND_FORM = "form"
"""A contact-form type: every submission is a new record."""
KIND_SUBSCRIPTION = "subscription"
"""A newsletter type: one record per address, with a double opt-in."""

KIND_REGISTRATION = "registration"
"""An event registration: one record per person per occurrence, with a seat at the event the
signed token names (never the page, never the request body)."""

SubmissionKind = Literal["form", "subscription", "registration"]

DEFAULT_PENDING_HOLD_HOURS = 1
"""How long an unconfirmed registration is kept by default (its **pending TTL**): an hour. It holds
no seat meanwhile (the seat is taken at the confirmation); the record is only personal data of
someone who has not confirmed, so the retention sweep removes it after this. One constant, used by
every reader of a stored config that lacks the key."""
MAX_PENDING_HOLD_HOURS = 168

MAX_NOTIFY_TO = 10
MAX_CONSENT_TEXT_LEN = 2000
MAX_RETENTION_DAYS = 36500
"""A century: an unbounded day count overflows ``timedelta`` the first time a
purge subtracts it from now."""


class ConsentConfig(SQLModel):
    """A checkbox the visitor must tick when ``required``. ``text`` is keyed by
    content locale; the visitor's is snapshotted into ``sm_consent_text``."""

    # SQLModel declares `model_config` as its own TypedDict, a ConfigDict superset.
    model_config = ConfigDict(extra="forbid")  # pyright: ignore[reportAssignmentType]

    required: bool = False
    text: dict[str, str] = Field(default_factory=dict)


class PublicSubmissionsConfig(SQLModel):
    """One record type's public-submissions settings.

    ``kind`` is set once: clearing or changing it is a 409
    (``public_submissions.config.check_change``). ``enabled`` is the switch the
    type editor labels "Accept submissions from the website".
    """

    # SQLModel declares `model_config` as its own TypedDict, a ConfigDict superset.
    model_config = ConfigDict(extra="forbid")  # pyright: ignore[reportAssignmentType]

    kind: SubmissionKind
    enabled: bool = False
    public_fields: list[str] = Field(default_factory=list)
    """Allowlist of ordinary field keys a visitor may fill, in render order."""
    notify_to: list[str] = Field(default_factory=list, max_length=MAX_NOTIFY_TO)
    """Form kind: who is told about each submission. Empty stores and sends nothing."""
    consent: ConsentConfig = Field(default_factory=ConsentConfig)
    double_opt_in: bool = True
    """Subscription and registration kinds. Off requires ``consent.required``."""
    retention_days: int = Field(default=365, ge=0, le=MAX_RETENTION_DAYS)
    """Form kind: records older than this are purged. ``0`` keeps them."""
    pending_purge_days: int = Field(default=30, ge=1, le=MAX_RETENTION_DAYS)
    """Subscription kind: never-confirmed records are purged after this."""

    pending_hold_hours: int = Field(
        default=DEFAULT_PENDING_HOLD_HOURS, ge=1, le=MAX_PENDING_HOLD_HOURS
    )
    """Registration kind: how long an unconfirmed registration holds its seat."""

    @model_validator(mode="after")
    def _hold_is_for_registrations(self) -> PublicSubmissionsConfig:
        if self.kind != KIND_REGISTRATION and self.pending_hold_hours != DEFAULT_PENDING_HOLD_HOURS:
            raise ValueError("pending_hold_hours belongs to the registration kind")
        return self

    @field_validator("notify_to")
    @classmethod
    def _emails(cls, value: list[str]) -> list[str]:
        # Case-insensitive: ``Ops@x.org`` and ``ops@x.org`` are one inbox in
        # practice, and listing both would send it every notification twice.
        # The first spelling is kept.
        out: list[str] = []
        seen: set[str] = set()
        for address in value:
            cleaned = address.strip()
            _check_email(cleaned)
            if cleaned.lower() not in seen:
                seen.add(cleaned.lower())
                out.append(cleaned)
        return out

    @field_validator("public_fields")
    @classmethod
    def _unique_keys(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("public_fields names a field twice")
        return value
