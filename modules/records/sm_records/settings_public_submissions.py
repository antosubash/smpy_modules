"""The settings of submissions from the website (#101) — the abuse knobs every
type that accepts them shares.

A base class of :class:`~sm_records.settings.RecordsSettings`, between it and
:class:`~sm_records.settings_boot.BootSettings`, for the 300-line cap: one
class on one Settings screen, still stored in the database with no environment
source (``StoredSourcesOnly`` comes with the base). Every field is read per
request, so none needs a restart.

What a single type accepts — its fields, recipients and consent — lives on the
type (``RecordType.public_submissions``), not here: types are per tenant, and
these are one deployment's limits.
"""

from __future__ import annotations

from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, field_validator
from pydantic_settings import SettingsConfigDict
from simple_module_core.rate_limit import RateLimitError, parse_rate

from sm_records.settings_boot import BootSettings

__all__ = ["PublicSubmissionsSettings", "check_origin"]


def check_origin(value: str) -> str:
    """An ``http(s)://host[:port]`` origin, lowercased, with no path."""
    cleaned = value.strip().rstrip("/").lower()
    parts = urlsplit(cleaned)
    if parts.scheme not in ("http", "https") or not parts.netloc or parts.path:
        raise ValueError(f"{value!r} is not an origin such as https://example.org")
    if parts.query or parts.fragment or "@" in parts.netloc:
        raise ValueError(f"{value!r} is not an origin such as https://example.org")
    return cleaned


class PublicSubmissionsSettings(BootSettings):
    model_config = SettingsConfigDict(extra="ignore", use_attribute_docstrings=True)

    public_submissions_enabled: bool = True
    """Master switch for submissions from the website. Off, every submission
    route answers 404 — the switch to reach for under attack. Harmless when on:
    nothing is accepted until a record type opts in."""

    public_submissions_rate_per_ip: str = "5/10minute"
    """How many submissions one IP address may send, across every type, as
    ``<count>/<period>`` (``5/10minute``, ``20/hour``). Over it is a ``429``
    with ``Retry-After``. ``off`` disables it. Counted per process unless the
    host has Redis; behind a proxy, set ``SM_TRUSTED_PROXY`` or every visitor
    shares one address."""

    public_submissions_type_rate: str = "60/hour"
    """How many submissions one type accepts from everyone together, as
    ``<count>/<period>``. Catches a flood from rotating addresses; over it is a
    ``429``. ``off`` disables it."""

    public_submissions_min_fill_seconds: int = Field(default=3, ge=0)
    """A form sent sooner than this after it was loaded is refused as a bot
    (``400 form_expired``; the form fetches a fresh token and retries)."""

    public_submissions_token_max_age_seconds: int = Field(default=7200, ge=60)
    """How long a loaded form stays sendable. Older is ``400 form_expired``."""

    public_submissions_max_links: int = Field(default=5, ge=0)
    """A submission whose text holds more links than this is kept as spam: in
    the trash, marked ``links``, with nobody notified. ``0`` turns the check
    off."""

    public_submissions_max_body_bytes: int = Field(default=16384, ge=1024)
    """Largest submission body, in bytes — refused with a ``413`` before it is
    read. ``max_payload_bytes`` wins when it is lower."""

    public_submissions_allowed_origins: tuple[str, ...] = ()
    """Origins besides this host and the host's ``public_base_url`` that may
    send submissions, as a JSON array (``["https://www.example.org"]``). A
    submission whose ``Origin`` (else ``Referer``) is none of them is a
    ``403 bad_origin``."""

    public_submissions_store_ip_hash: bool = True
    """Keep a keyed hash of the sender's IP address with each submission
    (``sm_ip_hash``). The raw address is never stored."""

    public_submissions_store_user_agent: bool = True
    """Keep the sender's user agent (``sm_user_agent``), cut to 256 characters."""

    public_submissions_confirm_rate_per_email: str = "3/day"
    """How many confirmation emails one address is sent for one newsletter
    list, as ``<count>/<period>`` — signups and admin resends together. Over
    it the signup still answers the same ``202`` and nothing is sent, so
    nobody can use the list to flood an inbox. ``off`` disables it."""

    public_submissions_confirm_ttl_hours: int = Field(default=168, ge=1, le=24 * 365)
    """How long a confirmation link works, in hours. Later it is expired and
    the visitor signs up again."""

    public_submissions_captcha_provider: Literal["none", "turnstile", "hcaptcha"] = "none"
    """A CAPTCHA every submission must pass: ``none`` (the default — the
    honeypot, the signed form token and the rate limits stop most spam),
    ``turnstile`` (Cloudflare) or ``hcaptcha``. Checked with the provider
    before anything is stored; when the provider cannot be reached the
    submission is refused, never let through. Add the provider's host to
    pagebuilder's ``public_csp`` (``script-src`` and ``frame-src``), or the
    widget cannot load."""

    public_submissions_captcha_site_key: str = ""
    """The provider's public site key, sent to the form to render the widget."""

    public_submissions_captcha_secret: str = ""
    """The provider's secret key, used only to verify a response server-side.
    Masked on the Settings screen and stored as other secrets here are."""

    public_submissions_retention_enabled: bool = True
    """Run the hourly clean-up: delete contact-form submissions older than
    their type's retention, newsletter signups never confirmed within the
    list's unconfirmed purge, and old delivery bookkeeping. Off, nothing is
    deleted automatically (a deployment that purges another way)."""

    public_submissions_retention_interval_seconds: int = Field(default=3600, ge=60)
    """How often the clean-up runs, in seconds."""

    public_submissions_delivery_retention_days: int = Field(default=30, ge=1, le=3650)
    """How long the record of who a submission's email reached is kept, in
    days. It stops a retried delivery from mailing someone twice, which only
    matters while a retry can still happen."""

    @field_validator(
        "public_submissions_rate_per_ip",
        "public_submissions_type_rate",
        "public_submissions_confirm_rate_per_email",
        mode="after",
    )
    @classmethod
    def _check_rate(cls, value: str) -> str:
        try:
            parse_rate(value)
        except RateLimitError as exc:
            raise ValueError(str(exc)) from exc
        return value

    @field_validator("public_submissions_allowed_origins", mode="after")
    @classmethod
    def _check_origins(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(dict.fromkeys(check_origin(origin) for origin in value))
