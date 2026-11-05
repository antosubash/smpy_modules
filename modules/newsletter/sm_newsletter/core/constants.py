"""Names the module registers under; one place so nothing spells them twice."""

from __future__ import annotations

PACKAGE = "sm_newsletter"
MODULE_NAME = "Newsletter"
DISTRIBUTION = "simple_module_newsletter"
LOCALE_NAMESPACE = "newsletter"
BASE_NAME = "newsletter"

ROUTE_PREFIX_API = "/api/newsletter"
VIEW_PREFIX = "/admin/newsletter"
PUBLIC_PREFIX = "/newsletter/"
# The SYSTEM-scope branding logo, served anonymously for emails (ruling C8).
BRAND_LOGO_PATH = f"{PUBLIC_PREFIX}brand/logo"
# Previews and test sends have no send row, so no MAC: their unsubscribe links
# carry this token, which the unsubscribe page treats like a forged one (R1).
TEST_UNSUBSCRIBE_TOKEN = "test"
# The email accent without branding, or when branding sets no primary colour.
DEFAULT_ACCENT = "#2563eb"

PERM_GROUP = MODULE_NAME
PERM_GROUP_KEY = "newsletter.permission_group"
PERM_VIEW = "newsletter.view"
PERM_EDIT = "newsletter.edit"
PERM_SEND = "newsletter.send"
PERM_MANAGE = "newsletter.manage"
# The framework settings module's system-scope write permission
# (`settings.constants.PERM_EDIT`; a test keeps the two equal). Writing the SMTP
# password needs it as well as PERM_MANAGE.
PERM_SETTINGS_EDIT = "settings.edit"
PERMISSIONS = (PERM_VIEW, PERM_EDIT, PERM_SEND, PERM_MANAGE)

_MODULE_SETTINGS = "Settings"
_MODULE_RECORDS = "Records"
_MODULE_BACKGROUND_TASKS = "BackgroundTasks"
DEPENDS_ON = (_MODULE_SETTINGS, _MODULE_RECORDS, _MODULE_BACKGROUND_TASKS)

TENANT_REQUIRED_CODE = "tenant_required"
NOT_FOUND_DETAIL = "Not found"

# Inertia page names (``sm_newsletter/pages/<name>.tsx``).
_PAGE_CAMPAIGNS = "Newsletter/Campaigns"
_PAGE_EDITOR = "Newsletter/CampaignEditor"
_PAGE_SETTINGS = "Newsletter/Settings"

# Sidebar. The same keys are in ``locales/*.json`` under ``menu``.
MENU_GROUP = "Newsletter"
MENU_GROUP_KEY = "newsletter.menu.group"
MENU_URL = f"{VIEW_PREFIX}/"
MENU_LABEL_CAMPAIGNS = "Campaigns"
MENU_LABEL_KEY_CAMPAIGNS = "newsletter.menu.campaigns"
MENU_ICON_CAMPAIGNS = "mail"
MENU_LABEL_SETTINGS = "Settings"
MENU_LABEL_KEY_SETTINGS = "newsletter.menu.settings"
MENU_ICON_SETTINGS = "settings"

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
ATTEMPT_OUTCOMES = ("pending", "accepted", "rejected", "unknown", "failed")

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
