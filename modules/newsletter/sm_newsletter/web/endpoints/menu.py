"""The console's rail entries for newsletter, registered from ``module.py``."""

from __future__ import annotations

from simple_module_core.menu import MenuItem

from sm_newsletter.core import constants


def menu_items() -> list[MenuItem]:
    """Campaigns and Segments (``newsletter.view``) and Settings (``newsletter.manage``)."""
    return [
        MenuItem(
            label=constants.MENU_LABEL_CAMPAIGNS,
            label_key=constants.MENU_LABEL_KEY_CAMPAIGNS,
            url=constants.MENU_URL,
            icon=constants.MENU_ICON_CAMPAIGNS,
            order=300,
            group=constants.MENU_GROUP,
            group_key=constants.MENU_GROUP_KEY,
            permissions=[constants.PERM_VIEW],
        ),
        MenuItem(
            label=constants.MENU_LABEL_SEGMENTS,
            label_key=constants.MENU_LABEL_KEY_SEGMENTS,
            url=constants.SEGMENTS_URL,
            icon=constants.MENU_ICON_SEGMENTS,
            order=310,
            group=constants.MENU_GROUP,
            group_key=constants.MENU_GROUP_KEY,
            permissions=[constants.PERM_VIEW],
        ),
        MenuItem(
            label=constants.MENU_LABEL_SETTINGS,
            label_key=constants.MENU_LABEL_KEY_SETTINGS,
            url=constants.SETTINGS_URL,
            icon=constants.MENU_ICON_SETTINGS,
            order=390,
            group=constants.MENU_GROUP,
            group_key=constants.MENU_GROUP_KEY,
            permissions=[constants.PERM_MANAGE],
        ),
    ]
