"""What the dispatcher needs in a Celery worker, which never builds the app (S11, S12, A5).

:func:`dispatch_config` reads, in order: ``NewsletterSettings`` from the
database (``background_tasks.settings_for``), the refusal of a plaintext SMTP
password, the worker's secret key (:mod:`sm_newsletter.core.secret`), and the
transport (which decrypts the password under that key).

:func:`dispatch_async` is the task body. Any configuration failure refuses the
whole tick before recovery, freeze or a relay connection: it is logged at ERROR
by its class name only (never a value; ``SettingsUnreadable`` adds its cause's
class) and the summary says ``not_configured``.
Campaigns stay as they are until the worker is fixed.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

from sm_newsletter.core import constants, crypto
from sm_newsletter.core.clock import utcnow
from sm_newsletter.core.errors import SmtpPasswordUnreadable
from sm_newsletter.core.secret import SecretMissing, install, resolve_worker_secret
from sm_newsletter.core.settings import NewsletterSettings
from sm_newsletter.sending.dispatch import TickSummary, tick
from sm_newsletter.sending.transport import Transport, transport_for
from sm_newsletter.sending.upkeep import SessionFactory

__all__ = [
    "PASSWORD_ENDPOINT",
    "DispatchConfig",
    "PlaintextPassword",
    "SettingsUnreadable",
    "dispatch_async",
    "dispatch_config",
    "refuse_plaintext_password",
]

logger = logging.getLogger(__name__)

PASSWORD_ENDPOINT = "PUT /api/newsletter/settings/smtp-password"


class PlaintextPassword(RuntimeError):  # noqa: N818 - reads as the condition it is
    """The stored SMTP password is not encrypted (A5); the worker will not send it."""


class SettingsUnreadable(RuntimeError):  # noqa: N818 - reads as the condition it is
    """``NewsletterSettings`` could not be read from the database."""


_REFUSALS = (SecretMissing, PlaintextPassword, SmtpPasswordUnreadable, SettingsUnreadable)


@dataclass(frozen=True)
class DispatchConfig:
    settings: NewsletterSettings
    secret: str = field(repr=False)
    transport: Transport


def refuse_plaintext_password(settings: NewsletterSettings) -> None:
    """Raise :class:`PlaintextPassword` for an ``smtp`` transport whose stored
    password lacks ``enc:v1:``. The message names the endpoint, never the value."""
    password = settings.smtp_password
    if settings.transport == "smtp" and password and not password.startswith(crypto.ENC_PREFIX):
        raise PlaintextPassword(
            f"the stored SMTP password is not encrypted; save it again with {PASSWORD_ENDPOINT}"
        )


def _settings() -> NewsletterSettings:
    from background_tasks import settings_for

    try:
        return settings_for(NewsletterSettings, constants.PACKAGE)
    except Exception as exc:
        raise SettingsUnreadable("newsletter settings could not be read") from exc


def dispatch_config() -> DispatchConfig:
    """The worker's settings, secret and transport, or one of the refusals."""
    settings = _settings()
    refuse_plaintext_password(settings)
    secret = resolve_worker_secret()
    install(secret)
    return DispatchConfig(settings, secret, transport_for(settings))


async def dispatch_async(
    factory: SessionFactory, *, clock: Callable[[], datetime] = utcnow
) -> TickSummary:
    """One dispatcher tick in a worker; ``not_configured`` when it may not run."""
    try:
        config = dispatch_config()
    except _REFUSALS as exc:
        name = type(exc).__name__
        if isinstance(exc, PlaintextPassword):
            logger.error("newsletter.dispatch refused: %s; use %s", name, PASSWORD_ENDPOINT)
        elif isinstance(exc, SettingsUnreadable):
            cause = type(exc.__cause__).__name__
            logger.error("newsletter.dispatch refused: %s (%s)", name, cause)
        else:
            logger.error("newsletter.dispatch refused: %s", name)
        return TickSummary(stopped="not_configured")
    return await tick(
        factory,
        settings=config.settings,
        secret=config.secret,
        transport=config.transport,
        clock=clock,
    )
