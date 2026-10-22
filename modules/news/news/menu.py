"""The console's rail entries for news.

Out of :mod:`news.module` only to keep that file under the line cap; the
module still registers them, from ``register_menu_items``.
"""

from __future__ import annotations

from simple_module_core.menu import MenuItem

from news import constants


def menu_items() -> list[MenuItem]:
    """Articles, Categories and Trash under News; Search in a group of its own.

    Roles stay empty: filtering is a plain intersection with no admin bypass,
    so a non-empty list hides the entry from everyone outside it.
    """
    return [
        MenuItem(
            label=constants.MENU_LABEL_ARTICLES,
            label_key=constants.MENU_LABEL_KEY_ARTICLES,
            url=constants.MENU_URL,
            icon=constants.MENU_ICON,
            order=100,
            group=constants.MENU_GROUP,
            group_key=constants.MENU_GROUP_KEY,
        ),
        MenuItem(
            label=constants.MENU_LABEL_CATEGORIES,
            label_key=constants.MENU_LABEL_KEY_CATEGORIES,
            url=constants.MENU_URL_CATEGORIES,
            icon=constants.MENU_ICON_CATEGORIES,
            order=110,
            group=constants.MENU_GROUP,
            group_key=constants.MENU_GROUP_KEY,
        ),
        # In the rail rather than behind a filter on the list: a trashed
        # article keeps its slug claimed, so an author who bins one and
        # cannot find it tries to recreate it and is told the URL is
        # taken by something they cannot see.
        MenuItem(
            label=constants.MENU_LABEL_TRASH,
            label_key=constants.MENU_LABEL_KEY_TRASH,
            url=constants.MENU_URL_TRASH,
            icon=constants.MENU_ICON_TRASH,
            order=120,
            group=constants.MENU_GROUP,
            group_key=constants.MENU_GROUP_KEY,
        ),
        # Its own group: where pagebuilder is installed the screen
        # searches pages and media as well, so listing it under News
        # would say something untrue about what it covers.
        MenuItem(
            label=constants.MENU_LABEL_SEARCH,
            label_key=constants.MENU_LABEL_KEY_SEARCH,
            url=constants.ADMIN_SEARCH_URL,
            icon=constants.MENU_ICON_SEARCH,
            order=10,
            group=constants.MENU_GROUP_SEARCH,
            group_key=constants.MENU_GROUP_KEY_SEARCH,
        ),
    ]
