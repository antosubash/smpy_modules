# AI Base Module (`simple_module_ai`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A distributable base module giving every SimpleModule app one provider-configurable Pydantic AI service layer (chat + embeddings), DB-backed settings with encrypted keys, and an admin settings page with per-slot test-connection.

**Architecture:** Zero-table module on the framework settings store (`register_module_settings` + hydration + `apply_changes_and_reload`, exactly branding's pattern). Consumers `from sm_ai.contracts import resolve_model, resolve_embedder` — a module-global services holder makes that work without `app.state` or sessions in signatures.

**Tech Stack:** Python 3.12, FastAPI, pydantic-settings, pydantic-ai-slim v2 (`anthropic,openai,google` extras), cryptography (Fernet), React 19 + Inertia + `@simple-module-py/ui`, pytest + `simple_module_test`, Playwright.

**Spec:** `docs/superpowers/specs/2026-08-19-ai-module-design.md`

## Global Constraints

- Repo version is **0.0.5** — the module's `version` must match (`scripts/bump_version.py --check-current` verifies).
- Framework deps use **ranges, never `==`**: `>=0.0.25,<0.1`.
- **300-line cap** on every `.py`/`.ts`/`.tsx` (`scripts/check_file_size.py`).
- Module names, routes, permissions, page names live in `constants.py` — `scripts/check_hardcoded_strings.py` fails on bare literals at call sites (exception: the Inertia page name is inlined at the `inertia.render` call and unit-tested equal to the constant — news/branding convention).
- **Nothing in `sm_ai/pages/` except real Inertia pages** — extractions go to `components/` or `utils/`.
- Import package is **`sm_ai`** (PyPI `ai` = Vercel SDK collision); everything user-visible says "ai"/"Ai"/"AI".
- Run all Python entry points from the **repo root** unless the step says `cd modules/ai`.
- Module test suites run from inside `modules/ai/` so they pick up its own pytest config.
- UI copy is hardcoded English (repo convention — no i18n).
- No migrations, no SQLModel tables.
- `ModuleMeta.name = "Ai"` → the framework's page manifest keys pages as `Ai/<PageName>` (`manifest.py` uses `mod.meta.name`).

---

### Task 1: Package scaffold, contracts errors, crypto layer

**Files:**
- Create: `modules/ai/pyproject.toml`
- Create: `modules/ai/package.json`
- Create: `modules/ai/README.md` (placeholder H1 now; completed in Task 7)
- Create: `modules/ai/sm_ai/__init__.py` (empty)
- Create: `modules/ai/sm_ai/constants.py`
- Create: `modules/ai/sm_ai/contracts/__init__.py` (errors re-export for now)
- Create: `modules/ai/sm_ai/contracts/errors.py`
- Create: `modules/ai/sm_ai/crypto.py`
- Create: `modules/ai/tests/test_crypto.py`
- Modify: `host/pyproject.toml` (dependency + workspace source — makes `uv sync` install the member editable)

**Interfaces:**
- Produces: `AiError`, `AiNotConfigured(field, hint="")` (attrs `.field`), `AiKeyUnreadable(field)`; `crypto.encrypt_value(plain: str) -> str`, `crypto.decrypt_value(stored: str, field: str) -> str`, `crypto.ENC_PREFIX = "enc:v1:"`; all names in `constants.py` below.

- [ ] **Step 1: Write `modules/ai/pyproject.toml`**

```toml
[project]
name = "simple_module_ai"
version = "0.0.5"
description = "AI base module: provider-configurable Pydantic AI service layer, encrypted key storage, admin settings UI"
requires-python = ">=3.12"
readme = "README.md"
license = "MIT"
authors = [{ name = "Anto Subash", email = "antosubash@live.com" }]
keywords = ["simple-module", "ai", "llm", "pydantic-ai", "embeddings"]
# Ranges, never `==`: an exact framework pin makes a published module
# uninstallable in any host running a newer framework build.
dependencies = [
    "simple_module_core>=0.0.25,<0.1",
    "simple_module_db>=0.0.25,<0.1",
    "simple_module_hosting>=0.0.25,<0.1",
    # Floor verified: register_module_settings and apply_changes_and_reload
    # both exist at 0.0.25.
    "simple_module_settings>=0.0.25,<0.1",
    "pydantic-ai-slim[anthropic,openai,google]>=2.0,<3",
    "pydantic-settings>=2.0",
    "cryptography>=42.0",
]

[project.urls]
Repository = "https://github.com/antosubash/simple_module_python_modules"

[project.entry-points.simple_module]
ai = "sm_ai.module:AiModule"

[project.optional-dependencies]
dev = ["pytest>=8.0", "pytest-asyncio>=0.24", "simple_module_test>=0.0.25,<0.1"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["sm_ai"]

# package.json lives at the module root so npm workspaces see it; copying it
# into the package lets the host discover JS deps after a pip install. This
# module ships no bundled frontend build, so there is no dist to include.
[tool.hatch.build.targets.wheel.force-include]
"package.json" = "sm_ai/package.json"

[tool.pytest.ini_options]
asyncio_mode = "auto"
```

- [ ] **Step 2: Write `modules/ai/package.json`** (mirrors news; no extra JS deps — the page uses only the shared UI kit)

```json
{
  "name": "@simple-module-py/ai",
  "version": "0.0.5",
  "private": true,
  "description": "Frontend assets for the AI module",
  "peerDependencies": {
    "react": "^19.0.0",
    "react-dom": "^19.0.0",
    "@inertiajs/react": "^2.0.0",
    "@simple-module-py/ui": "*"
  },
  "devDependencies": {
    "@simple-module-py/tsconfig": "*"
  },
  "dependencies": {}
}
```

- [ ] **Step 3: Write `modules/ai/README.md` placeholder**

```markdown
# simple_module_ai

AI base module for SimpleModule apps. Full README written in Task 7 (Install / Usage / settings / permissions / consuming guide).
```

- [ ] **Step 4: Write `modules/ai/sm_ai/constants.py`**

First verify the settings module's meta name (expected `"Settings"`):

Run: `uv run python -c "from settings.module import SettingsModule; print(SettingsModule.meta.name)"`

```python
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
```

- [ ] **Step 5: Write `modules/ai/sm_ai/contracts/errors.py`**

```python
"""Exceptions consuming modules catch. No imports from the rest of sm_ai —
this file sits at the bottom of the dependency graph."""

from __future__ import annotations


class AiError(Exception):
    """Base class for AI module errors."""


class AiNotConfigured(AiError):
    """A required connection setting is missing or invalid."""

    def __init__(self, field: str, hint: str = "") -> None:
        self.field = field
        message = f"AI is not configured: {field!r} is missing or invalid."
        if hint:
            message = f"{message} {hint}"
        super().__init__(message)


class AiKeyUnreadable(AiError):
    """A stored key has the enc:v1: prefix but cannot be decrypted."""

    def __init__(self, field: str) -> None:
        self.field = field
        super().__init__(
            f"The stored key {field!r} cannot be decrypted — SM_SECRET_KEY has "
            "changed. Re-enter the key on the AI settings page."
        )
```

- [ ] **Step 6: Write `modules/ai/sm_ai/contracts/__init__.py`** (errors only for now; resolve functions land in Task 3)

```python
"""Public surface for consuming modules."""

from __future__ import annotations

from sm_ai.contracts.errors import AiError, AiKeyUnreadable, AiNotConfigured

__all__ = ["AiError", "AiKeyUnreadable", "AiNotConfigured"]
```

- [ ] **Step 7: Write the failing crypto tests** — `modules/ai/tests/test_crypto.py`

```python
"""Fernet layer: roundtrip, the three stored-value states, missing secret."""

from __future__ import annotations

import pytest
from sm_ai import crypto
from sm_ai.contracts.errors import AiKeyUnreadable

SECRET = "test-secret-key-for-crypto"


@pytest.fixture(autouse=True)
def _secret_env(monkeypatch):
    monkeypatch.setenv("SM_SECRET_KEY", SECRET)
    crypto._warned_plaintext.clear()


class TestEncrypt:
    def test_roundtrip(self):
        stored = crypto.encrypt_value("sk-ant-abc123")
        assert stored.startswith(crypto.ENC_PREFIX)
        assert crypto.decrypt_value(stored, "chat_api_key") == "sk-ant-abc123"

    def test_each_encryption_differs(self):
        # Fernet includes a random IV — equality would mean something is wrong.
        assert crypto.encrypt_value("x") != crypto.encrypt_value("x")

    def test_missing_secret_key_raises(self, monkeypatch):
        monkeypatch.delenv("SM_SECRET_KEY", raising=False)
        with pytest.raises(RuntimeError, match="SM_SECRET_KEY"):
            crypto.encrypt_value("x")


class TestDecrypt:
    def test_empty_string_passes_through(self):
        assert crypto.decrypt_value("", "chat_api_key") == ""

    def test_wrong_secret_raises_unreadable(self, monkeypatch):
        stored = crypto.encrypt_value("sk-123")
        monkeypatch.setenv("SM_SECRET_KEY", "a-different-secret")
        with pytest.raises(AiKeyUnreadable) as exc:
            crypto.decrypt_value(stored, "chat_api_key")
        assert exc.value.field == "chat_api_key"

    def test_garbage_after_prefix_raises_unreadable(self):
        with pytest.raises(AiKeyUnreadable):
            crypto.decrypt_value(crypto.ENC_PREFIX + "not-a-token", "chat_api_key")

    def test_plaintext_passes_through_with_warning(self, caplog):
        # A key pasted through the generic settings UI or seeded via env.
        with caplog.at_level("WARNING"):
            assert crypto.decrypt_value("sk-plain", "chat_api_key") == "sk-plain"
        assert any("unencrypted" in r.message for r in caplog.records)

    def test_plaintext_warns_only_once_per_field(self, caplog):
        with caplog.at_level("WARNING"):
            crypto.decrypt_value("sk-plain", "chat_api_key")
            crypto.decrypt_value("sk-plain", "chat_api_key")
        assert sum("unencrypted" in r.message for r in caplog.records) == 1
```

- [ ] **Step 8: Wire the host and sync so the member installs**

In `host/pyproject.toml` add `"simple_module_ai",` to `dependencies` (after `simple_module_news`) and:

```toml
[tool.uv.sources.simple_module_ai]
workspace = true
```

Run: `uv sync` (repo root). Expected: resolves and installs `simple_module_ai` editable plus `pydantic-ai-slim` + extras.

- [ ] **Step 9: Run tests to verify they fail**

Run: `cd modules/ai && uv run pytest tests/test_crypto.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'sm_ai.crypto'`

- [ ] **Step 10: Write `modules/ai/sm_ai/crypto.py`**

```python
"""Fernet encryption for stored provider keys.

The key derives from ``SM_SECRET_KEY`` (SHA-256 → urlsafe base64), read
straight from the environment through a private BaseSettings — no coupling to
app.state or hosting internals. Stored format is ``enc:v1:<fernet token>``:

- prefix present and decrypts        → plaintext key
- prefix present, decryption fails   → AiKeyUnreadable (secret key changed)
- no prefix                          → treated as plaintext, warned once
  (covers keys pasted through the generic settings UI or seeded from env)
"""

from __future__ import annotations

import logging
from base64 import urlsafe_b64encode
from hashlib import sha256

from cryptography.fernet import Fernet, InvalidToken
from pydantic_settings import BaseSettings, SettingsConfigDict

from sm_ai.contracts.errors import AiKeyUnreadable

logger = logging.getLogger(__name__)

ENC_PREFIX = "enc:v1:"

# Fields already warned about this process — one line per field is signal,
# one per read is noise.
_warned_plaintext: set[str] = set()


class _CryptoEnv(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SM_", extra="ignore")

    secret_key: str = ""


def _fernet() -> Fernet:
    secret = _CryptoEnv().secret_key
    if not secret:
        raise RuntimeError(
            "SM_SECRET_KEY is not set — the AI module needs it to encrypt "
            "stored provider keys."
        )
    return Fernet(urlsafe_b64encode(sha256(secret.encode()).digest()))


def encrypt_value(plain: str) -> str:
    """Encrypt a provider key for storage."""
    return ENC_PREFIX + _fernet().encrypt(plain.encode()).decode()


def decrypt_value(stored: str, field: str) -> str:
    """Return the plaintext key for a stored value (see module docstring)."""
    if not stored:
        return ""
    if stored.startswith(ENC_PREFIX):
        try:
            return _fernet().decrypt(stored[len(ENC_PREFIX) :].encode()).decode()
        except InvalidToken as exc:
            raise AiKeyUnreadable(field) from exc
    if field not in _warned_plaintext:
        _warned_plaintext.add(field)
        logger.warning(
            "AI setting %r is stored unencrypted; re-save it via the AI "
            "settings page to encrypt it.",
            field,
        )
    return stored
```

- [ ] **Step 11: Run tests to verify they pass**

Run: `cd modules/ai && uv run pytest tests/test_crypto.py -v`
Expected: all PASS

- [ ] **Step 12: Commit**

```bash
git add modules/ai host/pyproject.toml uv.lock
git commit -m "feat(ai): scaffold simple_module_ai with contracts errors and Fernet crypto layer"
```

---

### Task 2: AiSettings and the services holder

**Files:**
- Create: `modules/ai/sm_ai/settings.py`
- Create: `modules/ai/sm_ai/services.py`
- Create: `modules/ai/tests/test_settings.py`

**Interfaces:**
- Consumes: nothing beyond Task 1.
- Produces: `AiSettings(BaseSettings)` with the 9 fields below; `AiServices` dataclass (`settings` attr); `services.install(AiServices) -> AiServices`, `services.reset() -> None`, `services.current_settings() -> AiSettings` (raises `AiNotConfigured("module", ...)` when not installed).

- [ ] **Step 1: Write the failing tests** — `modules/ai/tests/test_settings.py`

```python
"""Settings defaults, env seeding, and the module-global services holder."""

from __future__ import annotations

import pytest
from sm_ai import services
from sm_ai.contracts.errors import AiNotConfigured
from sm_ai.settings import AiSettings


@pytest.fixture(autouse=True)
def _reset_holder():
    yield
    services.reset()


class TestDefaults:
    def test_chat_defaults(self):
        s = AiSettings()
        assert s.chat_provider == "anthropic"
        assert s.chat_model == "claude-opus-5"
        assert s.chat_base_url == ""
        assert s.chat_api_key == ""

    def test_embeddings_unconfigured_by_default(self):
        s = AiSettings()
        assert s.embedding_provider == ""
        assert s.embedding_model == ""
        assert s.embedding_dim == 0


class TestEnvSeeding:
    def test_env_vars_fill_unset_fields(self, monkeypatch):
        # hydrate_settings constructs AiSettings(**db_overrides); BaseSettings
        # then reads SM_AI_* env for anything the DB didn't override. This is
        # how dev/CI configure with zero DB rows.
        monkeypatch.setenv("SM_AI_CHAT_MODEL", "claude-sonnet-5")
        monkeypatch.setenv("SM_AI_EMBEDDING_DIM", "4096")
        s = AiSettings()
        assert s.chat_model == "claude-sonnet-5"
        assert s.embedding_dim == 4096

    def test_explicit_kwargs_beat_env(self, monkeypatch):
        monkeypatch.setenv("SM_AI_CHAT_MODEL", "from-env")
        assert AiSettings(chat_model="from-db").chat_model == "from-db"


class TestHolder:
    def test_current_settings_before_install_raises(self):
        with pytest.raises(AiNotConfigured) as exc:
            services.current_settings()
        assert exc.value.field == "module"

    def test_install_then_read(self):
        installed = services.install(services.AiServices(settings=AiSettings()))
        assert services.current_settings() is installed.settings

    def test_hot_swap_visible_through_holder(self):
        # apply_changes_and_reload assigns services.settings = validated on the
        # same AiServices instance app.state holds — the holder must see it.
        installed = services.install(services.AiServices(settings=AiSettings()))
        installed.settings = AiSettings(chat_model="swapped")
        assert services.current_settings().chat_model == "swapped"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd modules/ai && uv run pytest tests/test_settings.py -v`
Expected: FAIL — `No module named 'sm_ai.settings'`

- [ ] **Step 3: Write `modules/ai/sm_ai/settings.py`**

```python
"""AI connection settings — DB-backed via ``register_module_settings``.

The module owns *connection* configuration (provider, endpoint, key, model
name); consuming modules own *behaviour* (agents, prompts, temperature,
retries, streaming). Two slots because real deployments run chat and
embeddings as separate endpoints (e.g. two vLLM processes on one GPU host).

Values persist in the shared settings store at SYSTEM scope and hot-swap on
save. Unset fields fall back to ``SM_AI_*`` environment variables — dev, CI
and e2e configure with zero DB rows; DB values win when present.

API keys are stored as ``enc:v1:<fernet>`` — see ``sm_ai.crypto``.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict

from sm_ai import constants


class AiSettings(BaseSettings):
    """Connection configuration for the chat and embedding slots."""

    model_config = SettingsConfigDict(env_prefix="SM_AI_", extra="ignore")

    # --- chat slot ---
    chat_provider: str = constants.PROVIDER_ANTHROPIC
    chat_model: str = "claude-opus-5"  # bare model name, no provider prefix
    chat_base_url: str = ""  # required for openai_compatible; optional override otherwise
    chat_api_key: str = ""

    # --- embedding slot (unconfigured by default) ---
    embedding_provider: str = ""  # "" = embeddings not configured
    embedding_model: str = ""
    embedding_base_url: str = ""
    embedding_api_key: str = ""
    embedding_dim: int = 0  # consumer-visible (vector stores fix width to it)
```

- [ ] **Step 4: Write `modules/ai/sm_ai/services.py`**

```python
"""Module-scoped state container plus the module-global holder.

``AiServices`` is stored as ``app.state.sm_ai`` by
:meth:`AiModule.register_settings` (via ``register_module_settings``); the
hosting lifespan hydrates ``settings`` from the DB before ``on_startup`` and
``settings.reload.apply_changes_and_reload`` hot-swaps it on save — both by
assigning ``services.settings`` on the *same instance*.

``install`` keeps a module-global reference to that instance so
``sm_ai.contracts`` works by direct import: consumers never touch app.state
and pass no sessions.
"""

from __future__ import annotations

from dataclasses import dataclass

from sm_ai.contracts.errors import AiNotConfigured
from sm_ai.settings import AiSettings


@dataclass
class AiServices:
    """AI module singletons."""

    settings: AiSettings


_current: AiServices | None = None


def install(services: AiServices) -> AiServices:
    """Record the host's AiServices instance; returns it for the factory."""
    global _current
    _current = services
    return services


def reset() -> None:
    """Drop the installed instance (tests only)."""
    global _current
    _current = None


def current_settings() -> AiSettings:
    """The hydrated settings of the running host."""
    if _current is None:
        raise AiNotConfigured(
            "module",
            "The AI module is not initialised — is a host running with "
            "simple_module_ai installed?",
        )
    return _current.settings
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd modules/ai && uv run pytest tests/test_settings.py -v`
Expected: all PASS

- [ ] **Step 6: Commit**

```bash
git add modules/ai/sm_ai/settings.py modules/ai/sm_ai/services.py modules/ai/tests/test_settings.py
git commit -m "feat(ai): AiSettings with env seeding and the module-global services holder"
```

---

### Task 3: Resolve layer + public contracts

**Files:**
- Create: `modules/ai/sm_ai/resolve.py`
- Modify: `modules/ai/sm_ai/contracts/__init__.py`
- Create: `modules/ai/tests/test_resolve.py`

**Interfaces:**
- Consumes: `AiSettings`, `services.current_settings()`, `crypto.decrypt_value`, constants.
- Produces: `resolve.build_chat_model(settings, model_name=None) -> pydantic_ai model`, `resolve.build_embedder(settings) -> pydantic_ai.Embedder`; contracts exports `resolve_model(model_name=None)`, `resolve_embedder()`, `embedding_dim() -> int`.

- [ ] **Step 1: Write the failing tests** — `modules/ai/tests/test_resolve.py`

```python
"""Per-provider model construction — pure, zero network."""

from __future__ import annotations

import pytest
from pydantic_ai import Embedder
from pydantic_ai.models.anthropic import AnthropicModel
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.models.openai import OpenAIChatModel
from sm_ai import constants, crypto, resolve, services
from sm_ai.contracts import embedding_dim, resolve_model
from sm_ai.contracts.errors import AiNotConfigured
from sm_ai.settings import AiSettings

SECRET = "test-secret-key-for-resolve"


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("SM_SECRET_KEY", SECRET)
    # Keep host env out of these constructions.
    for var in ("SM_AI_CHAT_PROVIDER", "SM_AI_CHAT_MODEL", "SM_AI_CHAT_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    yield
    services.reset()


def _chat(**kw) -> AiSettings:
    base = {
        "chat_provider": constants.PROVIDER_ANTHROPIC,
        "chat_model": "claude-opus-5",
        "chat_api_key": crypto.encrypt_value("sk-test"),
    }
    base.update(kw)
    return AiSettings(**base)


class TestChatProviders:
    def test_anthropic(self):
        model = resolve.build_chat_model(_chat())
        assert isinstance(model, AnthropicModel)
        assert model.model_name == "claude-opus-5"

    def test_openai(self):
        model = resolve.build_chat_model(
            _chat(chat_provider=constants.PROVIDER_OPENAI, chat_model="gpt-5.2")
        )
        assert isinstance(model, OpenAIChatModel)

    def test_google(self):
        model = resolve.build_chat_model(
            _chat(chat_provider=constants.PROVIDER_GOOGLE, chat_model="gemini-3-pro")
        )
        assert isinstance(model, GoogleModel)

    def test_openai_compatible_with_base_url(self):
        model = resolve.build_chat_model(
            _chat(
                chat_provider=constants.PROVIDER_OPENAI_COMPATIBLE,
                chat_model="Qwen/Qwen3.6-35B-A3B-FP8",
                chat_base_url="http://vllm.example:8000/v1",
                chat_api_key="",
            )
        )
        assert isinstance(model, OpenAIChatModel)

    def test_model_name_override(self):
        model = resolve.build_chat_model(_chat(), model_name="claude-haiku-4-5")
        assert model.model_name == "claude-haiku-4-5"


class TestChatErrors:
    def test_unknown_provider(self):
        with pytest.raises(AiNotConfigured) as exc:
            resolve.build_chat_model(_chat(chat_provider="watsonx"))
        assert exc.value.field == "chat_provider"

    def test_empty_model(self):
        with pytest.raises(AiNotConfigured) as exc:
            resolve.build_chat_model(_chat(chat_model=""))
        assert exc.value.field == "chat_model"

    def test_missing_key_for_hosted_provider(self):
        with pytest.raises(AiNotConfigured) as exc:
            resolve.build_chat_model(_chat(chat_api_key=""))
        assert exc.value.field == "chat_api_key"

    def test_openai_compatible_needs_base_url(self):
        with pytest.raises(AiNotConfigured) as exc:
            resolve.build_chat_model(
                _chat(chat_provider=constants.PROVIDER_OPENAI_COMPATIBLE, chat_base_url="")
            )
        assert exc.value.field == "chat_base_url"


def _embed(**kw) -> AiSettings:
    base = {
        "embedding_provider": constants.PROVIDER_OPENAI_COMPATIBLE,
        "embedding_model": "qwen3-embedding-8b",
        "embedding_base_url": "http://vllm.example:8001/v1",
        "embedding_dim": 4096,
    }
    base.update(kw)
    return AiSettings(**base)


class TestEmbeddings:
    def test_openai_compatible(self):
        assert isinstance(resolve.build_embedder(_embed()), Embedder)

    def test_openai(self):
        embedder = resolve.build_embedder(
            _embed(
                embedding_provider=constants.PROVIDER_OPENAI,
                embedding_model="text-embedding-3-small",
                embedding_api_key=crypto.encrypt_value("sk-test"),
                embedding_base_url="",
            )
        )
        assert isinstance(embedder, Embedder)

    def test_unconfigured(self):
        with pytest.raises(AiNotConfigured) as exc:
            resolve.build_embedder(_embed(embedding_provider=""))
        assert exc.value.field == "embedding_provider"

    def test_anthropic_unsupported(self):
        with pytest.raises(AiNotConfigured) as exc:
            resolve.build_embedder(_embed(embedding_provider=constants.PROVIDER_ANTHROPIC))
        assert exc.value.field == "embedding_provider"


class TestContractsFacade:
    def test_resolve_model_reads_holder(self):
        services.install(services.AiServices(settings=_chat()))
        assert isinstance(resolve_model(), AnthropicModel)

    def test_embedding_dim(self):
        services.install(services.AiServices(settings=_embed()))
        assert embedding_dim() == 4096

    def test_embedding_dim_unset_raises(self):
        services.install(services.AiServices(settings=_embed(embedding_dim=0)))
        with pytest.raises(AiNotConfigured):
            embedding_dim()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd modules/ai && uv run pytest tests/test_resolve.py -v`
Expected: FAIL — `No module named 'sm_ai.resolve'`

- [ ] **Step 3: Write `modules/ai/sm_ai/resolve.py`**

```python
"""Build Pydantic AI model / embedder objects from AiSettings.

Pure construction — no network I/O. Provider and auth failures surface in the
consumer's ``agent.run()`` where they belong. Objects are built per call:
construction is cheap, pydantic-ai's shared HTTP client keeps pooling, and a
settings save applies on the very next call.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from sm_ai import constants, crypto
from sm_ai.contracts.errors import AiNotConfigured

if TYPE_CHECKING:
    from pydantic_ai import Embedder
    from pydantic_ai.models import Model

    from sm_ai.settings import AiSettings

logger = logging.getLogger(__name__)


def build_chat_model(settings: AiSettings, model_name: str | None = None) -> Model:
    """A ready chat model for the configured provider.

    ``model_name`` overrides the configured name for same-endpoint
    multi-model setups (e.g. a vision and a text model on one vLLM server).
    """
    provider_id = settings.chat_provider.strip().lower()
    name = (model_name or settings.chat_model).strip()
    if provider_id not in constants.CHAT_PROVIDERS:
        raise AiNotConfigured(
            "chat_provider",
            f"Unknown provider {provider_id!r}; expected one of "
            f"{', '.join(constants.CHAT_PROVIDERS)}.",
        )
    if not name:
        raise AiNotConfigured("chat_model")

    key = crypto.decrypt_value(settings.chat_api_key, "chat_api_key")
    base_url = settings.chat_base_url.strip()

    if provider_id == constants.PROVIDER_OPENAI_COMPATIBLE:
        if not base_url:
            raise AiNotConfigured(
                "chat_base_url",
                "The openai_compatible provider needs the server's /v1 URL.",
            )
        return _openai_chat(name, base_url, key or constants.PLACEHOLDER_API_KEY)

    if not key:
        raise AiNotConfigured("chat_api_key")

    if provider_id == constants.PROVIDER_ANTHROPIC:
        from pydantic_ai.models.anthropic import AnthropicModel
        from pydantic_ai.providers.anthropic import AnthropicProvider

        kwargs = {"base_url": base_url} if base_url else {}
        return AnthropicModel(name, provider=AnthropicProvider(api_key=key, **kwargs))

    if provider_id == constants.PROVIDER_OPENAI:
        return _openai_chat(name, base_url, key)

    # google — the genai client has no plain base_url knob; ignore with a
    # warning rather than fail a working configuration.
    if base_url:
        logger.warning("chat_base_url is ignored for the google provider.")
    from pydantic_ai.models.google import GoogleModel
    from pydantic_ai.providers.google import GoogleProvider

    return GoogleModel(name, provider=GoogleProvider(api_key=key))


def _openai_chat(name: str, base_url: str, key: str) -> Model:
    from pydantic_ai.models.openai import OpenAIChatModel
    from pydantic_ai.providers.openai import OpenAIProvider

    kwargs = {"base_url": base_url} if base_url else {}
    return OpenAIChatModel(name, provider=OpenAIProvider(api_key=key, **kwargs))


def build_embedder(settings: AiSettings) -> Embedder:
    """A ready ``Embedder`` for the configured embedding slot."""
    from pydantic_ai import Embedder

    provider_id = settings.embedding_provider.strip().lower()
    name = settings.embedding_model.strip()
    if not provider_id:
        raise AiNotConfigured(
            "embedding_provider", "The embedding slot is not configured."
        )
    if provider_id not in constants.EMBEDDING_PROVIDERS:
        hint = (
            "Anthropic does not offer an embeddings API."
            if provider_id == constants.PROVIDER_ANTHROPIC
            else f"Expected one of {', '.join(constants.EMBEDDING_PROVIDERS)}."
        )
        raise AiNotConfigured("embedding_provider", hint)
    if not name:
        raise AiNotConfigured("embedding_model")

    key = crypto.decrypt_value(settings.embedding_api_key, "embedding_api_key")
    base_url = settings.embedding_base_url.strip()

    if provider_id == constants.PROVIDER_OPENAI_COMPATIBLE:
        if not base_url:
            raise AiNotConfigured(
                "embedding_base_url",
                "The openai_compatible provider needs the server's /v1 URL.",
            )
        return Embedder(
            _openai_embedding(name, base_url, key or constants.PLACEHOLDER_API_KEY)
        )

    if not key:
        raise AiNotConfigured("embedding_api_key")

    if provider_id == constants.PROVIDER_OPENAI:
        return Embedder(_openai_embedding(name, base_url, key))

    if base_url:
        logger.warning("embedding_base_url is ignored for the google provider.")
    from pydantic_ai.embeddings.google import GoogleEmbeddingModel
    from pydantic_ai.providers.google import GoogleProvider

    return Embedder(GoogleEmbeddingModel(name, provider=GoogleProvider(api_key=key)))


def _openai_embedding(name: str, base_url: str, key: str):
    from pydantic_ai.embeddings.openai import OpenAIEmbeddingModel
    from pydantic_ai.providers.openai import OpenAIProvider

    kwargs = {"base_url": base_url} if base_url else {}
    return OpenAIEmbeddingModel(name, provider=OpenAIProvider(api_key=key, **kwargs))
```

- [ ] **Step 4: Replace `modules/ai/sm_ai/contracts/__init__.py`**

```python
"""Public surface for consuming modules.

    from sm_ai.contracts import resolve_model, resolve_embedder, embedding_dim

    agent = Agent(instructions=..., output_type=MySchema)
    result = await agent.run(text, model=resolve_model())

The base module resolves *connections*; consumers own *behaviour* —
temperature, prompts, retries and streaming belong on the consumer's Agent.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from sm_ai.contracts.errors import AiError, AiKeyUnreadable, AiNotConfigured

if TYPE_CHECKING:
    from pydantic_ai import Embedder
    from pydantic_ai.models import Model


def resolve_model(model_name: str | None = None) -> Model:
    """A ready chat model built from the host's AI settings."""
    from sm_ai import resolve, services

    return resolve.build_chat_model(services.current_settings(), model_name)


def resolve_embedder() -> Embedder:
    """A ready ``Embedder`` built from the host's AI settings."""
    from sm_ai import resolve, services

    return resolve.build_embedder(services.current_settings())


def embedding_dim() -> int:
    """The configured embedding vector width (vector stores need it)."""
    from sm_ai import services
    from sm_ai.contracts.errors import AiNotConfigured as _NotConfigured

    dim = services.current_settings().embedding_dim
    if dim <= 0:
        raise _NotConfigured("embedding_dim", "Set the vector width in AI settings.")
    return dim


__all__ = [
    "AiError",
    "AiKeyUnreadable",
    "AiNotConfigured",
    "embedding_dim",
    "resolve_embedder",
    "resolve_model",
]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd modules/ai && uv run pytest tests/test_resolve.py -v`
Expected: all PASS. If `model.model_name` is not the attribute pydantic-ai v2 exposes, check `model.model_name` vs `model.name` with `uv run python -c "from pydantic_ai.models.anthropic import AnthropicModel; help(AnthropicModel)" | head -40` and adjust the two assertions (not the implementation).

- [ ] **Step 6: Commit**

```bash
git add modules/ai/sm_ai/resolve.py modules/ai/sm_ai/contracts/__init__.py modules/ai/tests/test_resolve.py
git commit -m "feat(ai): per-provider resolve layer and public contracts facade"
```

---

### Task 4: Module class

**Files:**
- Create: `modules/ai/sm_ai/module.py`
- Create: `modules/ai/tests/test_module.py`

**Interfaces:**
- Consumes: `register_module_settings` (settings framework), `services.install`, `AiServices`, `AiSettings`, constants.
- Produces: `AiModule(ModuleBase)` with `meta` (name "Ai", `/api/ai`, `/ai`, depends_on Settings), `register_settings`, `register_permissions`, `register_menu_items`. (`register_routes` is added in Task 5 — the endpoints don't exist yet.)

- [ ] **Step 1: Write the failing tests** — `modules/ai/tests/test_module.py`

```python
"""Module registration: meta, settings holder wiring, permissions, menu."""

from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from settings.module_registry import ModuleSettingsRegistry
from simple_module_core.menu import MenuRegistry
from simple_module_core.permissions import PermissionRegistry
from sm_ai import constants, services
from sm_ai.module import AiModule


class TestMeta:
    def test_meta(self):
        assert AiModule.meta.name == constants.MODULE_NAME
        assert AiModule.meta.route_prefix == constants.ROUTE_PREFIX_API
        assert AiModule.meta.view_prefix == constants.VIEW_PREFIX
        assert constants._MODULE_SETTINGS in AiModule.meta.depends_on

    def test_requires_framework(self):
        assert AiModule.meta.requires_framework is not None


class TestRegisterSettings:
    def test_installs_holder_and_registers_class(self):
        # A minimal stand-in for the settings module's app.state contribution.
        app = FastAPI()
        app.state.settings = SimpleNamespace(module_registry=ModuleSettingsRegistry())
        try:
            AiModule().register_settings(app)
            assert app.state.settings.module_registry.get(constants.PACKAGE) is not None
            state_services = getattr(app.state, constants.PACKAGE)
            # The module-global holder and app.state hold the SAME instance —
            # that identity is what makes hot reload visible to contracts.
            assert services.current_settings() is state_services.settings
        finally:
            services.reset()


class TestPermissions:
    def test_manage_permission_registered(self):
        registry = PermissionRegistry()
        AiModule().register_permissions(registry)
        assert constants.PERM_MANAGE in registry.all_permissions()


class TestMenu:
    def test_menu_entry(self):
        registry = MenuRegistry()
        AiModule().register_menu_items(registry)
        items = [i for i in registry.all_items() if i.url == constants.MENU_URL]
        assert len(items) == 1
        assert items[0].group == constants.MENU_GROUP
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd modules/ai && uv run pytest tests/test_module.py -v`
Expected: FAIL — `No module named 'sm_ai.module'`. If `PermissionRegistry.all_permissions()` / `MenuRegistry.all_items()` don't exist under those names, check the news module's `tests/test_module.py` for the accessor names the repo already uses and mirror them exactly.

- [ ] **Step 3: Write `modules/ai/sm_ai/module.py`**

```python
"""AI base module — connection configuration and the resolve service layer.

Provides no AI features of its own. Other modules depend on it for
``sm_ai.contracts`` (resolve_model / resolve_embedder) and its settings page;
consumers own agents, prompts and behaviour. There are no tables and no
migrations: configuration lives in the shared settings store.
"""

from __future__ import annotations

import importlib.metadata

from fastapi import APIRouter, FastAPI
from simple_module_core.menu import MenuItem, MenuRegistry, MenuSection
from simple_module_core.module import ModuleBase, ModuleMeta
from simple_module_core.permissions import PermissionRegistry

from sm_ai import constants

_VERSION = importlib.metadata.version("simple_module_ai")


class AiModule(ModuleBase):
    meta = ModuleMeta(
        name=constants.MODULE_NAME,
        route_prefix=constants.ROUTE_PREFIX_API,
        view_prefix=constants.VIEW_PREFIX,
        depends_on=[constants._MODULE_SETTINGS],
        version=_VERSION,
        # The framework API version (1.0.0) is decoupled from the framework
        # package version (0.0.x) — this range is correct as written.
        requires_framework=">=1.0,<2.0",
    )

    def register_settings(self, app: FastAPI) -> None:
        from settings.registration import register_module_settings

        from sm_ai import services
        from sm_ai.settings import AiSettings

        # The factory installs the instance in the module-global holder AND
        # returns it for app.state.sm_ai — one shared object, so hydration and
        # hot reload (which assign .settings on it) are visible to contracts.
        register_module_settings(
            app,
            constants.PACKAGE,
            AiSettings,
            lambda s: services.install(services.AiServices(settings=s)),
        )

    def register_permissions(self, registry: PermissionRegistry) -> None:
        registry.add_group(constants.MODULE_NAME, [constants.PERM_MANAGE])

    def register_menu_items(self, registry: MenuRegistry) -> None:
        registry.add(
            MenuItem(
                label="AI",
                url=constants.MENU_URL,
                icon=constants.MENU_ICON,
                order=constants.MENU_ORDER,
                section=MenuSection.SIDEBAR,
                group=constants.MENU_GROUP,
                roles=["admin"],
            )
        )

    def register_routes(self, api_router: APIRouter, view_router: APIRouter) -> None:
        from sm_ai.endpoints.api import router as api
        from sm_ai.endpoints.views import router as views

        api_router.include_router(api)
        view_router.include_router(views)
```

Note: `register_routes` imports endpoints that don't exist until Task 5. For this task's tests that's fine (nothing calls it); if any collected import pulls it in, create empty `sm_ai/endpoints/__init__.py` with two empty `APIRouter()` stubs in `api.py` / `views.py` and let Task 5 fill them.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd modules/ai && uv run pytest tests/test_module.py -v`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add modules/ai/sm_ai/module.py modules/ai/tests/test_module.py
git commit -m "feat(ai): AiModule with settings registration, permission and menu"
```

---

### Task 5: Schemas, service, endpoints

**Files:**
- Create: `modules/ai/sm_ai/contracts/schemas.py`
- Create: `modules/ai/sm_ai/deps.py`
- Create: `modules/ai/sm_ai/service.py`
- Create: `modules/ai/sm_ai/endpoints/__init__.py` (empty)
- Create: `modules/ai/sm_ai/endpoints/api.py`
- Create: `modules/ai/sm_ai/endpoints/views.py`
- Create: `modules/ai/tests/test_api.py`

**Interfaces:**
- Consumes: everything from Tasks 1–4; framework `RequiresPermission`, `InertiaDep`, `get_db`; settings framework `apply_changes_and_reload`, `SettingsStore`, `SettingService`.
- Produces: `AiSettingsOut`, `AiSettingsUpdate`, `AiTestRequest`, `AiTestResult` schemas; `AiService(app, db)` with `current()`, `apply(changes)`, static `build_changes(data)`; routes `GET/PUT /api/ai/settings`, `POST /api/ai/test`, view `GET /ai/`.

- [ ] **Step 1: Write `modules/ai/sm_ai/contracts/schemas.py`**

```python
"""DTOs for the AI settings API. Secrets never travel outward — reads carry
``has_*_api_key`` booleans; writes treat blank as "keep" and ``clear_*`` as
explicit removal."""

from __future__ import annotations

from pydantic import field_validator
from sqlmodel import SQLModel

from sm_ai import constants


class AiSettingsOut(SQLModel):
    """Current AI settings with secrets reduced to presence flags."""

    chat_provider: str
    chat_model: str
    chat_base_url: str
    has_chat_api_key: bool
    embedding_provider: str
    embedding_model: str
    embedding_base_url: str
    has_embedding_api_key: bool
    embedding_dim: int


class AiSettingsUpdate(SQLModel):
    """Partial update. Key fields: blank/omitted = keep the stored key."""

    chat_provider: str | None = None
    chat_model: str | None = None
    chat_base_url: str | None = None
    chat_api_key: str | None = None
    clear_chat_api_key: bool = False
    embedding_provider: str | None = None
    embedding_model: str | None = None
    embedding_base_url: str | None = None
    embedding_api_key: str | None = None
    clear_embedding_api_key: bool = False
    embedding_dim: int | None = None

    @field_validator("chat_provider")
    @classmethod
    def _chat_provider_known(cls, value: str | None) -> str | None:
        if value is not None and value not in constants.CHAT_PROVIDERS:
            raise ValueError(f"chat_provider must be one of {constants.CHAT_PROVIDERS}")
        return value

    @field_validator("embedding_provider")
    @classmethod
    def _embedding_provider_known(cls, value: str | None) -> str | None:
        if value is not None and value != "" and value not in constants.EMBEDDING_PROVIDERS:
            raise ValueError(
                f"embedding_provider must be empty or one of {constants.EMBEDDING_PROVIDERS}"
            )
        return value

    @field_validator("embedding_dim")
    @classmethod
    def _dim_non_negative(cls, value: int | None) -> int | None:
        if value is not None and value < 0:
            raise ValueError("embedding_dim must be >= 0")
        return value


class AiTestRequest(SQLModel):
    """Which slot to test."""

    slot: str

    @field_validator("slot")
    @classmethod
    def _slot_known(cls, value: str) -> str:
        if value not in constants.TEST_SLOTS:
            raise ValueError(f"slot must be one of {constants.TEST_SLOTS}")
        return value


class AiTestResult(SQLModel):
    """Outcome of one test call. Failure is a result, never a 500."""

    ok: bool
    model: str = ""
    latency_ms: int = 0
    error: str = ""
```

- [ ] **Step 2: Write `modules/ai/sm_ai/service.py`**

```python
"""AI settings service — reads current settings and applies admin changes.

No AI table: values live in the shared settings store. Writes go through
``settings.reload.apply_changes_and_reload`` which validates against
``AiSettings``, persists (SYSTEM scope), hot-swaps ``app.state.sm_ai`` (the
same instance the module-global holder references) and publishes
``SettingsReloaded``. Key material is encrypted before it ever reaches the
store — see ``build_changes``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sm_ai import constants, crypto, services
from sm_ai.contracts.schemas import AiSettingsOut, AiSettingsUpdate

if TYPE_CHECKING:
    from fastapi import FastAPI
    from sqlalchemy.ext.asyncio import AsyncSession

_CLEAR_FLAGS = {
    "clear_chat_api_key": "chat_api_key",
    "clear_embedding_api_key": "embedding_api_key",
}


class AiService:
    """Read/update the host's AI connection settings."""

    def __init__(self, app: FastAPI, db: AsyncSession) -> None:
        self.app = app
        self.db = db

    def current(self) -> AiSettingsOut:
        s = services.current_settings()
        return AiSettingsOut(
            chat_provider=s.chat_provider,
            chat_model=s.chat_model,
            chat_base_url=s.chat_base_url,
            has_chat_api_key=bool(s.chat_api_key),
            embedding_provider=s.embedding_provider,
            embedding_model=s.embedding_model,
            embedding_base_url=s.embedding_base_url,
            has_embedding_api_key=bool(s.embedding_api_key),
            embedding_dim=s.embedding_dim,
        )

    @staticmethod
    def build_changes(data: AiSettingsUpdate) -> dict[str, Any]:
        """Translate an update payload into settings-store changes.

        Secret fields: omitted or blank = keep the stored key; a value is
        encrypted; ``clear_*`` wins and empties the field.
        """
        payload = data.model_dump(exclude_unset=True)
        changes: dict[str, Any] = {}
        for field, value in payload.items():
            if field in _CLEAR_FLAGS:
                continue  # handled below
            if value is None:
                continue
            if field in constants.SECRET_FIELDS:
                if value == "":
                    continue
                changes[field] = crypto.encrypt_value(value)
            elif isinstance(value, str):
                changes[field] = value.strip()
            else:
                changes[field] = value
        for flag, target in _CLEAR_FLAGS.items():
            if payload.get(flag):
                changes[target] = ""
        return changes

    async def apply(self, changes: dict[str, Any]) -> AiSettingsOut:
        """Persist and hot-swap the given field changes, then return current."""
        # Plugin→plugin imports (settings is a declared dependency); kept local
        # so import order during discovery stays tolerant.
        from settings.reload import apply_changes_and_reload
        from settings.service import SettingService
        from settings.store import SettingsStore

        store = SettingsStore(SettingService(self.db))
        bus = self.app.state.sm.event_bus
        await apply_changes_and_reload(
            self.app, bus, store, package=constants.PACKAGE, changes=changes
        )
        return self.current()
```

- [ ] **Step 3: Write `modules/ai/sm_ai/deps.py`**

```python
"""FastAPI dependencies for the AI module."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request
from simple_module_db.deps import get_db
from sqlalchemy.ext.asyncio import AsyncSession

from sm_ai.service import AiService


async def get_ai_service(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> AiService:
    return AiService(request.app, db)


AiServiceDep = Annotated[AiService, Depends(get_ai_service)]
```

- [ ] **Step 4: Write `modules/ai/sm_ai/endpoints/api.py`**

```python
"""REST API for AI settings. Everything requires ai.manage."""

from __future__ import annotations

import asyncio
import time

from fastapi import APIRouter, Depends
from simple_module_hosting.permissions import RequiresPermission

from sm_ai import constants, services
from sm_ai.contracts.schemas import (
    AiSettingsOut,
    AiSettingsUpdate,
    AiTestRequest,
    AiTestResult,
)
from sm_ai.deps import AiServiceDep
from sm_ai.service import AiService

router = APIRouter()

_MANAGE = Depends(RequiresPermission(constants.PERM_MANAGE))


@router.get("/settings", response_model=AiSettingsOut, dependencies=[_MANAGE])
async def get_settings(service: AiServiceDep) -> AiSettingsOut:
    return service.current()


@router.put("/settings", response_model=AiSettingsOut, dependencies=[_MANAGE])
async def update_settings(data: AiSettingsUpdate, service: AiServiceDep) -> AiSettingsOut:
    changes = AiService.build_changes(data)
    if not changes:
        return service.current()
    return await service.apply(changes)


@router.post("/test", response_model=AiTestResult, dependencies=[_MANAGE])
async def test_connection(data: AiTestRequest) -> AiTestResult:
    """One tiny real call through the configured slot.

    The only place this module itself calls a provider. Every failure —
    missing config, unreadable key, bad URL, auth error, timeout — comes back
    as ``ok: false`` with the message; a wrong URL is a result, not a 500.
    """
    from pydantic_ai import Agent

    from sm_ai import contracts

    started = time.monotonic()
    label = ""
    try:
        async with asyncio.timeout(constants.TEST_TIMEOUT_SECONDS):
            if data.slot == constants.SLOT_CHAT:
                label = services.current_settings().chat_model
                agent = Agent(contracts.resolve_model())
                await agent.run(constants.TEST_PROMPT)
            else:
                label = services.current_settings().embedding_model
                await contracts.resolve_embedder().embed_query(constants.TEST_PROMPT)
    except TimeoutError:
        return AiTestResult(
            ok=False,
            model=label,
            error=f"Timed out after {constants.TEST_TIMEOUT_SECONDS}s.",
        )
    except Exception as exc:  # noqa: BLE001 — a failed probe is a result, not a bug
        return AiTestResult(ok=False, model=label, error=str(exc) or type(exc).__name__)
    return AiTestResult(
        ok=True, model=label, latency_ms=int((time.monotonic() - started) * 1000)
    )
```

- [ ] **Step 5: Write `modules/ai/sm_ai/endpoints/views.py`**

```python
"""Inertia view endpoints for the AI module."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from inertia import InertiaResponse
from simple_module_hosting.inertia_deps import InertiaDep
from simple_module_hosting.permissions import RequiresPermission

from sm_ai import constants

router = APIRouter()


@router.get(
    "/",
    response_model=None,
    dependencies=[Depends(RequiresPermission(constants.PERM_MANAGE))],
)
async def settings_page(inertia: InertiaDep) -> InertiaResponse:
    # Settings are fetched client-side from /api/ai/settings so a save can
    # refresh without a full Inertia round trip. The page name is inlined as a
    # literal (SM003/SM004 static-AST pairing); a unit test asserts it matches
    # constants._PAGE_SETTINGS.
    return await inertia.render("Ai/Settings")
```

- [ ] **Step 6: Write the failing endpoint tests** — `modules/ai/tests/test_api.py`

```python
"""Endpoint behaviour: masking, keep-vs-replace-vs-clear, the test probe.

The app here is assembled by hand (news-conftest style): stub auth middleware
grants ai.manage, the module-global holder carries the settings, and
AiService.apply is monkeypatched to capture changes — persistence itself is
framework code with its own tests upstream.
"""

from __future__ import annotations

import inspect
from types import SimpleNamespace

import pytest
import pytest_asyncio
from fastapi import APIRouter, FastAPI
from httpx import ASGITransport, AsyncClient
from pydantic_ai.models.test import TestModel
from sm_ai import constants, crypto, services
from sm_ai.contracts.schemas import AiSettingsUpdate
from sm_ai.service import AiService
from sm_ai.settings import AiSettings
from starlette.middleware.base import BaseHTTPMiddleware

SECRET = "test-secret-key-for-api"


class _GrantAll(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        request.state.user = SimpleNamespace(
            id="test-user", email="t@example.com", name="T", roles=["admin"]
        )
        request.state.permissions = {constants.PERM_MANAGE}
        return await call_next(request)


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("SM_SECRET_KEY", SECRET)
    yield
    services.reset()


@pytest_asyncio.fixture
async def client(monkeypatch):
    from sm_ai.endpoints.api import router as api_router

    services.install(
        services.AiServices(
            settings=AiSettings(chat_api_key=crypto.encrypt_value("sk-stored"))
        )
    )
    applied: list[dict] = []

    async def _fake_apply(self, changes):
        applied.append(changes)
        return self.current()

    monkeypatch.setattr(AiService, "apply", _fake_apply)

    app = FastAPI()
    app.add_middleware(_GrantAll)
    prefixed = APIRouter(prefix=constants.ROUTE_PREFIX_API)
    prefixed.include_router(api_router)
    app.include_router(prefixed)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as http:
        http.applied = applied
        yield http


class TestGetSettings:
    async def test_masks_secrets(self, client):
        res = await client.get("/api/ai/settings")
        assert res.status_code == 200
        body = res.json()
        assert body["has_chat_api_key"] is True
        assert "chat_api_key" not in body

    async def test_defaults_visible(self, client):
        body = (await client.get("/api/ai/settings")).json()
        assert body["chat_provider"] == constants.PROVIDER_ANTHROPIC
        assert body["embedding_provider"] == ""


class TestBuildChanges:
    def test_blank_key_keeps_stored(self):
        changes = AiService.build_changes(
            AiSettingsUpdate(chat_model="claude-opus-5", chat_api_key="")
        )
        assert changes == {"chat_model": "claude-opus-5"}

    def test_new_key_is_encrypted(self, monkeypatch):
        monkeypatch.setenv("SM_SECRET_KEY", SECRET)
        changes = AiService.build_changes(AiSettingsUpdate(chat_api_key="sk-new"))
        assert changes["chat_api_key"].startswith(crypto.ENC_PREFIX)
        assert crypto.decrypt_value(changes["chat_api_key"], "chat_api_key") == "sk-new"

    def test_clear_wins(self):
        changes = AiService.build_changes(
            AiSettingsUpdate(chat_api_key="sk-new", clear_chat_api_key=True)
        )
        assert changes["chat_api_key"] == ""

    def test_empty_update_no_changes(self):
        assert AiService.build_changes(AiSettingsUpdate()) == {}


class TestPutSettings:
    async def test_put_applies_changes(self, client):
        res = await client.put(
            "/api/ai/settings", json={"chat_model": "claude-sonnet-5"}
        )
        assert res.status_code == 200
        assert client.applied == [{"chat_model": "claude-sonnet-5"}]

    async def test_unknown_provider_rejected(self, client):
        res = await client.put("/api/ai/settings", json={"chat_provider": "watsonx"})
        assert res.status_code == 422

    async def test_noop_put_does_not_apply(self, client):
        res = await client.put("/api/ai/settings", json={})
        assert res.status_code == 200
        assert client.applied == []


class TestTestEndpoint:
    async def test_unconfigured_slot_reports_error(self, client):
        res = await client.post("/api/ai/test", json={"slot": constants.SLOT_EMBEDDING})
        assert res.status_code == 200
        body = res.json()
        assert body["ok"] is False
        assert "embedding_provider" in body["error"]

    async def test_chat_ok_with_test_model(self, client, monkeypatch):
        from sm_ai import contracts

        monkeypatch.setattr(contracts, "resolve_model", lambda model_name=None: TestModel())
        res = await client.post("/api/ai/test", json={"slot": constants.SLOT_CHAT})
        body = res.json()
        assert body["ok"] is True
        assert body["model"] == "claude-opus-5"

    async def test_unknown_slot_rejected(self, client):
        res = await client.post("/api/ai/test", json={"slot": "video"})
        assert res.status_code == 422


class TestViewLiteral:
    def test_render_literal_matches_constant(self):
        # The view inlines the page name for the framework's static-AST
        # diagnostics; this pins it to the constant.
        from sm_ai.endpoints import views

        source = inspect.getsource(views)
        assert f'"{constants._PAGE_SETTINGS}"' in source
```

- [ ] **Step 7: Run tests to verify current state**

Run: `cd modules/ai && uv run pytest tests/test_api.py -v`
Expected: PASS if Steps 1–5 were written first (this task writes impl before test only because the schemas/service/endpoints are one coherent unit; the tests were designed from the spec, not from the code). If `RequiresPermission` reads a different request attribute than `request.state.permissions`, read `simple_module_hosting/permissions.py` and adapt the `_GrantAll` middleware (only the middleware — not the endpoints).

- [ ] **Step 8: Run the whole module suite**

Run: `cd modules/ai && uv run pytest -v`
Expected: all PASS

- [ ] **Step 9: Commit**

```bash
git add modules/ai/sm_ai modules/ai/tests/test_api.py
git commit -m "feat(ai): settings API, test-connection probe, and Inertia view"
```

---

### Task 6: Frontend settings page

**Files:**
- Create: `modules/ai/sm_ai/utils/api.ts`
- Create: `modules/ai/sm_ai/components/SlotCard.tsx`
- Create: `modules/ai/sm_ai/pages/Settings.tsx`

**Interfaces:**
- Consumes: `GET/PUT /api/ai/settings` (`AiSettingsOut` / `AiSettingsUpdate` shapes), `POST /api/ai/test`.
- Produces: Inertia page registered as `Ai/Settings`.

- [ ] **Step 1: Write `modules/ai/sm_ai/utils/api.ts`**

```typescript
export type AiSettingsOut = {
  chat_provider: string;
  chat_model: string;
  chat_base_url: string;
  has_chat_api_key: boolean;
  embedding_provider: string;
  embedding_model: string;
  embedding_base_url: string;
  has_embedding_api_key: boolean;
  embedding_dim: number;
};

export type TestResult = {
  ok: boolean;
  model: string;
  latency_ms: number;
  error: string;
};

export type SlotValues = {
  provider: string;
  model: string;
  base_url: string;
  api_key: string; // "" = keep stored key
  clear_key: boolean;
  dim?: number;
};

async function readError(res: Response): Promise<string> {
  try {
    const body = await res.json();
    if (typeof body?.detail === 'string') return body.detail;
    return JSON.stringify(body?.detail ?? res.statusText);
  } catch {
    return res.statusText;
  }
}

async function checkedJson<T>(res: Response): Promise<T> {
  if (!res.ok) throw new Error(await readError(res));
  return (await res.json()) as T;
}

export async function loadSettings(): Promise<AiSettingsOut> {
  return checkedJson(await fetch('/api/ai/settings', { credentials: 'same-origin' }));
}

export async function saveSettings(chat: SlotValues, embedding: SlotValues): Promise<AiSettingsOut> {
  const payload: Record<string, unknown> = {
    chat_provider: chat.provider,
    chat_model: chat.model,
    chat_base_url: chat.base_url,
    embedding_provider: embedding.provider,
    embedding_model: embedding.model,
    embedding_base_url: embedding.base_url,
    embedding_dim: embedding.dim ?? 0,
  };
  if (chat.api_key) payload.chat_api_key = chat.api_key;
  if (chat.clear_key) payload.clear_chat_api_key = true;
  if (embedding.api_key) payload.embedding_api_key = embedding.api_key;
  if (embedding.clear_key) payload.clear_embedding_api_key = true;
  return checkedJson(
    await fetch('/api/ai/settings', {
      method: 'PUT',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),
  );
}

export async function testSlot(slot: 'chat' | 'embedding'): Promise<TestResult> {
  return checkedJson(
    await fetch('/api/ai/test', {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ slot }),
    }),
  );
}
```

Note: if other pages in this repo send a CSRF header with mutating fetches (check `tests/e2e/csrf.spec.ts` and how `news/utils/api.ts` posts), copy that exact pattern into `saveSettings`/`testSlot`.

- [ ] **Step 2: Write `modules/ai/sm_ai/components/SlotCard.tsx`**

```tsx
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@simple-module-py/ui/components/ui/card';
import { Button } from '@simple-module-py/ui/components/ui/button';
import { Input } from '@simple-module-py/ui/components/ui/input';
import { Label } from '@simple-module-py/ui/components/ui/label';
import type { SlotValues, TestResult } from '../utils/api';

const OPENAI_COMPATIBLE = 'openai_compatible';

export function SlotCard({
  title,
  description,
  idPrefix,
  providers,
  allowEmptyProvider,
  values,
  hasStoredKey,
  showDim,
  busy,
  testResult,
  onChange,
  onTest,
}: {
  title: string;
  description: string;
  idPrefix: string;
  providers: string[];
  allowEmptyProvider: boolean;
  values: SlotValues;
  hasStoredKey: boolean;
  showDim: boolean;
  busy: boolean;
  testResult: TestResult | null;
  onChange: (next: SlotValues) => void;
  onTest: () => void;
}) {
  const set = (patch: Partial<SlotValues>) => onChange({ ...values, ...patch });
  const needsUrl = values.provider === OPENAI_COMPATIBLE;

  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        <CardDescription>{description}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="space-y-2">
          <Label htmlFor={`${idPrefix}-provider`}>Provider</Label>
          <select
            id={`${idPrefix}-provider`}
            className="border-input bg-background flex h-9 w-full rounded-md border px-3 py-1 text-sm"
            value={values.provider}
            onChange={(e) => set({ provider: e.target.value })}
            disabled={busy}
          >
            {allowEmptyProvider && <option value="">Not configured</option>}
            {providers.map((p) => (
              <option key={p} value={p}>
                {p}
              </option>
            ))}
          </select>
        </div>
        <div className="space-y-2">
          <Label htmlFor={`${idPrefix}-model`}>Model</Label>
          <Input
            id={`${idPrefix}-model`}
            value={values.model}
            onChange={(e) => set({ model: e.target.value })}
            placeholder="model name, no provider prefix"
            disabled={busy}
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor={`${idPrefix}-url`}>
            Base URL{needsUrl ? ' (required)' : ' (optional override)'}
          </Label>
          <Input
            id={`${idPrefix}-url`}
            value={values.base_url}
            onChange={(e) => set({ base_url: e.target.value })}
            placeholder={needsUrl ? 'http://your-server:8000/v1' : 'provider default'}
            disabled={busy}
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor={`${idPrefix}-key`}>API key</Label>
          <div className="flex gap-2">
            <Input
              id={`${idPrefix}-key`}
              type="password"
              value={values.api_key}
              onChange={(e) => set({ api_key: e.target.value, clear_key: false })}
              placeholder={hasStoredKey ? 'saved — leave blank to keep' : 'not set'}
              disabled={busy || values.clear_key}
            />
            {hasStoredKey && (
              <Button
                type="button"
                variant={values.clear_key ? 'destructive' : 'ghost'}
                size="sm"
                disabled={busy}
                onClick={() => set({ clear_key: !values.clear_key, api_key: '' })}
              >
                {values.clear_key ? 'Will clear' : 'Clear'}
              </Button>
            )}
          </div>
        </div>
        {showDim && (
          <div className="space-y-2">
            <Label htmlFor={`${idPrefix}-dim`}>Vector dimension</Label>
            <Input
              id={`${idPrefix}-dim`}
              type="number"
              value={values.dim ?? 0}
              onChange={(e) => set({ dim: Number(e.target.value) || 0 })}
              disabled={busy}
            />
            <p className="text-xs text-muted-foreground">
              Vector stores fix collection width to this — changing it means re-indexing.
            </p>
          </div>
        )}
        <div className="flex items-center gap-3">
          <Button type="button" variant="outline" size="sm" disabled={busy} onClick={onTest}>
            Test connection
          </Button>
          {testResult && (
            <span
              data-testid={`${idPrefix}-test-result`}
              className={testResult.ok ? 'text-sm text-emerald-600' : 'text-sm text-destructive'}
            >
              {testResult.ok
                ? `OK — ${testResult.model} (${testResult.latency_ms} ms)`
                : testResult.error}
            </span>
          )}
        </div>
      </CardContent>
    </Card>
  );
}
```

- [ ] **Step 3: Write `modules/ai/sm_ai/pages/Settings.tsx`**

```tsx
import { Head } from '@inertiajs/react';
import { PageShell } from '@simple-module-py/ui/components/PageShell';
import { Button } from '@simple-module-py/ui/components/ui/button';
import { AuthenticatedLayout } from '@simple-module-py/ui/layouts/AuthenticatedLayout';
import { useEffect, useState } from 'react';
import { toast } from 'sonner';

import { SlotCard } from '../components/SlotCard';
import {
  type AiSettingsOut,
  type SlotValues,
  type TestResult,
  loadSettings,
  saveSettings,
  testSlot,
} from '../utils/api';

const CHAT_PROVIDERS = ['anthropic', 'openai', 'google', 'openai_compatible'];
const EMBEDDING_PROVIDERS = ['openai', 'google', 'openai_compatible'];

const emptySlot = (): SlotValues => ({
  provider: '',
  model: '',
  base_url: '',
  api_key: '',
  clear_key: false,
});

function fromSettings(s: AiSettingsOut): { chat: SlotValues; embedding: SlotValues } {
  return {
    chat: {
      provider: s.chat_provider,
      model: s.chat_model,
      base_url: s.chat_base_url,
      api_key: '',
      clear_key: false,
    },
    embedding: {
      provider: s.embedding_provider,
      model: s.embedding_model,
      base_url: s.embedding_base_url,
      api_key: '',
      clear_key: false,
      dim: s.embedding_dim,
    },
  };
}

export default function Settings() {
  const [loaded, setLoaded] = useState<AiSettingsOut | null>(null);
  const [chat, setChat] = useState<SlotValues>(emptySlot());
  const [embedding, setEmbedding] = useState<SlotValues>(emptySlot());
  const [busy, setBusy] = useState(false);
  const [chatTest, setChatTest] = useState<TestResult | null>(null);
  const [embeddingTest, setEmbeddingTest] = useState<TestResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    loadSettings()
      .then((s) => {
        setLoaded(s);
        const slots = fromSettings(s);
        setChat(slots.chat);
        setEmbedding(slots.embedding);
      })
      .catch((err) => setError((err as Error).message));
  }, []);

  async function run(work: () => Promise<void>, errorMsg: string) {
    setBusy(true);
    try {
      await work();
    } catch (err) {
      toast.error(`${errorMsg}: ${(err as Error).message}`);
    } finally {
      setBusy(false);
    }
  }

  const save = () =>
    run(async () => {
      const next = await saveSettings(chat, embedding);
      setLoaded(next);
      const slots = fromSettings(next);
      setChat(slots.chat);
      setEmbedding(slots.embedding);
      toast.success('AI settings saved');
    }, 'Save failed');

  const test = (slot: 'chat' | 'embedding') =>
    run(async () => {
      const result = await testSlot(slot);
      (slot === 'chat' ? setChatTest : setEmbeddingTest)(result);
    }, 'Test failed');

  return (
    <AuthenticatedLayout>
      <Head title="AI Settings" />
      <PageShell
        title="AI"
        description="Connection settings for the chat and embedding providers every module shares."
      >
        {error && <p className="text-sm text-destructive">{error}</p>}
        {!loaded && !error && <p className="text-sm text-muted-foreground">Loading…</p>}
        {loaded && (
          <div className="space-y-6">
            <SlotCard
              title="Chat"
              description="The model modules use for text generation."
              idPrefix="ai-chat"
              providers={CHAT_PROVIDERS}
              allowEmptyProvider={false}
              values={chat}
              hasStoredKey={loaded.has_chat_api_key}
              showDim={false}
              busy={busy}
              testResult={chatTest}
              onChange={setChat}
              onTest={() => test('chat')}
            />
            <SlotCard
              title="Embeddings"
              description="Optional second endpoint for vector embeddings."
              idPrefix="ai-embedding"
              providers={EMBEDDING_PROVIDERS}
              allowEmptyProvider={true}
              values={embedding}
              hasStoredKey={loaded.has_embedding_api_key}
              showDim={true}
              busy={busy}
              testResult={embeddingTest}
              onChange={setEmbedding}
              onTest={() => test('embedding')}
            />
            <Button type="button" disabled={busy} onClick={save}>
              Save
            </Button>
          </div>
        )}
      </PageShell>
    </AuthenticatedLayout>
  );
}
```

- [ ] **Step 4: Install workspace deps and lint**

Run: `npm install` (repo root — picks up the new workspace member), then `npx biome check modules/ai`
Expected: clean (fix any import-order complaints with `npx biome check --write modules/ai`).

- [ ] **Step 5: Line-count check**

Run: `uv run python scripts/check_file_size.py`
Expected: clean — `Settings.tsx` and `SlotCard.tsx` both under 300 lines.

- [ ] **Step 6: Commit**

```bash
git add modules/ai/sm_ai/pages modules/ai/sm_ai/components modules/ai/sm_ai/utils package-lock.json
git commit -m "feat(ai): admin settings page with per-slot test connection"
```

---

### Task 7: Repo wiring, README, host smoke, full gates

**Files:**
- Modify: `pyproject.toml` (root — `testpaths`)
- Modify: `.github/workflows/ci.yml` (pytest step)
- Modify: `.github/workflows/release.yml` (publish matrix)
- Modify: `modules/ai/README.md` (full content)
- Modify: `host/tests/test_host_boots.py` (add the AI module to whatever it asserts per module)

- [ ] **Step 1: Add `"modules/ai/tests",` to `testpaths`** in root `pyproject.toml` (alphabetical — before `modules/news/tests`).

- [ ] **Step 2: Add the CI step** in `.github/workflows/ci.yml` next to the news/pagebuilder steps:

```yaml
      - name: Run pytest (ai)
        run: cd modules/ai && uv run pytest
```

- [ ] **Step 3: Add `- simple_module_ai`** to the `publish-pypi` matrix `package:` list in `.github/workflows/release.yml`.

- [ ] **Step 4: Write the full `modules/ai/README.md`** (≥500 bytes, H1, the words "Install" and "Usage"):

```markdown
# simple_module_ai

AI base module for [SimpleModule](https://docs.py.simplemodule.dev) apps: one
provider-configurable service layer (chat + embeddings) that every other
module shares, with DB-backed settings, encrypted keys and an admin page.

The module owns **connection** configuration — provider, endpoint, key, model
name. Consuming modules own **behaviour** — agents, prompts, temperature,
retries, streaming.

## Install

```bash
pip install simple_module_ai
```

Add `simple_module_ai` to your host's dependencies; it is discovered at boot
via the `simple_module` entry point. There are no tables and no migrations.

## Usage (consuming from another module)

Declare the dependency in your module's `ModuleMeta`:

```python
meta = ModuleMeta(name="MyModule", depends_on=["Ai"], ...)
```

Then resolve connections wherever you need them:

```python
from pydantic_ai import Agent
from sm_ai.contracts import AiNotConfigured, resolve_model, resolve_embedder

agent = Agent(instructions="...", output_type=MySchema)
result = await agent.run(text, model=resolve_model())

embedder = resolve_embedder()          # raises AiNotConfigured until the
vectors = await embedder.embed_documents(chunks)  # embedding slot is set up
```

`resolve_model(model_name=...)` overrides the configured model name for
same-endpoint multi-model setups. `embedding_dim()` returns the configured
vector width. All errors subclass `AiError`.

## Settings

Two slots — chat and embeddings — each with provider (`anthropic`, `openai`,
`google`, `openai_compatible`), model, base URL and API key. The
`openai_compatible` provider covers vLLM, Ollama and LM Studio (base URL
required; a blank key is replaced by a protocol-satisfying placeholder).

Configure at `/ai/` (permission `ai.manage`) or seed via `SM_AI_*` env vars
(e.g. `SM_AI_CHAT_MODEL`); DB values win over env. API keys are encrypted at
rest with a key derived from `SM_SECRET_KEY` — rotating that secret means
re-entering provider keys. A settings save hot-reloads the worker that
handled it; other workers pick the change up on restart.

## Routes

| Route | Purpose |
|---|---|
| `GET /ai/` | admin settings page |
| `GET`/`PUT /api/ai/settings` | read (secrets masked) / update |
| `POST /api/ai/test` | probe the chat or embedding slot |
```

- [ ] **Step 5: Extend the host smoke test.** Read `host/tests/test_host_boots.py` first; add the AI module to each per-module assertion it makes (routes registered under `/api/ai`, menu entry "AI" present — matching however it asserts news/pagebuilder).

- [ ] **Step 6: Run every gate**

Run from repo root:

```bash
make lint
make test-py
uv run python scripts/bump_version.py --check-current
```

Expected: all clean. `check_metadata` validates the module's pyproject, `check_readmes` the README, `check_hardcoded_strings` the constants discipline, `check_file_size` the 300-line cap.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml .github/workflows/ci.yml .github/workflows/release.yml modules/ai/README.md host/tests
git commit -m "chore(ai): wire module into testpaths, CI, release matrix; full README"
```

---

### Task 8: Playwright e2e

**Files:**
- Create: `tests/e2e/ai-settings.spec.ts`

**Interfaces:**
- Consumes: the running host (`make dev` stack the e2e config boots), `tests/e2e/helpers.ts` login helper, the `data-testid` attributes from Task 6.

- [ ] **Step 1: Read `tests/e2e/branding.spec.ts` and `tests/e2e/helpers.ts`** — copy their login + navigation idioms exactly (auth setup, base URL, any `test.beforeEach`).

- [ ] **Step 2: Write `tests/e2e/ai-settings.spec.ts`** (adapt the login call to what helpers.ts actually exports):

```typescript
import { expect, test } from '@playwright/test';
import { loginAsAdmin } from './helpers';

test.describe('AI settings', () => {
  test.beforeEach(async ({ page }) => {
    await loginAsAdmin(page);
    await page.goto('/ai/');
  });

  test('page loads with both slot cards', async ({ page }) => {
    await expect(page.getByText('Chat', { exact: true })).toBeVisible();
    await expect(page.getByText('Embeddings', { exact: true })).toBeVisible();
  });

  test('saving the chat model persists across reload', async ({ page }) => {
    await page.locator('#ai-chat-model').fill('claude-sonnet-5');
    await page.getByRole('button', { name: 'Save' }).click();
    await expect(page.getByText('AI settings saved')).toBeVisible();
    await page.reload();
    await expect(page.locator('#ai-chat-model')).toHaveValue('claude-sonnet-5');
  });

  test('saved key is masked, never echoed', async ({ page }) => {
    await page.locator('#ai-chat-key').fill('sk-e2e-secret');
    await page.getByRole('button', { name: 'Save' }).click();
    await expect(page.getByText('AI settings saved')).toBeVisible();
    await page.reload();
    await expect(page.locator('#ai-chat-key')).toHaveValue('');
    await expect(page.locator('#ai-chat-key')).toHaveAttribute(
      'placeholder',
      /leave blank to keep/,
    );
  });

  test('test connection surfaces an unreachable endpoint as an inline error', async ({
    page,
  }) => {
    // 127.0.0.1:1 refuses connections instantly — deterministic, no stubs.
    await page.locator('#ai-chat-provider').selectOption('openai_compatible');
    await page.locator('#ai-chat-model').fill('some-model');
    await page.locator('#ai-chat-url').fill('http://127.0.0.1:1/v1');
    await page.getByRole('button', { name: 'Save' }).click();
    await expect(page.getByText('AI settings saved')).toBeVisible();
    await page.getByRole('button', { name: 'Test connection' }).first().click();
    await expect(page.getByTestId('ai-chat-test-result')).toBeVisible({ timeout: 45_000 });
    await expect(page.getByTestId('ai-chat-test-result')).not.toContainText('OK —');
  });
});
```

- [ ] **Step 3: Run the suite**

Run: `make e2e` (repo root; if chromium is missing first run `npx playwright install chromium --with-deps`)
Expected: the new spec passes along with the existing ones (the run resets `host/test.db`, so saved settings don't leak between runs).

- [ ] **Step 4: Commit**

```bash
git add tests/e2e/ai-settings.spec.ts
git commit -m "test(ai): e2e coverage for the AI settings page"
```

---

## Self-Review Notes

- **Spec coverage:** packaging (T1), settings + env seeding (T2), crypto states (T1), resolve + contracts + placeholder key + overrides (T3), module wiring + holder identity (T4), endpoints + masking + keep/replace/clear + probe (T5), UI (T6), README consuming section + repo chores + smoke (T7), e2e incl. masked-key and unreachable-endpoint paths (T8). Multi-worker limitation documented in README (T7). No spec item is untasked.
- **Known adaptation points** (verify-don't-assume steps are built into the tasks): settings module meta name (T1 S4), pydantic-ai `model_name` attribute (T3 S5), `PermissionRegistry`/`MenuRegistry` accessor names (T4 S2), `RequiresPermission` request attribute (T5 S7), CSRF fetch pattern (T6 S1), helpers.ts login export (T8 S1).
- **Type consistency:** `SlotValues`/`AiSettingsOut` field names match the Python schemas; `build_changes` handles exactly the fields `AiSettingsUpdate` declares; constants referenced in tests exist in T1's `constants.py`.
