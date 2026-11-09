"""The console's rail entries for newsletter, registered from ``module.py``."""

from __future__ import annotations

from simple_module_core.menu import MenuItem

from sm_newsletter.core import constants


def menu_items() -> list[MenuItem]:
    """The rail entries.

    Campaigns and Segments need ``newsletter.view``, Subscribers that and
    ``records.view``, Suppressions, Import and Settings ``newsletter.manage``.
    """
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
            label=constants.MENU_LABEL_SUBSCRIBERS,
            label_key=constants.MENU_LABEL_KEY_SUBSCRIBERS,
            url=constants.SUBSCRIBERS_URL,
            icon=constants.MENU_ICON_SUBSCRIBERS,
            order=320,
            group=constants.MENU_GROUP,
            group_key=constants.MENU_GROUP_KEY,
            permissions=[constants.PERM_VIEW, constants.PERM_RECORDS_VIEW],
        ),
        MenuItem(
            label=constants.MENU_LABEL_SUPPRESSIONS,
            label_key=constants.MENU_LABEL_KEY_SUPPRESSIONS,
            url=constants.SUPPRESSIONS_URL,
            icon=constants.MENU_ICON_SUPPRESSIONS,
            order=330,
            group=constants.MENU_GROUP,
            group_key=constants.MENU_GROUP_KEY,
            permissions=[constants.PERM_MANAGE],
        ),
        MenuItem(
            label=constants.MENU_LABEL_IMPORT,
            label_key=constants.MENU_LABEL_KEY_IMPORT,
            url=constants.IMPORT_URL,
            icon=constants.MENU_ICON_IMPORT,
            order=360,
            group=constants.MENU_GROUP,
            group_key=constants.MENU_GROUP_KEY,
            permissions=[constants.PERM_MANAGE],
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
