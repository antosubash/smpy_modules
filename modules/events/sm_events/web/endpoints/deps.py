"""Request-scoped dependencies shared by the events API and view endpoints.

The module's permissions are its static surface; per-calendar access (owner,
shares, visibility) is the access policy in :mod:`sm_events.core.access`, and
narrows what these admit.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request
from simple_module_core.resources import ResourcePrincipal
from simple_module_db.deps import get_db
from simple_module_hosting.permissions import RequiresPermission
from simple_module_hosting.resource_deps import resource_principal
from sqlalchemy.ext.asyncio import AsyncSession

from sm_events.content import bus
from sm_events.core import constants
from sm_events.core.settings import EventsSettings

require_view = Depends(RequiresPermission(constants.PERM_VIEW))
require_edit = Depends(RequiresPermission(constants.PERM_EDIT))
require_manage = Depends(RequiresPermission(constants.PERM_MANAGE))


Principal = Annotated[ResourcePrincipal, Depends(resource_principal)]


def get_settings(request: Request) -> EventsSettings:
    """The hydrated settings for this install, read through the container
    ``register_settings`` mounts so a Settings-screen edit applies at once."""
    return getattr(request.app.state, constants.PACKAGE).settings


async def event_db(request: Request, db: AsyncSession = Depends(get_db)) -> AsyncSession:
    """``get_db``, with the session told where this app's bus is, so the events a
    write queues go out after its commit (a harness with no bus publishes none)."""
    bus.attach(db, getattr(getattr(request.app.state, "sm", None), "event_bus", None))
    return db


def content_locales(request: Request) -> tuple[str, ...]:
    """The languages events can be written in; the first is the default."""
    return tuple(get_settings(request).content_locales)
