"""Newsletter settings - stored in the database, not read from the environment.

:class:`~simple_module_core.settings_base.DbBackedSettings` drops every source
pydantic-settings would consult, so there is no ``SM_NEWSLETTER_*`` variable.
Until PR 3's page exists they are configured headlessly with
``scripts/set_setting.py``. The module registers a ``manage_url``, so the
generic Settings screen refuses newsletter writes (409): ``smtp_password`` must
never be written there in plaintext. It is stored ``enc:v1:...`` and written
through ``PUT /api/newsletter/settings/smtp-password``; a plaintext value found
at read time (an operator wrote the DB directly) is accepted with a one-time
warning. SYSTEM scope: one configuration for the whole deployment.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field
from pydantic_settings import SettingsConfigDict
from simple_module_core.settings_base import DbBackedSettings

__all__ = ["NewsletterSettings"]


class NewsletterSettings(DbBackedSettings):
    # ``use_attribute_docstrings`` puts the prose under each field on the
    # Settings screen: the admin UI renders ``FieldInfo.description``.
    model_config = SettingsConfigDict(extra="ignore", use_attribute_docstrings=True)

    transport: Literal["smtp", "console"] = "smtp"
    """How campaigns leave the server: ``smtp``, or ``console`` to log them (development)."""

    smtp_host: str = "smtp-relay.gmail.com"
    """SMTP relay host name."""

    smtp_port: int = Field(default=587, ge=1, le=65535)
    """SMTP relay port."""

    smtp_security: Literal["starttls", "tls"] = "starttls"
    """Connection security: ``starttls`` (upgrade a plain connection) or ``tls`` (implicit TLS)."""

    smtp_username: str = ""
    """SMTP login. Empty sends without authenticating (an IP-allowlisted relay)."""

    smtp_password: str = Field(default="", repr=False)
    """SMTP password, stored encrypted (``enc:v1:...``). Written through the
    password endpoint, never shown."""

    from_address: str = ""
    """Sender address of every campaign."""

    from_name: str = ""
    """Sender display name."""

    reply_to: str = ""
    """Reply-To address. Empty uses the sender address."""

    daily_limit: int = Field(default=9500, ge=1)
    """Most messages sent per day (the relay's own quota, with headroom)."""

    per_minute_limit: int = Field(default=30, ge=1)
    """Most messages sent per minute."""

    tracking_opens: bool = True
    """Add an open-tracking pixel to campaigns."""

    tracking_clicks: bool = True
    """Rewrite links so clicks are counted."""

    physical_address: str = ""
    """Postal address printed in every campaign footer."""
