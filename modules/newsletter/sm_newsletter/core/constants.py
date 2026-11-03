"""Names the module registers under; one place so nothing spells them twice."""

from __future__ import annotations

PACKAGE = "sm_newsletter"
MODULE_NAME = "Newsletter"
DISTRIBUTION = "simple_module_newsletter"
LOCALE_NAMESPACE = "newsletter"
TABLE_PREFIX = "newsletter_"
BASE_NAME = "newsletter"

ROUTE_PREFIX_API = "/api/newsletter"
VIEW_PREFIX = "/admin/newsletter"
PUBLIC_PREFIX = "/newsletter/"

PERM_GROUP = MODULE_NAME
PERM_GROUP_KEY = "newsletter.permission_group"
PERM_VIEW = "newsletter.view"
PERM_EDIT = "newsletter.edit"
PERM_SEND = "newsletter.send"
PERM_MANAGE = "newsletter.manage"
PERMISSIONS = (PERM_VIEW, PERM_EDIT, PERM_SEND, PERM_MANAGE)

_MODULE_SETTINGS = "Settings"
_MODULE_RECORDS = "Records"
_MODULE_BACKGROUND_TASKS = "BackgroundTasks"
DEPENDS_ON = (_MODULE_SETTINGS, _MODULE_RECORDS, _MODULE_BACKGROUND_TASKS)

TENANT_REQUIRED_CODE = "tenant_required"
NOT_FOUND_DETAIL = "Not found"

# The newsletter settings page (PR 3). Registered now as the settings'
# ``manage_url`` so the generic Settings screen refuses newsletter writes.
SETTINGS_URL = f"{VIEW_PREFIX}/settings"
