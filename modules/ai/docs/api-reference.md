# AI API reference

The AI module has two surfaces. The **Python contract** in `sm_ai.contracts`
is what other modules use. The **HTTP API** under `/api/ai` backs the
settings page.

## Python contract — `sm_ai.contracts`

Import from `sm_ai.contracts` only. Everything else in `sm_ai` is internal.
The import package is `sm_ai`, not `ai`, because the bare name belongs to
another PyPI project.

```python
from sm_ai.contracts import (
    METER_REQUESTS,
    AiBaseUrlRefusedError,
    AiError,
    AiKeyUnreadableError,
    AiNotConfiguredError,
    RequiresAiRequest,
    consume_requests,
    embedding_dim,
    resolve_embedder,
    resolve_model,
)
```

The three resolve functions read the running host's current settings. You pass no
app, session or request. They also work in a process that never ran the web
host, such as a Celery worker: there they read the settings table
themselves, cached per process for 60 seconds (see
[operations.md](operations.md#background-workers)). None of them makes a network call: they validate the
slot and build the object. Provider and authentication failures surface later,
when you call the provider (`agent.run()`, `embed_documents()` and so on), as
whatever exception Pydantic AI raises.

### `resolve_model(model_name: str | None = None, *, max_retries: int | None = None) -> pydantic_ai.models.Model`

`max_retries` sets the provider SDK's own transport retries on the client it
builds (OpenAI and OpenAI-compatible, Anthropic: the client's `max_retries`;
Google: `HttpRetryOptions(attempts=max_retries + 1)`). `None` keeps the SDK
default. A caller that meters each call with `consume_requests` passes `0`,
so one charge is at most one provider request.

Builds a chat model from the **chat** slot:

| `chat_provider` | Returns |
|---|---|
| `anthropic` | `AnthropicModel` with `AnthropicProvider(api_key=…)` |
| `openai` | `OpenAIChatModel` with `OpenAIProvider(api_key=…)` |
| `openai_compatible` | `OpenAIChatModel` with `OpenAIProvider(api_key=…, base_url=…)` |
| `google` | `GoogleModel` with `GoogleProvider(api_key=…)` |

A non-empty `chat_base_url` is passed as `base_url` for every provider.
`model_name` replaces the configured model name for this call only, for
setups that serve several models from one endpoint (e.g. a vision model and a
text model on one vLLM server). The provider, key and URL stay the slot's.

### `resolve_embedder() -> pydantic_ai.Embedder`

Builds an `Embedder` from the **embedding** slot. `openai` and
`openai_compatible` use `OpenAIEmbeddingModel`; `google` uses
`GoogleEmbeddingModel`. `anthropic` is refused because Anthropic has no
embeddings API.

### `embedding_dim() -> int`

Returns the configured `embedding_dim`. Raises
`AiNotConfiguredError("embedding_dim")` while it is `0`. Read it when you
create a vector collection, since the store fixes the width there.

### Validation (both resolve functions)

Each slot is checked in this order. The first failure raises
`AiNotConfiguredError` with `field` set to the setting at fault:

1. **Provider.** It is trimmed and lower-cased. An empty embedding provider
   means "not configured" (`embedding_provider`). A value outside the slot's
   list fails with a hint that names the allowed values, or says Anthropic has
   no embeddings API.
2. **Model.** The `model_name` override, or the configured model, must not be
   blank (`chat_model` / `embedding_model`).
3. **Key.** A stored `enc:v2:` (or 0.0.15 `enc:v1:`) key is decrypted under
   `SM_SECRET_KEY` or a key in `SM_SECRET_KEY_PREVIOUS`. If none opens it, this
   raises `AiKeyUnreadableError` (`chat_api_key` / `embedding_api_key`).
4. **Base URL / key.** `openai_compatible` needs a base URL
   (`*_base_url`), and an empty key is replaced by the placeholder
   `not-needed`. Every other provider needs a key (`*_api_key`).
5. **Base URL address.** A base URL must be `http(s)`; unless
   `allow_private_base_url` is on, a private IP literal raises
   `AiBaseUrlRefusedError`, and the model's HTTP client resolves the host at
   each request and refuses a non-public address (the SDK then raises its
   connection error, caused by `sm_ai.core.url_safety.UnsafeURLError`). See
   "Base URLs and the network" in [operations.md](operations.md).

### Errors

| Exception | Raised when | Attributes |
|---|---|---|
| `AiError` | base class; catch this to handle every AI module error | |
| `AiNotConfiguredError(AiError)` | a required setting is missing or invalid | `field`; the message names it and may add a hint |
| `AiBaseUrlRefusedError(AiError)` | a base URL is not `http(s)`, or is a private IP literal while `allow_private_base_url` is off (#347); the message names the setting to turn on and never the URL | `field`, `reason` |
| `AiKeyUnreadableError(AiError)` | a stored key has an `enc:` prefix but neither `SM_SECRET_KEY` nor a key in `SM_SECRET_KEY_PREVIOUS` decrypts it (the secret was rotated without keeping the old one), or names an unknown format | `field` |

### Usage metering: `RequiresAiRequest`

`RequiresAiRequest(qty: int = 1)` is a FastAPI dependency for a consumer's
route that calls the model. It charges `qty` of the `ai.requests` meter
(`METER_REQUESTS`) to the request's tenant before the handler runs:

```python
@router.post("/summarise", dependencies=[RequiresAiRequest()])
async def summarise(...): ...
```

| Host | Behaviour |
|---|---|
| billing installed and running | billing's `RequiresQuota("ai.requests", qty)`, unchanged: its tenant rule (single-tenant host: `default`; multi-tenant: the resolved tenant, else 403 `tenant_required`), 402 `quota_exceeded` past the limit, its `Idempotency-Key` rules |
| billing installed, not running | yields `None`; nothing is limited |
| no billing (or one older than usage metering) | a no-op yielding `None`; billing is never imported |

`AiModule.on_startup` registers the meter (`counter`, unit `count`, label
`ai.meters.requests`) when `app.state.billing_meters` exists, so the plan
editor suggests it. A `qty` that is not an integer from 1 to 2^53 raises
`ValueError` at route definition, with or without billing.

**Refunds.** The charge is refunded only when the handler raises. A provider
or model error that propagates (or is re-raised as an `HTTPException`) costs
nothing; a handler that catches it and *returns* an error response keeps the
charge. **Streaming.** The dependency is function-scoped, so for a
`StreamingResponse` it settles when the handler returns the response, before
the body streams: open the model call inside the handler if a failure to
connect should refund, and know that an error mid-stream does not.

**The 402 in the browser.** The body is
`{"detail": "quota_exceeded", "meter", "limit", "used", "requested", "resets_at"}`.
`sm_ai/ui/utils/quotaError.ts` (`isQuotaExceeded`, `quotaMessage`) renders it as
"AI requests limit reached (1/1); resets Nov 1, 2026." in the console's
language; this module's `api.ts` decodes every failed call through it.

### Usage metering outside a request: `consume_requests`

```python
async def consume_requests(
    tenant_id: str, qty: int = 1, *, idempotency_key: str, source: str,
    session_factory=None,
) -> bool
```

For code with no request and no app, such as a Celery task. Call it before
each model call and skip the call when it answers `False` (the plan's limit
refused it, or the key was since refunded). With billing installed it is
billing's `usage_meter(session_factory).consume(..., "ai.requests", ...)`:
billing's conditional upsert, in its own short transaction finished with
`finalize_session`. `session_factory` is the caller's (images passes its
pipeline's); without one, the process opens a `NullPool` engine of its own
on the host's database URL (`SM_DATABASE_URL`, else the project `.env`, read
through `BootstrapSettings`). Only when `sm_billing` is not installed at all
does it return `True` (and import nothing). An installed billing that cannot
meter fails closed: one older than `usage_meter` raises `RuntimeError`, and an
import error propagates, so a call is never free because billing failed to
load. A worker cannot see the
web host's module list, so an *installed* billing counts as running there.

`idempotency_key` makes a retry of the same call free: a replay answers the
first outcome and counts nothing (images uses
`images:{tenant}:{image}:{step}:{version}:{lease token}`). Never put personal
data in the key or `source`. `qty` outside 1 to 2^53, or an empty key or
source, raises `ValueError`. Nothing is refunded: a provider error after the
charge keeps it, since the provider may have billed the call.

## HTTP API — `/api/ai`

Every route requires the `ai.manage` permission. `PUT` and `POST` also need
the session's CSRF token in an `X-CSRF-Token` header. The check is the
framework's `RequiresCsrf`, the one billing, news, records and pagebuilder use,
so one token serves every module. The settings view (`GET /ai/`) shares it as
the `csrf_token` Inertia prop (`simple_module_hosting.csrf.get_csrf_token`),
and the page sends it from there; there is no CSRF cookie. A missing or wrong
token gives `403 {"detail": "CSRF token missing or invalid — …"}`, before the
permission check runs. When the host mounts no session middleware, the
framework skips the check (there is no session to bind a token to).

Body validation errors are FastAPI's `422` with a Pydantic error list.

### `GET /api/ai/settings`

The current settings. Keys are never returned, only whether one is stored.

```json
{
  "chat_providers": ["anthropic", "openai", "google", "openai_compatible"],
  "embedding_providers": ["openai", "google", "openai_compatible"],
  "chat_provider": "anthropic",
  "chat_model": "claude-opus-5",
  "chat_base_url": "",
  "has_chat_api_key": true,
  "embedding_provider": "",
  "embedding_model": "",
  "embedding_base_url": "",
  "has_embedding_api_key": false,
  "embedding_dim": 0
}
```

`*_providers` are the lists the server validates against. The settings page
builds its dropdowns from them. Providers are returned lower-cased.

### `PUT /api/ai/settings`

A partial update: send only the fields you want to change. The response is
the same shape as `GET`.

| Field | Type | Rules |
|---|---|---|
| `chat_provider` | string | trimmed, lower-cased, must be a chat provider |
| `chat_model` | string | must not be blank |
| `chat_base_url` | string | trimmed |
| `chat_api_key` | string | trimmed; blank or omitted keeps the stored key; otherwise encrypted and stored |
| `clear_chat_api_key` | bool | `true` removes the stored chat key (wins over `chat_api_key`) |
| `embedding_provider` | string | `""` (not configured) or an embedding provider |
| `embedding_model`, `embedding_base_url` | string | trimmed |
| `embedding_api_key`, `clear_embedding_api_key` | string, bool | as for chat |
| `embedding_dim` | int | `>= 0` |
| `allow_private_base_url` | bool | changing it needs `settings.edit` as well (`403 Permission required: settings.edit`); sending the current value needs nothing |

`null` is treated as omitted. A slot whose provider is `openai_compatible`
must end up with a non-blank base URL — judged on the stored values merged
with the update, so sending only the provider, or blanking the URL, is a `422`
whose error `loc` names `chat_base_url` or `embedding_base_url`. A non-blank
base URL must be an `http(s)` URL, and unless `allow_private_base_url` is on
its host is resolved and every address must be public (#347); otherwise it is
a `422` on that field with `ctx.reason` `non_public_address` (the message says
to turn on `allow_private_base_url`), `unresolvable_host`, `invalid_scheme`,
`userinfo_not_allowed`, `missing_host` or `invalid_url`. Only values that differ from the current ones
are written. The handling worker's settings are replaced immediately and a
`SettingsReloaded` event is published.

```bash
curl -X PUT https://app.example.com/api/ai/settings \
  -H 'Content-Type: application/json' -H "X-CSRF-Token: $TOKEN" -b "$COOKIES" \
  -d '{"chat_provider": "openai_compatible", "chat_model": "qwen3-32b",
       "chat_base_url": "http://gpu-host:8000/v1"}'
```

### `POST /api/ai/test`

Request `{"slot": "chat"}` or `{"slot": "embedding"}`; any other slot is a
`422`. Makes one real call through the **saved** settings: a chat run of
"Reply with the single word: ok", or an `embed_query` of the same text, with a
30-second limit.

```json
{"ok": true,  "model": "claude-opus-5", "latency_ms": 812, "error": "", "code": "", "status": 0}
{"ok": false, "model": "claude-opus-5", "latency_ms": 0, "code": "unauthorised", "status": 401,
 "error": "The endpoint refused the API key (HTTP 401 or 403)."}
```

Every failure returns `200` with `ok: false`, a stable `code` and a fixed
English `error` for it; the provider's own message is never returned (#347),
since it can describe whatever answered at the base URL. The console
translates by `code`:

| `code` | Meaning |
|---|---|
| `base_url_refused` | the base URL is not `http(s)`, or resolves to a private or local address while `allow_private_base_url` is off |
| `not_configured` | provider, model, key or required base URL missing |
| `key_unreadable` | the stored key cannot be decrypted |
| `unreachable` | the host does not resolve, or the connection failed |
| `connection_refused` | nothing listens at that address and port |
| `timeout` | no answer in time (the 30-second probe deadline, or the SDK's or pinned client's own timeout) |
| `unauthorised` | HTTP 401 or 403 (`status` says which) |
| `http_error` | another status the call did not succeed with (`status`), a `3xx` included: redirects are not followed |
| `other` | anything else |

The server logs the failure with its class and the exception text: a
configuration or provider failure as one warning line, anything else with
its traceback, so a code defect stays distinguishable from a configuration
problem.

The probe is not metered as `ai.requests`. It is the operator checking the
deployment-wide (SYSTEM-scope) connection, not an organisation's use, and an
organisation that used up its allowance must not stop the operator from
diagnosing the provider.

### `POST /api/ai/models`

Request `{"slot": "chat"}` or `{"slot": "embedding"}`; any other slot is a
`422`. Lists the model ids the slot's **saved** endpoint serves, through the
provider's own SDK: `models.list()` for `openai` and `openai_compatible`, and
for `anthropic`; for `google`, the models whose supported actions include
`generateContent` (chat) or `embedContent` (embedding), without the `models/`
prefix. The slot needs a provider, its key (or a base URL for
`openai_compatible`) — but no model name, since finding one is the point.

```json
{"ok": true,  "models": ["llama-3-8b", "mistral-7b", "qwen-7b"], "truncated": false, "error": "", "code": "", "status": 0}
{"ok": false, "models": [], "truncated": false, "code": "connection_refused", "status": 0,
 "error": "The endpoint refused the connection: is the server running?"}
```

Ids are sorted and de-duplicated. At most 500 are returned; `truncated` is
`true` when the endpoint served more (the first 500 alphabetically). OpenAI's
list carries no capability information, so an `openai`/`openai_compatible`
embedding slot lists every model the endpoint serves. Failures follow the
`/test` contract: `200` with `ok: false`, 30-second limit, same logging.
