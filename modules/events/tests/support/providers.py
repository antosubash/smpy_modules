"""A fake registration provider and a way to install it (PR 9's seam), like ``sources.install``."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from sm_events.calendar.plugins import extensions, registry
from sm_events.contracts.extensions import (
    Registrant,
    RegistrationContext,
    RegistrationProvider,
    RegistrationTargetError,
    RegistrationTargetInfo,
)

_REAL_LOADERS = list(extensions._BUILTIN_LOADERS)
"""The built-ins' loaders, taken before any test patches them: a second install in one test must
not inherit the first one's plugins."""

PROVIDER_ID = "records:registration"
KNOWN_TARGET = "event-registrations"


async def _check(ctx: RegistrationContext, target: str) -> RegistrationTargetInfo:
    if target != KNOWN_TARGET:
        raise RegistrationTargetError("unknown form")
    return RegistrationTargetInfo(
        label="Event registrations",
        admin_url="/admin/records/event-registrations",
        attendees_url="/admin/records/event-registrations?filter=x",
    )


async def _recipients(ctx: RegistrationContext, holders: Sequence[str]) -> Mapping[str, Registrant]:
    return {h: Registrant(email=f"{h}@example.com", name=h, locale="en") for h in holders}


def provider(
    check: Callable[..., Any] = _check,
    recipients: Callable[..., Any] = _recipients,
    ident: str = PROVIDER_ID,
) -> RegistrationProvider:
    return RegistrationProvider(
        id=ident, label_key="records.registration", check_target=check, recipients=recipients
    )


async def slow(ctx: RegistrationContext, target: str) -> RegistrationTargetInfo:
    await asyncio.sleep(10)
    raise AssertionError("unreachable")


def install_provider(monkeypatch, *providers: RegistrationProvider) -> None:
    """A registry holding the built-ins plus ``providers`` (namespaced by their own id), frozen on
    first read. Call ``registry.reset_registry()`` (the ``fresh_registry`` fixture does)."""
    registry.reset_registry()

    def plugins() -> None:
        for each in providers:
            registry.add_registration_provider(each, namespace=each.id.split(":", 1)[0])

    monkeypatch.setattr(extensions, "_BUILTIN_LOADERS", [*_REAL_LOADERS, plugins])
    monkeypatch.setattr(extensions, "_plugins", list)


SECRET_TARGET = "secret-form"
OPEN_TARGET = "open-form"


def _may(ctx: RegistrationContext, target: str) -> bool:
    """alice may use any form; everybody else only the open one; a worker (no viewer) none."""
    if ctx.viewer is None:
        return False
    return target == OPEN_TARGET or (target == SECRET_TARGET and ctx.viewer.user_id == "alice")


async def _restricted_check(ctx: RegistrationContext, target: str) -> RegistrationTargetInfo:
    if not _may(ctx, target):  # one refusal for "missing" and "not yours"
        raise RegistrationTargetError("no such registration form")
    return RegistrationTargetInfo(label=f"Label of {target}", admin_url=f"/admin/{target}")


async def _restricted_can_read(ctx: RegistrationContext, target: str) -> bool:
    return _may(ctx, target)


def restricted() -> RegistrationProvider:
    return RegistrationProvider(
        id=PROVIDER_ID,
        label_key="records.registration",
        check_target=_restricted_check,
        recipients=_recipients,
        can_read=_restricted_can_read,
    )
