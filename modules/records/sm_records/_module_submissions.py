"""The website-submission hooks of :class:`~sm_records.module.RecordsModule`
(#101), split out for the 300-line cap: the outbox handler and the static rate
limit. The routes and their exemptions stay with the module's other routes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from simple_module_core.events import EventBus
from simple_module_core.rate_limit import RateLimitRegistry, RateLimitRule

from sm_records import constants

if TYPE_CHECKING:
    from fastapi import FastAPI

__all__ = ["SubmissionHooks"]


class SubmissionHooks:
    settings: Any
    """The composing module's settings, which the outbox handler reads."""

    def register_event_handlers(self, bus: EventBus, app: FastAPI | None = None) -> None:
        """The outbox handler that mails a website submission's notification,
        when the host delivers durably. Registered whatever ``app`` is: the
        outbox worker builds modules with ``app=None`` and still has to know
        the handler. See :mod:`sm_records.public_submissions.mail_runner`.

        A newsletter's confirmation has no durable handler on purpose: its
        links need the host's ``secret_key``, which the worker does not have
        (:mod:`sm_records.public_submissions.confirmation`)."""
        from sm_records.public_submissions.mail_runner import (
            HANDLER_NAME,
            NotificationDue,
            durable_handler,
        )

        bus.subscribe_durable(NotificationDue, durable_handler(self), name=HANDLER_NAME)

    def register_rate_limits(self, registry: RateLimitRegistry) -> None:
        """A static backstop on the anonymous form definition. Submits are
        limited by the module itself, at rates that are settings."""
        registry.add_prefix(
            constants.PUBLIC_SUBMISSIONS_API_PREFIX,
            RateLimitRule("60/minute", key="ip", methods=frozenset({"GET"})),
        )
