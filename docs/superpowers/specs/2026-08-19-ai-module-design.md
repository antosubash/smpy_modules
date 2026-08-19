# AI base module (`simple_module_ai`) — design

Date: 2026-08-19
Status: approved pending review

## Context

Every AI-flavoured SimpleModule app so far has built its own provider plumbing:
`iiasa_lib_rag`'s Rag module owns chat + embedding clients over two vLLM
endpoints and shares them with Pure through `app.state.rag`; `mowing_detect`
carries its own `VLLMMowingDetector`; GeoWiki (.NET) solved the same problem
with an `Ai` module (`AiSettings.cs` / `AiClientFactory`). This module is the
Python twin of that idea: one distributable base module that owns **connection
configuration** (provider, endpoint, key, model name) so consuming modules only
own **behaviour** (agents, prompts, temperature, retries, streaming).

First intended consumer: `iiasa_lib_rag`'s Rag module, which can later drop its
`clients/` and connection settings, declare `depends_on=["Ai"]`, and let Pure
take its embedder from `sm_ai.contracts` instead of `app.state.rag`. That
refactor is out of scope here; this design only has to make it possible.

## Scope

**In:** provider-configurable service layer (Pydantic AI), DB-backed settings
with encrypted keys, admin settings page with per-slot test-connection.

**Out (deliberately):** AI action registry, usage/cost tracking, vector store,
retry policy, concurrency caps, request timeouts, vision helpers, per-module
model overrides, i18n (repo-wide convention — see CLAUDE.md), model
auto-discovery from OpenAI-compatible endpoints. The last four are plausible
v2 items; the boundary rule below explains why the rest stay out.

**Boundary rule:** the base module resolves *connections*; consumers own
*behaviour*. Temperature, max_tokens, thinking toggles, system prompts,
embedding instruction prefixes (e.g. Qwen's asymmetric query/document
preambles), retries and streaming all live in the consuming module's own
`Agent` / call sites.

## Architecture: zero-table module on the framework settings store

The module ships **no SQLModel tables and no migration**. It registers a
pydantic `AiSettings(BaseSettings)` via the framework settings module's
`register_module_settings`, which gives it, for free:

- per-field storage in the shared settings store at SYSTEM scope,
- boot-time hydration (DB overrides merged over pydantic defaults),
- hot reload on save via `apply_changes_and_reload` (branding's pattern),
- secret masking in the generic module-settings UI (`api_key…` field names
  match `is_secret_field`),
- **env seeding**: `hydrate_settings` constructs `AiSettings(**db_overrides)`,
  so unset fields fall back to `SM_AI_*` env vars. Dev, CI and e2e can
  configure via env with zero DB rows; DB values win when present.

Rejected alternatives: an own `ai_settings` table (every consuming host would
need an alembic revision to adopt a *base* module, for a handful of key-value
pairs — config is what the settings store is for); hybrid split (most moving
parts, no benefit).

Consequences to accept: encrypted key blobs are visible as opaque strings in
the generic settings Browse UI; `simple_module_settings` becomes a declared
dependency (already transitively present wherever `users` is).

## Packaging

```
modules/ai/
├── pyproject.toml          # dist: simple_module_ai; entry point: ai = "sm_ai.module:AiModule"
├── package.json            # npm workspace member
├── README.md               # incl. "Consuming from another module" section
├── sm_ai/
│   ├── module.py           # AiModule(ModuleBase)
│   ├── constants.py        # package, prefixes, permission, page name, provider ids
│   ├── settings.py         # AiSettings(BaseSettings)
│   ├── crypto.py           # Fernet layer derived from SM_SECRET_KEY
│   ├── service.py          # internal: settings holder + provider/model construction
│   ├── contracts/__init__.py  # public: resolve_model, resolve_embedder, embedding_dim, errors
│   ├── endpoints/api.py    # GET/PUT settings, POST test
│   ├── endpoints/views.py  # renders "Ai/Settings"
│   ├── pages/Settings.tsx  # the only file in pages/
│   └── components/         # form pieces shared by the two cards
└── tests/
```

**Import package is `sm_ai`, not `ai`** — PyPI's `ai` is Vercel's AI SDK for
Python, which installs a top-level `ai` package; a bare `ai/` here would
collide in any host that installs it. Everything user-visible stays "ai":
distribution name, entry-point key, `/api/ai` + `/ai` prefixes, menu label.

Dependencies (ranges, never `==`): the framework trio and
`simple_module_settings`, all `>=0.0.25,<0.1` (floor verified:
`register_module_settings` and `apply_changes_and_reload` both exist at
0.0.25); `pydantic-ai-slim[anthropic,openai,google]` with the floor set to the
version implementation tests against and a `<` cap at the next major;
`cryptography` (Fernet). `ModuleMeta.depends_on` names the settings module
(exact meta name copied from its `module.py`).

Repo chores per `docs/adding-a-module.md`: metadata, README checks, root
`testpaths`, `ci.yml` pytest step, `release.yml` publish matrix, host
`pyproject.toml` dependency + workspace source. Step 8 (migration) is skipped —
there is nothing to migrate.

## Settings

```python
class AiSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="SM_AI_", extra="ignore")

    # --- chat slot ---
    chat_provider: str = "anthropic"      # anthropic | openai | google | openai_compatible
    chat_model: str = "claude-opus-5"     # bare model name, no provider prefix
    chat_base_url: str = ""               # required for openai_compatible; optional
                                          # override (proxy/gateway) for the rest
    chat_api_key: str = ""                # "enc:v1:<fernet>" at rest — see Crypto

    # --- embedding slot (unconfigured by default) ---
    embedding_provider: str = ""          # "" = embeddings not configured
    embedding_model: str = ""
    embedding_base_url: str = ""
    embedding_api_key: str = ""
    embedding_dim: int = 0                # consumer-visible (Qdrant fixes
                                          # collection width to it); cannot be inferred
```

Two slots because the first real consumer runs chat and embeddings as two
separate vLLM processes with different base URLs and models. `openai_compatible`
is first-class because *both* real projects (vLLM) — and Ollama, LM Studio —
speak it.

Provider validation happens at resolve time, not save time: an admin may
legitimately save a half-configured slot.

## Crypto

- Fernet key: SHA-256 of `SM_SECRET_KEY` → urlsafe base64. The module reads
  the env var through its own private one-field `BaseSettings` — no coupling
  to `app.state` or hosting internals.
- Stored format: `enc:v1:<fernet token>`. The prefix makes state unambiguous:
  - has prefix + decrypts → plaintext key;
  - has prefix + fails to decrypt → `AiKeyUnreadable` (secret key changed;
    UI says "re-enter the key") — an error, never a fallback;
  - no prefix → treated as plaintext, one warning logged ("stored
    unencrypted; re-save via the AI settings page to encrypt"). Covers keys
    pasted through the generic settings UI or seeded from env.
- Only the module's own save endpoint encrypts; rotation of `SM_SECRET_KEY`
  therefore means re-entering keys, stated in the README.

## Service layer (the contract)

```python
from sm_ai.contracts import resolve_model, resolve_embedder, embedding_dim
from sm_ai.contracts import AiNotConfigured, AiKeyUnreadable

agent = Agent(instructions=..., output_type=ArticleSummary)
result = await agent.run(text, model=resolve_model())
embedder = resolve_embedder()   # pydantic_ai.Embedder — embed calls per its API
```

- `resolve_model(model_name: str | None = None)` → a ready Pydantic AI model
  (`AnthropicModel` / `OpenAIChatModel` / `GoogleModel`; `openai_compatible`
  → `OpenAIChatModel` with `OpenAIProvider(base_url=...)`). `model_name`
  overrides the configured name for same-endpoint multi-model setups
  (mowing-style vision + text on one vLLM box).
- `resolve_embedder()` → a Pydantic AI `Embedder` from the embedding slot.
- `embedding_dim()` → the configured int.
- Empty key on `openai_compatible` → a placeholder literal is injected (the
  OpenAI protocol requires a non-empty key; vLLM ignores it — same move as
  GeoWiki's `AiClientFactory`).
- `AiNotConfigured(field)` raised when the selected provider is missing
  model/key/base_url; the message names the field.
- **No network I/O in `resolve_*`** — pure construction. Provider/auth
  failures surface in the consumer's `agent.run()`.
- No caching of resolved objects: construction is cheap, pydantic-ai's shared
  HTTP client keeps pooling, and a settings save applies on the next call.
- Internals: a module-level holder carries the hydrated `AiSettings`; startup
  sets it, hot reload refreshes it. Consumers never touch `app.state`, pass no
  sessions, and import nothing but `sm_ai.contracts`.

**Known limitation (inherited from the framework's hot-reload design):** a
save refreshes the worker that handled it; other uvicorn workers keep stale
settings until restart. Same property as branding. Documented in the README.

## Endpoints & UI

All routes gated by a single `ai.manage` permission (a settings page does not
earn a view/edit split). No public routes. Menu entry "AI" in the same group
as the other admin pages (group/icon copied from branding at implementation).

| Route | Purpose |
|---|---|
| `GET /ai/` | Inertia page `Ai/Settings` |
| `GET /api/ai/settings` | current values; secrets never echoed — `has_chat_api_key` / `has_embedding_api_key` booleans instead |
| `PUT /api/ai/settings` | save; secret fields: blank = keep existing, non-blank = encrypt + store; writes via the settings store, then `apply_changes_and_reload` |
| `POST /api/ai/test` | `{slot: "chat" \| "embedding"}` — one tiny real call through `resolve_*`; returns `{ok, model, latency_ms}` or `{ok: false, error}`; hard timeout; catches everything (wrong URL is a result, not a 500) |

`pages/Settings.tsx`: two cards (Chat, Embeddings), each with provider select,
model input, base-URL input (always visible, marked required only for
`openai_compatible`), key input with "leave blank to keep" placeholder, and a
per-card Test button rendering the result inline. Embeddings card adds the
dimension field. Hardcoded English (repo convention). Form pieces extracted to
`components/` — never `pages/` — to respect the 300-line cap.

## Testing

- **Module tests** (`modules/ai/tests`, `simple_module_test` fixtures, zero
  network): crypto roundtrip and all three `enc:v1` states; `resolve_model` /
  `resolve_embedder` per provider asserting the returned object's class,
  base_url and key wiring, placeholder-key injection, `model_name` override,
  every `AiNotConfigured` case; endpoint tests for secret masking and
  keep-vs-replace; test endpoint via Pydantic AI `TestModel` override. A
  fixture resets the module-level settings holder between tests.
- **Host smoke test**: AI routes + menu registered.
- **Playwright e2e**: settings page loads, save persists, key stays masked;
  test-button failure path against `http://127.0.0.1:1` (deterministic
  connection refusal — no stubs, no live providers in CI).

## Decisions log

| Decision | Choice |
|---|---|
| Scope v1 | service layer + settings UI; registry and usage tracking dropped |
| Access style | direct import from `sm_ai.contracts`; never `app.state` |
| Provider stack | Pydantic AI; providers: anthropic, openai, google, openai_compatible |
| Storage | framework settings store; zero tables, zero migrations |
| Secrets | in DB, Fernet-encrypted (`enc:v1:`), key derived from `SM_SECRET_KEY` |
| Model slots | two (chat + embeddings), driven by iiasa_lib_rag |
| Proof point | per-slot test-connection button |
| Import package | `sm_ai` (PyPI `ai` = Vercel AI SDK collision) |
