"""Registration identifiers and ingestion limits."""

PACKAGE = "sm_analytics"
MODULE_NAME = "Analytics"
_MODULE_SETTINGS = "Settings"
API_PREFIX = "/api/analytics"
VIEW_PREFIX = "/analytics"
PERM_VIEW = "analytics.view"
PERM_MANAGE = "analytics.manage"
_PAGE_DASHBOARD = "Analytics/Dashboard"
COLLECT_PATH = f"{API_PREFIX}/collect"
CONFIG_PATH = f"{API_PREFIX}/config"
MAX_BODY_BYTES = 8192
COLLECT_RATE = "120/minute"
# Every navigation of every signed-in or anonymous page reads the config, tracked
# or not, so one office behind a NAT (or an e2e shard on 127.0.0.1) spends 120 a
# minute quickly; the 429 then shows as a console error on unrelated pages.
CONFIG_RATE = "1200/minute"
UTM_PARAMETERS = frozenset({"utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content"})
EXCLUDED_SEGMENTS = frozenset({"auth", "login", "logout", "register", "settings", "analytics"})
