"""Mail transports: SMTP for real sends, console for development.

:func:`transport_for` picks one from the ``transport`` setting.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sm_newsletter.sending.transport.base import DeliveryResult, Transport, TransportSession
from sm_newsletter.sending.transport.console import ConsoleTransport
from sm_newsletter.sending.transport.message import (
    OutgoingMessage,
    build_mime,
    unsubscribe_headers,
)
from sm_newsletter.sending.transport.smtp import SmtpTransport

if TYPE_CHECKING:
    from sm_newsletter.core.settings import NewsletterSettings

__all__ = [
    "DeliveryResult",
    "OutgoingMessage",
    "Transport",
    "TransportSession",
    "build_mime",
    "transport_for",
    "unsubscribe_headers",
]


def transport_for(settings: NewsletterSettings) -> Transport:
    """The configured transport. Decrypts the SMTP password (``SmtpPasswordUnreadable``
    when the secret key changed)."""
    if settings.transport == "console":
        return ConsoleTransport()
    return SmtpTransport.from_settings(settings)
