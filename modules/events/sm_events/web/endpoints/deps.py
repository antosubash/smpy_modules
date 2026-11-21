"""Request-scoped dependencies shared by the events API and view endpoints.

The module's permissions are its static surface; per-calendar access (owner,
shares, visibility) is the access policy in :mod:`sm_events.core.access`, and
narrows what these admit.
"""

from __future__ import annotations

from fastapi import Depends, Request
from simple_module_hosting.permissions import RequiresPermission

from sm_events.core import constants
from sm_events.core.settings import EventsSettings

require_view = Depends(RequiresPermission(constants.PERM_VIEW))
require_edit = Depends(RequiresPermission(constants.PERM_EDIT))
require_manage = Depends(RequiresPermission(constants.PERM_MANAGE))


def get_settings(request: Request) -> EventsSettings:
    """The hydrated settings for this install, read through the container
    ``register_settings`` mounts so a Settings-screen edit applies at once."""
    return getattr(request.app.state, constants.PACKAGE).settings
