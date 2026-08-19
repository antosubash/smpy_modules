"""AI module constants.

Kept out of the call sites so no module name, route or permission appears as a
bare literal — see scripts/check_hardcoded_strings.py.
"""

from __future__ import annotations

from typing import Final

PACKAGE: Final = "sm_ai"
MODULE_NAME: Final = "Ai"

ROUTE_PREFIX_API: Final = "/api/ai"
VIEW_PREFIX: Final = "/ai"
MENU_URL: Final = f"{VIEW_PREFIX}/"
MENU_GROUP: Final = "Administration"
MENU_ICON: Final = "sparkles"
MENU_ORDER: Final = 116  # just after Branding's 115

# Modules this one depends on (value = that module's ModuleMeta.name).
_MODULE_SETTINGS: Final = "Settings"

# Inertia page identifier. Inlined as a literal at the view (framework SM003/
# SM004 static-AST pairing); a unit test asserts the literal matches this.
_PAGE_SETTINGS: Final = f"{MODULE_NAME}/Settings"

PERM_MANAGE: Final = "ai.manage"

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
