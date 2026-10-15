# AI architecture

Design record: `docs/superpowers/specs/2026-08-19-ai-module-design.md`
(repo root). This page describes the code as it is.

## Boundary

**The module resolves connections; consumers own behaviour.** It decides which
provider, endpoint, key and model name a call uses. Temperature, max tokens,
thinking toggles, system prompts, embedding instruction prefixes, retries,
timeouts and streaming belong in the consuming module's `Agent` or call site.
The module has no action registry, no usage or cost tracking, no vector store
and no per-module model overrides. Keep it that way. The `model_name`
argument to `resolve_model` is the one escape hatch, for several models
served by one endpoint.

## No tables

`AiSettings` (`settings.py`) is registered with the framework settings
module's `register_module_settings` (`module.py`, `register_settings`). That
provides:

- per-field storage at SYSTEM scope under package `sm_ai`;
- hydration at lifespan start: `AiSettings(**db_overrides)`. Because
  `AiSettings` keeps pydantic-settings' env and `.env` sources (prefix
  `SM_AI_`), a field with no row falls back to the environment. This is
  deliberate, and it is where ai differs from pagebuilder, news and billing,
  which drop those sources;
- hot reload on save through `settings.reload.apply_changes_and_reload`,
  which validates, writes the changed fields, swaps `.settings` and publishes
  `SettingsReloaded`.

The alternative, an `ai_settings` table, would make every host write an
Alembic revision to adopt a *base* module for a handful of key-value pairs.
The cost of this approach is that encrypted keys show up as opaque strings in
the generic settings screen.

## From the store to a consumer's call

```
register_module_settings(app, "sm_ai", AiSettings, factory)
        │  factory = services.install(AiServices(settings=s))
        ▼
AiServices instance ──► app.state.sm_ai        (hydration / reload assign .settings)
        └────────────► services._current        (module-global holder)
                                │
sm_ai.contracts.resolve_model() ─► services.current_settings()
                                ─► resolve.build_chat_model(settings, model_name)
```

The factory stores **the same instance** in `app.state.sm_ai` and in the
module-global holder. Hydration and hot reload assign `.settings` on that
object, so `sm_ai.contracts` always sees the current values. Consumers never
touch `app.state` or pass a session. Before a host has registered the module,
`current_settings()` raises `AiNotConfiguredError("module")`.

`resolve.py` is pure construction with no I/O, and nothing is cached. A new
model or embedder is built on every call: construction is cheap,
pydantic-ai's shared HTTP client keeps pooling connections, and a save applies
on the very next call. All validation goes through one function,
`_slot_inputs`, for both slots (rules in
[api-reference.md](api-reference.md#validation-both-resolve-functions)).
Provider membership is checked at resolve time, not save time, so an admin
can save a half-configured slot. The update DTO does validate provider names
and forbids a blank chat model.

The only provider call the module makes itself is `POST /api/ai/test`
(`endpoints/api.py`). It takes one settings snapshot, so the reported model
always matches the configuration being tested, and turns every exception into
`ok: false`.

## Keys

`crypto.py`: `Fernet(urlsafe_b64encode(sha256(secret)))`, stored as
`enc:v1:<token>`. The prefix makes the state unambiguous: it decrypts (the
key), it fails (`AiKeyUnreadableError`, never a fallback), or it is absent
(plaintext, warned once per field). Only `AiService.build_changes`
(`service.py`) encrypts, and it trims the value first. Blank means keep the
stored key, and `clear_*` empties it.

The secret comes from a provider installed in `register_settings` that reads
the live app's `settings.secret_key` through a weakref. Test suites build many
apps, and a strong reference would keep the discarded ones alive. If the
provider has nothing, the module reads `SM_SECRET_KEY` from the process
environment, then from `.env` (cached, since the file can't change without a
restart). The provider is consulted on every call and the derived `Fernet` is
cached per secret, so a call made before the app's secret exists can't fix the
fallback secret for the rest of the process.

`billing` uses the same scheme in its own `crypto.py` copy. A published module
must not import a sibling optional module.

## CSRF

The write API can change `chat_base_url` and so send the stored key to
another server. A forged cross-site `PUT` is therefore the threat.
`security.py` (adapted from pagebuilder's, not imported):

- `mint_csrf_token`, a view-router dependency, puts a random token in the
  session;
- `CsrfCookieMiddleware` copies it to the `sm_ai_csrf` cookie on responses
  under `/ai` and `/api/ai`. It is a middleware because FastAPI doesn't merge
  a dependency's cookie writes into a returned `Response`;
- `verify_csrf`, an API-router dependency, compares `X-CSRF-Token` in
  constant time (as bytes) on `POST`/`PUT`/`PATCH`/`DELETE`. With no session
  mounted it skips the check and logs a warning once.

## Consuming from another module

Declare the dependency so the AI module registers first, and add
`simple_module_ai` (a range, never `==`) to your module's `pyproject.toml`:

```python
# my_module/module.py
meta = ModuleMeta(name="Summaries", depends_on=["Ai"], ...)
```

Resolve at call time, never at import or startup. Settings hydrate at lifespan
start and can change on any save:

```python
import logging

from pydantic import BaseModel
from pydantic_ai import Agent
from sm_ai.contracts import AiNotConfiguredError, resolve_embedder, resolve_model

logger = logging.getLogger(__name__)


class Summary(BaseModel):
    title: str
    bullets: list[str]


# Behaviour lives here: instructions, output type, model settings, retries.
summariser = Agent(
    instructions="Summarise the article in three bullets.",
    output_type=Summary,
    model_settings={"temperature": 0.2},
    retries=2,
)


async def summarise(text: str) -> Summary | None:
    try:
        result = await summariser.run(text, model=resolve_model())
    except AiNotConfiguredError as exc:
        logger.info("AI not set up (%s); skipping summary", exc.field)
        return None
    return result.output


async def index(chunks: list[str]) -> None:
    embedder = resolve_embedder()        # AiNotConfiguredError until the slot is set
    result = await embedder.embed_documents(chunks)
    ...                                  # store vectors; width = embedding_dim()
```

- Catch `AiNotConfiguredError` where "AI is off" is a valid state, and let
  `AiKeyUnreadableError` (or `AiError`) reach the admin as an error.
- Provider errors (auth, network, rate limits) come from Pydantic AI during
  `run()` / `embed_*()`, not from `resolve_*`.
- Create vector collections with `embedding_dim()`. When it changes, the
  consumer is responsible for re-indexing.
- In tests, pass a Pydantic AI `TestModel` to `run(model=...)` instead of
  calling `resolve_model()`.

## File map

| File | Responsibility |
|---|---|
| `module.py` | framework hooks: settings registration, secret provider, permission, menu, routes, middleware |
| `settings.py` | `AiSettings`: the nine fields and the `SM_AI_` env fallback |
| `services.py` | `AiServices` and the module-global holder |
| `resolve.py` | slot validation and model / embedder construction |
| `crypto.py` | `enc:v1:` Fernet layer |
| `service.py`, `deps.py` | read with secrets masked; build and apply changes |
| `security.py` | CSRF mint, verify, cookie mirror |
| `contracts/` | the public surface (`__init__.py`), errors, API DTOs |
| `endpoints/` | `api.py` (settings, test), `views.py` (`Ai/Settings`) |
| `pages/Settings.tsx`, `components/SlotCard.tsx`, `utils/` | the settings page (only real Inertia pages under `pages/`) |
| `locales/en.json` | console strings, namespace `ai` |
