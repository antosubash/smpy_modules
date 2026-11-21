"""Names the module registers under; one place so nothing spells them twice."""

# ruff: noqa: F401 - the re-exports below are the point
from __future__ import annotations

from sm_events.core.constants.extensions import *  # noqa: F403 - plugins (PR 6)
from sm_events.core.constants.feed_tokens import *  # noqa: F403 - private feed links (PR 5)
from sm_events.core.constants.imports import *  # noqa: F403 - the .ics import (PR 5)

# The public surface's names live in ``public.py`` and are re-exported here, so every
# ``constants.X`` keeps working.
from sm_events.core.constants.public import (
    _PAGE_PUBLIC_EVENT,
    _PAGE_PUBLIC_INDEX,
    _PAGE_PUBLIC_NOT_FOUND,
    BLOCK_CALENDARS_MAX,
    DEFAULT_PUBLIC_PREFIX,
    FEED_DAYS_AHEAD,
    FEED_DAYS_BACK,
    FEED_MAX_COMPONENTS,
    FEED_MAX_EVENTS,
    FEED_RATE,
    FEED_ZONE_LAST_YEAR,
    FEED_ZONE_YEARS_AHEAD,
    ICS_MEDIA_TYPE,
    INVALID_QUERY_CODE,
    INVALID_QUERY_DETAIL,
    JSON_MEDIA_TYPE,
    NEXT_OCCURRENCES,
    NOT_FOUND_SUGGESTIONS,
    NOT_FOUND_WINDOW_DAYS,
    PAGE_DIGITS_MAX,
    PAGE_SIZE,
    PRODID,
    PUBLIC_API_RATE,
    PUBLIC_CACHE_SECONDS,
    PUBLIC_LISTING_CACHE_MAX,
    PUBLIC_METHODS,
    PUBLIC_PREFIX_PATTERN,
    PUBLIC_SWR_SECONDS,
    RESERVED_PREFIX_SEGMENTS,
    RESERVED_SLUGS,
    SEGMENT_API,
    SEGMENT_CALENDAR,
    SEGMENT_CALENDAR_FEED,
    SEGMENT_PRIVATE_FEED,
    SEGMENT_SITEMAP,
    SITEMAP_MAX_URLS,
    SITEMAP_NAMESPACE,
    SLUG_RESERVED_CODE,
    SLUG_RESERVED_DETAIL,
    SUB_EVENTS_MAX,
    UPCOMING_BLOCK_DEFAULT,
    UPCOMING_BLOCK_MAX,
    XML_MEDIA_TYPE,
)  # isort: skip
from sm_events.core.constants.reminders import *  # noqa: F403 - reminders (PR 8)

from sm_events.core.constants.names import MODULE_NAME  # isort: skip

PACKAGE = "sm_events"
DISTRIBUTION = "simple_module_events"
LOCALE_NAMESPACE = "events"
BASE_NAME = "events"

ROUTE_PREFIX_API = "/api/events"
PUBLIC_BLOCKS_API = f"{ROUTE_PREFIX_API}/public"
"""Where the pagebuilder blocks read: three anonymous, fixed-path routes (a block cannot learn
the configurable public prefix)."""
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
_MODULE_BACKGROUND_TASKS = "BackgroundTasks"
DEPENDS_ON = (_MODULE_SETTINGS, _MODULE_SHARING, _MODULE_BACKGROUND_TASKS)

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

OWNER_ONLY_DETAIL = "Only the calendar's owner or an events manager can do this"

# Calendars.
CALENDARS_MAX = 500
CALENDAR_SLUG_FALLBACK = "calendar"
SLUG_TAKEN_DETAIL = "That slug is already in use"
EDIT_REFUSED_DETAIL = "You can see this calendar but not change it"
OWNER_NOT_ALLOWED_CODE = "owner_not_allowed"
OWNER_NOT_ALLOWED_DETAIL = "The new owner must be an active member of this organisation"

# The share picker and the owner check read the user directory.
CANDIDATES_MAX = 20
CANDIDATES_SCAN = 100
DIRECTORY_UNAVAILABLE_CODE = "user_directory_unavailable"
DIRECTORY_UNAVAILABLE_DETAIL = "The user directory is not available"

# Categories.
CATEGORY_NAME_MAX = 100
CATEGORY_SLUG_FALLBACK = "category"
CATEGORIES_MAX = 500
DEFAULT_LOCALE_REQUIRED_DETAIL = "A name in the default language is required"
UNKNOWN_LOCALE_DETAIL = "That language is not one of the content locales"

# Console pages and sidebar entries.
_PAGE_CALENDAR = f"{MODULE_NAME}/Calendar"
_PAGE_CALENDARS = f"{MODULE_NAME}/Calendars"
_PAGE_CATEGORIES = f"{MODULE_NAME}/Categories"
_PAGE_EVENTS = f"{MODULE_NAME}/Events"
_PAGE_EVENT_EDITOR = f"{MODULE_NAME}/EventEditor"
_PAGE_IMPORT = f"{MODULE_NAME}/Import"
CALENDAR_URL = f"{VIEW_PREFIX}/"
CALENDARS_URL = f"{VIEW_PREFIX}/calendars"
CATEGORIES_URL = f"{VIEW_PREFIX}/categories"
EVENTS_URL = f"{VIEW_PREFIX}/list"
IMPORT_URL = f"{VIEW_PREFIX}/import"
EVENT_NEW_SEGMENT = "new"
MENU_GROUP = MODULE_NAME
MENU_GROUP_KEY = "events.menu.group"
MENU_LABEL_CALENDAR = "Calendar"
MENU_LABEL_KEY_CALENDAR = "events.menu.calendar"
MENU_ICON_CALENDAR = "calendar"
MENU_LABEL_CALENDARS = "Calendars"
MENU_LABEL_KEY_CALENDARS = "events.menu.calendars"
MENU_ICON_CALENDARS = "layers"
MENU_LABEL_CATEGORIES = "Event categories"
MENU_LABEL_KEY_CATEGORIES = "events.menu.categories"
MENU_ICON_CATEGORIES = "tag"
MENU_LABEL_EVENTS = "Events"
MENU_LABEL_KEY_EVENTS = "events.menu.events"
MENU_ICON_EVENTS = "list"

# Bounds on times, ranges, rules, revisions and pages.
MAX_EVENT_DAYS = 366
MAX_SERIES_EVENT_DAYS = 31
# A UTC offset can change inside an instance (31 wall-clock days are 31 days and an
# hour across a fall-back), so every look-back for one adds this many days.
LOOK_BACK_MARGIN_DAYS = 1
MAX_RANGE_DAYS = 366
# A path number and an occurrence's original start: what a signed 32-bit column holds and
# the years a calendar means (a bound keeps ``+ 1 microsecond`` and zone maths in range).
INT32_MAX = 2**31 - 1
PAGE_MAX = 10_000
"""The highest page number a list takes: ``(page - 1) * page_size`` stays far inside every
integer column and OFFSET, on SQLite and Postgres."""
ORIGINAL_START_MIN_YEAR = 1900
ORIGINAL_START_MAX_YEAR = 9000
MAX_OCCURRENCES = 2000
# Cards for another module (``contracts.cards``): the most one search returns, how many
# matching events it looks at before cutting, and how many times it re-reads series the
# occurrences read's own cap starved (a bound on statements, never on correctness of a card).
MAX_EVENT_SEARCH_LIMIT = 50
CARD_SEARCH_SCAN = 50
CARD_READ_ROUNDS = 3
SERIES_FETCH_MAX = 2000
RRULE_MAX_LEN = 500
RRULE_MAX_INTERVAL = 99
RRULE_MAX_COUNT = 730
RRULE_MAX_YEARS = 100
REVISIONS_KEPT = 100
PREVIEW_MAX = 50
PREVIEW_DEFAULT = 10
EVENTS_PAGE_MAX = 100
EVENTS_PAGE_DEFAULT = 50
DESCRIPTION_RAW_MAX = 200_000
DESCRIPTION_MAX = 100_000
NOTE_MAX = 1000
QUERY_MAX = 100
URL_MAX = 2048
ORGANISER_MAX = 200
VENUE_MAX = 200
ADDRESS_MAX = 500
RRULE_INPUT_MAX = 1000
TITLE_MAX = 300
SUMMARY_MAX = 1000
SEO_TITLE_MAX = 300
SEO_DESCRIPTION_MAX = 500
TYPE_NAME_MAX = 64
TIMES_FIELD_MAX = 40
TEXTS_MAX = 20
PUBLISH_DUE_BATCH = 200

# Names.
EVENT_SLUG_FALLBACK = "event"
UID_SUFFIX = "@simple-module-events"
UID_MAX = 255
SOURCE_EVENTS = "events"

# Error codes and their default messages.
STALE_CODE = "stale"
STALE_DETAIL = "This was changed by someone else; reload it"
CURRENT_REVISION_HEADER = "X-Current-Revision"
OVERRIDES_ORPHANED_CODE = "overrides_orphaned"
OVERRIDES_ORPHANED_DETAIL = "This change would orphan overrides of single occurrences"
HAS_SUB_EVENTS_CODE = "has_sub_events"
HAS_SUB_EVENTS_DETAIL = "Delete or move the sub-events first"
INVALID_TRANSITION_CODE = "invalid_transition"
INVALID_TRANSITION_DETAIL = "The event cannot move to that state from its current one"
PUBLISH_REQUIRED_CODE = "publish_required"
PUBLISH_REQUIRED_DETAIL = "Changing a published or scheduled event needs the publish permission"
INVALID_RRULE_CODE = "invalid_rrule"
INVALID_RRULE_DETAIL = "The recurrence rule is not valid"
RRULE_FREQUENCY_REFUSED_CODE = "rrule_frequency_refused"
RRULE_FREQUENCY_REFUSED_DETAIL = "Only daily, weekly, monthly and yearly rules are allowed"
START_FIELD = "times.start"
START_NOT_IN_RULE_CODE = "start_not_in_rule"
START_NOT_IN_RULE_DETAIL = "The first occurrence must be the event's own start"
INVALID_LOCAL_TIME_CODE = "invalid_local_time"
INVALID_LOCAL_TIME_DETAIL = "That local time is not valid in this timezone"
END_BEFORE_START_CODE = "end_before_start"
END_BEFORE_START_DETAIL = "The end must be after the start"
DURATION_TOO_LONG_CODE = "duration_too_long"
DURATION_TOO_LONG_DETAIL = "The event lasts too long"
INVALID_RANGE_CODE = "invalid_range"
INVALID_RANGE_DETAIL = "The range must end after it starts"
RANGE_TOO_LONG_CODE = "range_too_long"
RANGE_TOO_LONG_DETAIL = "The range is longer than the allowed maximum"
DEFAULT_LOCALE_REQUIRED_CODE = "default_locale_required"
IMAGE_OFF_SITE_CODE = "image_off_site"
IMAGE_OFF_SITE_DETAIL = "Use an image from this site's media library"
UNKNOWN_CATEGORY_CODE = "unknown_category"
UNKNOWN_CATEGORY_DETAIL = "That category does not exist"
UNKNOWN_TYPE_CODE = "unknown_type"
UNKNOWN_TYPE_DETAIL = "That event type is not supported"
INVALID_PARENT_CODE = "invalid_parent"
INVALID_PARENT_DETAIL = "That parent event is not allowed"
IMMUTABLE_FIELD_CODE = "immutable_field"
IMMUTABLE_FIELD_DETAIL = "That field cannot be changed after creation"
NOT_RECURRING_CODE = "not_recurring"
NOT_RECURRING_DETAIL = "The event does not recur"
NOT_AN_OCCURRENCE_CODE = "not_an_occurrence"
NOT_AN_OCCURRENCE_DETAIL = "That is not an occurrence of the event's rule"
DESCRIPTION_TOO_LONG_CODE = "description_too_long"
DESCRIPTION_TOO_LONG_DETAIL = "The description is too long"

STATUS_SCHEDULED = "scheduled"
"""A list filter, not a stored status: a draft or in-review event with ``publish_at`` set."""

# Revisions: what a history row's action may be.
REVISION_ACTIONS = (
    "created",
    "updated",
    "override_set",
    "override_cleared",
    "submitted",
    "withdrawn",
    "approved",
    "scheduled",
    "unscheduled",
    "rejected",
    "unpublished",
    "published_scheduled",
    "trashed",
    "restored",
)

# Occurrences.
OCCURRENCE_CONFIRMED = "confirmed"
OCCURRENCE_CANCELLED = "cancelled"
OCCURRENCE_KEY_STAMP = "%Y%m%dT%H%M%SZ"
EDITOR_URL = f"{VIEW_PREFIX}/edit"
