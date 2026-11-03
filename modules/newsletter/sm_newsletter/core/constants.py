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

# Campaign and send lifecycles (``str`` columns, ``max_length=24``).
CAMPAIGN_STATUSES = ("draft", "scheduled", "sending", "paused", "sent", "cancelled")
SEND_STATUSES = (
    "queued",
    "sending",
    "sent",
    "failed",
    "bounced",
    "suppressed",
    "skipped_unsubscribed",
    "cancelled",
)
# ``newsletter_send_attempt``: one row per recipient per SMTP attempt.
ATTEMPT_KINDS = ("campaign", "test")
ATTEMPT_OUTCOMES = ("pending", "accepted", "rejected", "unknown")

# Suppression reasons. An ``unsubscribed`` row names its list as provenance;
# the others carry ``""``. Lookups are tenant-wide whatever the list.
REASON_HARD_BOUNCE = "hard_bounce"
REASON_COMPLAINT = "complaint"
REASON_IMPORTED_CLEANED = "imported_cleaned"
REASON_UNSUBSCRIBED = "unsubscribed"
REASONS = (REASON_HARD_BOUNCE, REASON_COMPLAINT, REASON_IMPORTED_CLEANED, REASON_UNSUBSCRIBED)
# A later confirmation clears these; a complaint is never cleared.
CLEARED_BY_CONFIRMATION = (REASON_HARD_BOUNCE, REASON_IMPORTED_CLEANED, REASON_UNSUBSCRIBED)
SOURCES = ("records_event", "reconcile", "unsubscribe_page", "send", "import", "admin")

MAX_TYPE_KEY_LEN = 64  # records' ``MAX_KEY_LEN``
MAX_EMAIL_LEN = 320
