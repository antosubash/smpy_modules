"""Names the module registers under; one place so nothing spells them twice."""

from __future__ import annotations

PACKAGE = "sm_events"
MODULE_NAME = "Events"
DISTRIBUTION = "simple_module_events"
LOCALE_NAMESPACE = "events"
BASE_NAME = "events"

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
_PAGE_CALENDARS = f"{MODULE_NAME}/Calendars"
_PAGE_CATEGORIES = f"{MODULE_NAME}/Categories"
CALENDARS_URL = f"{VIEW_PREFIX}/calendars"
CATEGORIES_URL = f"{VIEW_PREFIX}/categories"
MENU_GROUP = MODULE_NAME
MENU_GROUP_KEY = "events.menu.group"
MENU_LABEL_CALENDARS = "Calendars"
MENU_LABEL_KEY_CALENDARS = "events.menu.calendars"
MENU_ICON_CALENDARS = "calendar"
MENU_LABEL_CATEGORIES = "Event categories"
MENU_LABEL_KEY_CATEGORIES = "events.menu.categories"
MENU_ICON_CATEGORIES = "tag"

# Bounds on times, ranges, rules, revisions and pages.
MAX_EVENT_DAYS = 366
MAX_SERIES_EVENT_DAYS = 31
MAX_RANGE_DAYS = 366
MAX_OCCURRENCES = 2000
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
PUBLISH_DUE_BATCH = 200

# Names.
EVENT_SLUG_FALLBACK = "event"
UID_SUFFIX = "@simple-module-events"
SOURCE_EVENTS = "events"

# Error codes and their default messages.
STALE_CODE = "stale"
STALE_DETAIL = "This was changed by someone else; reload it"
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

# Occurrences.
OCCURRENCE_CONFIRMED = "confirmed"
OCCURRENCE_CANCELLED = "cancelled"
OCCURRENCE_KEY_STAMP = "%Y%m%dT%H%M%SZ"
EDITOR_URL = f"{VIEW_PREFIX}/edit"
