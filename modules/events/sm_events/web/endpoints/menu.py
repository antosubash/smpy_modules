"""The events console's sidebar entries."""

from simple_module_core.menu import MenuItem

from sm_events.core import constants as c


def menu_items() -> list[MenuItem]:
    return [
        MenuItem(
            label=c.MENU_LABEL_CALENDAR,
            label_key=c.MENU_LABEL_KEY_CALENDAR,
            url=c.CALENDAR_URL,
            icon=c.MENU_ICON_CALENDAR,
            order=390,
            group=c.MENU_GROUP,
            group_key=c.MENU_GROUP_KEY,
            permissions=[c.PERM_VIEW],
        ),
        MenuItem(
            label=c.MENU_LABEL_EVENTS,
            label_key=c.MENU_LABEL_KEY_EVENTS,
            url=c.EVENTS_URL,
            icon=c.MENU_ICON_EVENTS,
            order=395,
            group=c.MENU_GROUP,
            group_key=c.MENU_GROUP_KEY,
            permissions=[c.PERM_VIEW],
        ),
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
        MenuItem(
            label=c.MENU_LABEL_IMPORT,
            label_key=c.MENU_LABEL_KEY_IMPORT,
            url=c.IMPORT_URL,
            icon=c.MENU_ICON_IMPORT,
            order=420,
            group=c.MENU_GROUP,
            group_key=c.MENU_GROUP_KEY,
            permissions=[c.PERM_VIEW, c.PERM_MANAGE],
        ),
    ]
