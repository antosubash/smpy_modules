"""AI module constants.

Kept out of the call sites so no module name, route or permission appears as a
bare literal — see scripts/check_hardcoded_strings.py.
"""

from __future__ import annotations

from typing import Final

PACKAGE: Final = "sm_ai"
# Namespace the console strings in ``locales/en.json`` are registered under.
LOCALE_NAMESPACE: Final = "ai"
MODULE_NAME: Final = "Ai"

ROUTE_PREFIX_API: Final = "/api/ai"
VIEW_PREFIX: Final = "/ai"
MENU_URL: Final = f"{VIEW_PREFIX}/"
MENU_GROUP: Final = "Administration"
MENU_ICON: Final = "sparkles"
MENU_ORDER: Final = 116  # just after Branding's 115

# Modules this one depends on (value = that module's ModuleMeta.name).
_MODULE_SETTINGS: Final = "Settings"

# Inertia page identifier, rendered via this constant at the view (the
# in-repo check_hardcoded_strings convention; the framework's SM003/SM004
# literal-pairing convention loses that tie-break — see endpoints/views.py).
# A unit test pins the value to pages/Settings.tsx.
_PAGE_SETTINGS: Final = f"{MODULE_NAME}/Settings"

PERM_MANAGE: Final = "ai.manage"

# CSRF channel between the view (mints into the session), the middleware
# (mirrors to this JS-readable cookie) and the API (verifies this header).
CSRF_COOKIE: Final = "sm_ai_csrf"
CSRF_HEADER: Final = "x-csrf-token"

# Provider identifiers (stored values — changing them breaks existing rows).
PROVIDER_ANTHROPIC: Final = "anthropic"
PROVIDER_OPENAI: Final = "openai"
PROVIDER_GOOGLE: Final = "google"
PROVIDER_OPENAI_COMPATIBLE: Final = "openai_compatible"

CHAT_PROVIDERS: Final = (
    PROVIDER_ANTHROPIC,
    PROVIDER_OPENAI,
    PROVIDER_GOOGLE,
    PROVIDER_OPENAI_COMPATIBLE,
)
# Anthropic offers no embeddings API.
EMBEDDING_PROVIDERS: Final = (
    PROVIDER_OPENAI,
    PROVIDER_GOOGLE,
    PROVIDER_OPENAI_COMPATIBLE,
)

# vLLM and friends ignore the key but the OpenAI protocol requires a non-empty
# value — same literal GeoWiki's AiClientFactory substitutes.
PLACEHOLDER_API_KEY: Final = "not-needed"

SLOT_CHAT: Final = "chat"
SLOT_EMBEDDING: Final = "embedding"
TEST_SLOTS: Final = (SLOT_CHAT, SLOT_EMBEDDING)
TEST_PROMPT: Final = "Reply with the single word: ok"
TEST_TIMEOUT_SECONDS: Final = 30

SECRET_FIELDS: Final = frozenset({"chat_api_key", "embedding_api_key"})
