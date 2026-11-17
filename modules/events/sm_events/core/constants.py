"""Names the module registers under; one place so nothing spells them twice."""

from __future__ import annotations

PACKAGE = "sm_events"
MODULE_NAME = "Events"
DISTRIBUTION = "simple_module_events"
LOCALE_NAMESPACE = "events"
BASE_NAME = "events"
TABLE_PREFIX = "events_"

ROUTE_PREFIX_API = "/api/events"
VIEW_PREFIX = "/admin/events"

PERM_GROUP = MODULE_NAME
PERM_GROUP_KEY = "events.permission_group"
PERM_VIEW = "events.view"
PERM_EDIT = "events.edit"
PERM_PUBLISH = "events.publish"
PERM_MANAGE = "events.manage"
PERMISSIONS = (PERM_VIEW, PERM_EDIT, PERM_PUBLISH, PERM_MANAGE)

_MODULE_SETTINGS = "Settings"
_MODULE_SHARING = "Sharing"
DEPENDS_ON = (_MODULE_SETTINGS, _MODULE_SHARING)

TENANT_REQUIRED_CODE = "tenant_required"
NOT_FOUND_DETAIL = "Not found"

# Column widths and the shapes a slug, a timezone name and a colour may take.
SLUG_MAX = 80
SLUG_PATTERN = r"^[a-z0-9]+(?:-[a-z0-9]+)*$"
TEXT_SLUG_MAX = 200
TZ_MAX = 64
LOCALE_MAX = 16
COLOR_PATTERN = r"^#[0-9a-f]{6}$"
DEFAULT_COLOR = "#2563eb"
