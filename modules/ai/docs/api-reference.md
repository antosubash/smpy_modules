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
    AiError, AiKeyUnreadableError, AiNotConfiguredError,
    embedding_dim, resolve_embedder, resolve_model,
)
```

All three functions read the running host's current settings. You pass no
app, session or request. They also work in a process that never ran the web
host, such as a Celery worker: there they read the settings table and `SM_AI_*`
env themselves, cached per process for 60 seconds (see
[operations.md](operations.md#background-workers)). None of them makes a network call: they validate the
slot and build the object. Provider and authentication failures surface later,
when you call the provider (`agent.run()`, `embed_documents()` and so on), as
whatever exception Pydantic AI raises.

### `resolve_model(model_name: str | None = None) -> pydantic_ai.models.Model`

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
3. **Key.** A stored `enc:v1:` key is decrypted. If decryption fails, this
   raises `AiKeyUnreadableError` (`chat_api_key` / `embedding_api_key`).
4. **Base URL / key.** `openai_compatible` needs a base URL
   (`*_base_url`), and an empty key is replaced by the placeholder
   `not-needed`. Every other provider needs a key (`*_api_key`).

### Errors

| Exception | Raised when | Attributes |
|---|---|---|
| `AiError` | base class; catch this to handle every AI module error | |
| `AiNotConfiguredError(AiError)` | a required setting is missing or invalid | `field`; the message names it and may add a hint |
| `AiKeyUnreadableError(AiError)` | a stored key has the `enc:v1:` prefix but can't be decrypted, because `SM_SECRET_KEY` changed | `field` |

## HTTP API — `/api/ai`

Every route requires the `ai.manage` permission. `PUT` and `POST` also need
the CSRF token in an `X-CSRF-Token` header. The settings view (`GET /ai/`)
stores the token in the session. Responses under `/ai` and `/api/ai` then
copy it to the JS-readable cookie `sm_ai_csrf` whenever the request didn't
already carry the current value
(`SameSite=Strict`, `Secure` over HTTPS). A missing or wrong token gives
`403 {"detail": "Invalid or missing CSRF token"}`. When the host mounts no
session middleware, the check is skipped and a warning is logged once.

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

`null` is treated as omitted. Only values that differ from the current ones
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
{"ok": true,  "model": "claude-opus-5", "latency_ms": 812, "error": ""}
{"ok": false, "model": "claude-opus-5", "latency_ms": 0,
 "error": "AI is not configured: 'chat_api_key' is missing or invalid."}
```

Every failure returns `200` with `ok: false`: missing configuration, an
unreadable key, a refused connection, an authentication error, or
`"Timed out after 30s."`. The server logs a configuration or provider
failure (an `AiError`, a refused connection, a provider error status) as one
warning line, and anything else with its traceback, so a code defect stays
distinguishable from a configuration problem.

### `POST /api/ai/models`

Request `{"slot": "chat"}` or `{"slot": "embedding"}`; any other slot is a
`422`. Lists the model ids the slot's **saved** endpoint serves, through the
provider's own SDK: `models.list()` for `openai` and `openai_compatible`, and
for `anthropic`; for `google`, the models whose supported actions include
`generateContent` (chat) or `embedContent` (embedding), without the `models/`
prefix. The slot needs a provider, its key (or a base URL for
`openai_compatible`) — but no model name, since finding one is the point.

```json
{"ok": true,  "models": ["llama-3-8b", "mistral-7b", "qwen-7b"], "truncated": false, "error": ""}
{"ok": false, "models": [], "truncated": false, "error": "Connection error."}
```

Ids are sorted and de-duplicated. At most 500 are returned; `truncated` is
`true` when the endpoint served more (the first 500 alphabetically). OpenAI's
list carries no capability information, so an `openai`/`openai_compatible`
embedding slot lists every model the endpoint serves. Failures follow the
`/test` contract: `200` with `ok: false`, 30-second limit, same logging.
