"""Request-scoped dependencies shared by the Images API and view endpoints.

The module's permissions are its static surface; per-collection access
(owner, shares, visibility) is the access policy added with the collections
endpoints, and narrows what these admit. There is no settings permission: the
module's settings are written through the framework's Settings screen and API,
governed by ``settings.edit``.
"""

from __future__ import annotations

from fastapi import Depends, Request
from simple_module_hosting.permissions import RequiresPermission

from sm_images import constants
from sm_images.settings import ImagesSettings

require_view = Depends(RequiresPermission(constants.PERM_VIEW))
require_create = Depends(RequiresPermission(constants.PERM_CREATE))
require_publish = Depends(RequiresPermission(constants.PERM_PUBLISH))


def get_settings(request: Request) -> ImagesSettings:
    """The hydrated settings for this install.

    Read through the container ``register_settings`` mounts, never a captured
    default, so a Settings-screen edit takes effect without a restart.
    """
    return getattr(request.app.state, constants.PACKAGE).settings
