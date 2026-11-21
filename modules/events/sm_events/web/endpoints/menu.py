"""The events console's sidebar entries."""

from simple_module_core.menu import MenuItem

from sm_events.core import constants as c


def menu_items() -> list[MenuItem]:
    return [
        MenuItem(
            label=c.MENU_LABEL_CALENDARS,
            label_key=c.MENU_LABEL_KEY_CALENDARS,
            url=c.CALENDARS_URL,
            icon=c.MENU_ICON_CALENDARS,
            order=400,
            group=c.MENU_GROUP,
            group_key=c.MENU_GROUP_KEY,
            permissions=[c.PERM_VIEW],
        ),
        MenuItem(
            label=c.MENU_LABEL_CATEGORIES,
            label_key=c.MENU_LABEL_KEY_CATEGORIES,
            url=c.CATEGORIES_URL,
            icon=c.MENU_ICON_CATEGORIES,
            order=410,
            group=c.MENU_GROUP,
            group_key=c.MENU_GROUP_KEY,
            permissions=[c.PERM_VIEW, c.PERM_MANAGE],
        ),
    ]
