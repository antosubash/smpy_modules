"""The console's sidebar entry for images.

Out of :mod:`sm_images.module` to keep that file small; the module registers it
from ``register_menu_items``. Deliberately not role-gated: menu role filtering is
a plain intersection with no admin bypass, so listing roles would hide the entry
from an ``admin`` user. The permission gates it instead.
"""

from __future__ import annotations

from simple_module_core.menu import MenuItem, MenuRegistry, MenuSection

from sm_images import constants


def register(registry: MenuRegistry) -> None:
    registry.add(
        MenuItem(
            label=constants.MENU_LABEL,
            label_key=constants.MENU_LABEL_KEY,
            url=constants.MENU_URL,
            icon=constants.MENU_ICON,
            order=constants.MENU_ORDER,
            section=MenuSection.ADMIN_SIDEBAR,
            group=constants.MENU_GROUP,
            group_key=constants.MENU_GROUP_KEY,
            permissions=[constants.PERM_VIEW],
        )
    )
