"""What a reminder pass asks of the host: who a user is, and what the site's address is.

A :class:`ReminderRuntime` is the one seam between the beat and the framework. The web process
uses :func:`web_runtime` (the live app); a Celery worker builds none, and
:mod:`sm_events.reminders.worker_app` supplies a headless one under strict conditions. Whatever
the runtime is, it answers :meth:`recipients` with the accounts it can *prove* are active,
reachable and members of the tenant, each with the principal they hold; anything it cannot
establish is simply absent. Who may still see which event is :mod:`...recipients`' business.
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
from typing import Any, Protocol

from simple_module_core.resources import ResourcePrincipal
from starlette.requests import Request

from sm_events.core.access.offline import offline_accounts
from sm_events.core.host_settings import public_base_url
from sm_events.core.tenancy import TenancyMode, mode_of

__all__ = ["Recipient", "ReminderRuntime", "web_runtime"]


@dataclass(frozen=True)
class Recipient:
    user_id: str
    email: str
    principal: ResourcePrincipal
    verified: bool | None = None
    """What the directory says about the address; ``None``: it does not say."""


class ReminderRuntime(Protocol):
    @property
    def public_base_url(self) -> str: ...

    @property
    def single_tenant(self) -> bool:
        """Whether the host serves one tenant (its public origin is then the configured one)."""
        ...

    async def recipients(
        self, db: Any, *, tenant_id: str, user_ids: Collection[str]
    ) -> dict[str, Recipient]:
        """The accounts among ``user_ids`` that are active, members of the tenant, have an
        address and whose rights could be worked out, with the principal each holds. A user who
        is missing may be unknown, deactivated, a non-member or unresolvable: never told apart."""
        ...


class _WebRuntime:
    """The live app: the offline principal over its directory, membership and permissions."""

    def __init__(self, app: Any) -> None:
        self.app = app

    @property
    def public_base_url(self) -> str:
        return public_base_url(self.app)

    @property
    def single_tenant(self) -> bool:
        return mode_of(self.app) is TenancyMode.SINGLE

    async def recipients(
        self, db: Any, *, tenant_id: str, user_ids: Collection[str]
    ) -> dict[str, Recipient]:
        request = Request(
            {"type": "http", "app": self.app, "headers": [], "method": "GET", "path": "/"}
        )
        accounts = await offline_accounts(
            self.app, db, user_ids=user_ids, tenant_id=tenant_id, request=request
        )
        return {
            user_id: Recipient(
                user_id, account.user.email, account.principal, account.user.email_verified
            )
            for user_id, account in accounts.items()
        }


def web_runtime(app: Any) -> ReminderRuntime:
    return _WebRuntime(app)
