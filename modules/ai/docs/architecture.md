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
- hydration at lifespan start: `AiSettings(**db_overrides)`. `AiSettings`
  is a `DbBackedSettings`, which drops pydantic-settings' env, `.env` and
  secrets sources, as pagebuilder, news and billing do, so a field with no
  row is its default. Until #124 it kept an `SM_AI_` env and cwd-relative
  `.env` fallback, which let a worker started from another directory see a
  different provider than the web host. Nothing is read while booting, so no
  field needs a restart;
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
touch `app.state` or pass a session.

A process that never registered the module — a Celery worker, a script — has
an empty holder. There `current_settings()` hydrates lazily through
`worker_settings.py` (#100): the framework's `hydrate_settings` over a
`SettingsStore` on a short-lived engine for `SM_DATABASE_URL`, so the
result is the web lifespan's (the DB row, else the default). It also installs
a secret provider resolving the secret the web app encrypts under: explicit
`SM_SECRET_KEY` (env, or the `.env` `BootstrapSettings` finds), else the
stored `host.secret_key`.
Framework 0.0.36's `SettingsReloaded` only travels the web process's in-memory
bus, so the worker caches for `LAZY_SETTINGS_TTL_SECONDS` (60 s) and
`services.invalidate()` forces a re-read. An unreachable or unmigrated
database falls back to the defaults with a warning, as the lifespan's
hydrate step does.

`resolve.py` is pure construction with no I/O, and nothing is cached. A new
model or embedder is built on every call: construction is cheap,
pydantic-ai's shared HTTP client keeps pooling connections, and a save applies
on the very next call. All validation goes through one function,
`_slot_inputs`, for both slots (rules in
[api-reference.md](api-reference.md#validation-both-resolve-functions)).
Provider membership is checked at resolve time, not save time, so an admin
can save a half-configured slot. The update DTO does validate provider names
and forbids a blank chat model.

The module calls a provider itself in two places only, both admin buttons in
`endpoints/api.py`. `POST /api/ai/test` takes one settings snapshot, so the
reported model always matches the configuration being tested. `POST
/api/ai/models` lists the saved endpoint's models through the provider SDK
(`discovery.py`, which reuses `resolve.slot_inputs` without the model-name
requirement). Both turn every exception into `ok: false` and log a
configuration or provider failure as one line, anything else with its
traceback.

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
environment, then from the project `.env` exactly as the framework's
`BootstrapSettings` finds it — `$SM_PROJECT_ROOT/.env`, else a bounded walk up
from the cwd to the project root — so it is the file the host itself reads,
never one that merely happens to sit in the working directory (cached, since
the file can't change without a restart). The placeholder default
`BootstrapSettings` carries never counts. The provider is consulted on every call and the derived `Fernet` is
cached per secret, so a call made before the app's secret exists can't fix the
fallback secret for the rest of the process.

`billing` uses the same scheme in its own `crypto.py` copy. A published module
must not import a sibling optional module.

## CSRF

The write API can change `chat_base_url` and so send the stored key to
another server. A forged cross-site `PUT` is therefore the threat.
The defence is the framework's, `simple_module_hosting.csrf`, the same one
billing, news, records and pagebuilder use:

- the API router carries `RequiresCsrf()`, which checks `X-CSRF-Token` against
  the session's token on `POST`/`PUT`/`PATCH`/`DELETE` and skips the check when
  no session is mounted;
- `csrf.py`'s `share_csrf_token`, a view-router dependency, shares
  `get_csrf_token(request)` as the `csrf_token` Inertia prop;
- `utils/csrf.ts` keeps the latest prop value (the server-rendered page, then
  every Inertia navigation) and `utils/api.ts` sends it on every write.

There is no middleware and no cookie.

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
    embedder = resolve_embedder()  # AiNotConfiguredError until the slot is set
    result = await embedder.embed_documents(chunks)
    ...  # store vectors; width = embedding_dim()
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
| `settings.py` | `AiSettings`: the nine DB-backed fields |
| `services.py` | `AiServices` and the module-global holder |
| `worker_settings.py` | lazy, TTL-cached hydration where no host registered the module (workers) |
| `resolve.py` | slot validation and model / embedder construction |
| `crypto.py` | `enc:v1:` Fernet layer |
| `service.py`, `deps.py` | read with secrets masked; build and apply changes |
| `csrf.py` | shares the framework CSRF token with the settings page |
| `metering.py` | `ai.requests`: registers the meter with an installed billing, and `RequiresAiRequest` (billing's `RequiresQuota`, or a no-op without billing) |
| `contracts/` | the public surface (`__init__.py`), errors, API DTOs |
| `endpoints/` | `api.py` (settings, test), `views.py` (`Ai/Settings`) |
| `pages/Settings.tsx`, `components/SlotCard.tsx`, `utils/` | the settings page (only real Inertia pages under `pages/`); `utils/quotaError.ts` renders billing's 402 |
| `locales/en.json` | console strings, namespace `ai` |
