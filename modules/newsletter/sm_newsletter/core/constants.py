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
# One unsubscribe link per send: ``{UNSUBSCRIBE_PREFIX}<token>``.
UNSUBSCRIBE_PREFIX = f"{PUBLIC_PREFIX}u/"
# The open pixel ``{OPEN_PREFIX}<token>.gif`` and the click redirect
# ``{CLICK_PREFIX}<token>/<position>``.
OPEN_PREFIX = f"{PUBLIC_PREFIX}o/"
CLICK_PREFIX = f"{PUBLIC_PREFIX}c/"
# At most this many distinct links per campaign are tracked, each at most
# MAX_LINK_URL characters (``Link.url``'s max_length; ``content.urls.MAX_URL``,
# 2000, is the tighter bound in practice).
MAX_TRACKED_LINKS = 100
MAX_LINK_URL = 2048
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
_PAGE_SEGMENTS = "Newsletter/Segments"
_PAGE_SUBSCRIBERS = "Newsletter/Subscribers"
_PAGE_SUPPRESSIONS = "Newsletter/Suppressions"
_PAGE_EDITOR = "Newsletter/CampaignEditor"
_PAGE_REPORT = "Newsletter/CampaignReport"
_PAGE_SETTINGS = "Newsletter/Settings"

# Sidebar. The same keys are in ``locales/*.json`` under ``menu``.
MENU_GROUP = "Newsletter"
MENU_GROUP_KEY = "newsletter.menu.group"
MENU_URL = f"{VIEW_PREFIX}/"
MENU_LABEL_CAMPAIGNS = "Campaigns"
MENU_LABEL_KEY_CAMPAIGNS = "newsletter.menu.campaigns"
MENU_ICON_CAMPAIGNS = "mail"
MENU_LABEL_SEGMENTS = "Segments"
MENU_LABEL_KEY_SEGMENTS = "newsletter.menu.segments"
MENU_ICON_SEGMENTS = "filter"
MENU_LABEL_SUBSCRIBERS = "Subscribers"
MENU_LABEL_KEY_SUBSCRIBERS = "newsletter.menu.subscribers"
MENU_ICON_SUBSCRIBERS = "users"
MENU_LABEL_SUPPRESSIONS = "Suppressions"
MENU_LABEL_KEY_SUPPRESSIONS = "newsletter.menu.suppressions"
MENU_ICON_SUPPRESSIONS = "shield"
MENU_LABEL_SETTINGS = "Settings"
MENU_LABEL_KEY_SETTINGS = "newsletter.menu.settings"
MENU_ICON_SETTINGS = "settings"

SEGMENTS_URL = f"{VIEW_PREFIX}/segments"
SUBSCRIBERS_URL = f"{VIEW_PREFIX}/subscribers"
SUPPRESSIONS_URL = f"{VIEW_PREFIX}/suppressions"
# The newsletter settings page; also the settings' ``manage_url``, so the
# generic Settings screen refuses newsletter writes.
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
SOURCES = ("records_event", "reconcile", "unsubscribe_page", "send", "import", "admin")

# Reasons an admin may lift; a complaint is never lifted.
LIFTABLE = (REASON_HARD_BOUNCE, REASON_IMPORTED_CLEANED, REASON_UNSUBSCRIBED)

PERM_RECORDS_VIEW = "records.view"
TAGS_FIELD = "tags"
"""The subscription list's tags multiselect field."""

MAX_TYPE_KEY_LEN = 64  # records' ``MAX_KEY_LEN``
MAX_EMAIL_LEN = 320
MAX_FIRST_NAME_LEN = 200
MAX_SENDER_LEN = 600  # an encoded "Name <address>" header
MAX_AUDIENCE_LEN = 140  # ``newsletter_campaign.audience``: ``tag:<=100 chars>`` fits

# Why a campaign is paused; ``paused_reason`` stores ``"<code>|<detail>"``,
# clipped to ``MAX_PAUSED_REASON`` (the column's length).
MAX_PAUSED_REASON = 1000
PAUSE_MANUAL = "manual"
PAUSE_SMTP_REJECTED = "smtp_rejected"
PAUSE_SMTP_AUTH = "smtp_auth"
PAUSE_LIST_UNAVAILABLE = "list_unavailable"
PAUSE_HTTPS_REQUIRED = "https_required"
"""The snapshot's bases are not both ``https://`` and the transport is ``smtp``."""
PAUSE_AUDIENCE_UNAVAILABLE = "audience_unavailable"
"""Records refused the audience's stored filter terms at freeze (a reason other
than ``reindexing`` or ``not_a_list``)."""
PAUSE_CODES = (
    PAUSE_MANUAL,
    PAUSE_SMTP_REJECTED,
    PAUSE_SMTP_AUTH,
    PAUSE_LIST_UNAVAILABLE,
    PAUSE_HTTPS_REQUIRED,
    PAUSE_AUDIENCE_UNAVAILABLE,
)

# ``newsletter_send.error_kind`` of a row that ended ``failed`` or ``bounced``.
ERROR_OUTCOME_UNKNOWN = "outcome_unknown"
ERROR_RETRIES_EXHAUSTED = "retries_exhausted"
ERROR_INVALID_MESSAGE = "invalid_message"
ERROR_HARD_BOUNCE = "hard_bounce"

# Suppression sources written by the sending path, the unsubscribe page and an
# admin's unsubscribe (all in ``SOURCES``).
SOURCE_SEND = "send"
SOURCE_UNSUBSCRIBE_PAGE = "unsubscribe_page"
SOURCE_ADMIN = "admin"
