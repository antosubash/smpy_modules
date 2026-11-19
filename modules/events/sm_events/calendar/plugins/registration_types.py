"""What a registration provider sees and answers (PR 9).

A provider is the module that owns the *people* of a registration (records). Events owns the seats
and the rule; the provider answers two questions: does this target (an opaque name the editor
saved on an event, for records a form's key) exist, and who are these holders (the opaque ids
stored on seats) right now. Everything here is re-exported by
:mod:`sm_events.contracts.extensions`, the only path a plugin imports.

**A provider call runs on a connection of its own** (the plugin runner's rule), never in events'
transaction: it reads committed data only and cannot write. Nothing that must be atomic with an
events write may be a provider call. The seat contract (:mod:`sm_events.contracts.registration`) is
the other direction and does share the caller's transaction.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

__all__ = [
    "Registrant",
    "RegistrationContext",
    "RegistrationProvider",
    "RegistrationTargetError",
    "RegistrationTargetInfo",
]


@dataclass(frozen=True)
class RegistrationContext:
    tenant_id: str
    db: AsyncSession


@dataclass(frozen=True)
class RegistrationTargetInfo:
    """What the editor shows about a target. Both urls are site-relative paths (``/admin/...``) or
    ``None``; ``attendees_url`` is shown only to someone the provider's own API lets in."""

    label: str
    admin_url: str | None = None
    attendees_url: str | None = None


@dataclass(frozen=True)
class Registrant:
    """One confirmed registrant, as the reminder needs them. Never stored by events."""

    email: str
    name: str
    locale: str


class RegistrationTargetError(Exception):
    """Raised by ``check_target``: the target does not exist or is not a registration form. Carries
    a message for the provider's own logs; events never shows it."""


@dataclass(frozen=True)
class RegistrationProvider:
    """``id`` is ``<entry-point name>:<name>`` like a source's. ``check_target`` raises
    :class:`RegistrationTargetError`; ``recipients`` returns only holders whose registration is
    confirmed right now (anyone else is simply absent)."""

    id: str
    label_key: str
    check_target: Callable[[RegistrationContext, str], Awaitable[RegistrationTargetInfo]]
    recipients: Callable[[RegistrationContext, Sequence[str]], Awaitable[Mapping[str, Registrant]]]
