# AI operations

## Install

1. Add the package to the host. Modules use version ranges; the host pins the
   framework exactly:

   ```toml
   dependencies = [
       "simple_module_hosting==0.0.35",
       "simple_module_ai",
   ]
   ```

   It pulls in `simple_module_settings` (declared in `depends_on`),
   `pydantic-ai-slim[anthropic,openai,google]` and `cryptography`.
2. Nothing to migrate. The module has no tables; its values live in the
   settings module's store, which the host already migrates.
3. Make sure `SM_SECRET_KEY` is set (`make env` generates one into `.env`).
   Saving a key fails without it.
4. Start the app. The module is discovered through its `simple_module` entry
   point. The **AI** menu entry, under **Administration**, is shown to the
   `admin` role. The page and API check the `ai.manage` permission.

## Settings

| Field | Default | Env var | Notes |
|---|---|---|---|
| `chat_provider` | `anthropic` | `SM_AI_CHAT_PROVIDER` | `anthropic`, `openai`, `google`, `openai_compatible` |
| `chat_model` | `claude-opus-5` | `SM_AI_CHAT_MODEL` | bare model name, no provider prefix |
| `chat_base_url` | `""` | `SM_AI_CHAT_BASE_URL` | required for `openai_compatible`; an optional proxy/gateway override otherwise |
| `chat_api_key` | `""` | `SM_AI_CHAT_API_KEY` | stored `enc:v1:…` when saved through the AI page |
| `embedding_provider` | `""` | `SM_AI_EMBEDDING_PROVIDER` | `""` = not configured; `openai`, `google`, `openai_compatible` |
| `embedding_model` | `""` | `SM_AI_EMBEDDING_MODEL` | |
| `embedding_base_url` | `""` | `SM_AI_EMBEDDING_BASE_URL` | as for chat |
| `embedding_api_key` | `""` | `SM_AI_EMBEDDING_API_KEY` | as for chat |
| `embedding_dim` | `0` | `SM_AI_EMBEDDING_DIM` | vector width; `0` = not set |

Out of scope by design: temperature, max tokens, prompts, retries, timeouts
and streaming. Each consuming module sets those on its own `Agent` or call.

### Where a value comes from

Unlike `pagebuilder`, `news` and `billing`, the AI module **does** read
environment variables. `AiSettings` is a pydantic `BaseSettings` with
`env_prefix="SM_AI_"` and `env_file=".env"`. At boot the framework builds it
from the rows in the settings store, and any field without a row falls back
in this order:

1. a row in the settings store (SYSTEM scope, package `sm_ai`);
2. the `SM_AI_<FIELD>` environment variable;
3. the same variable in `.env`, resolved from the process's working
   directory (run from the repo root, as for every entry point here);
4. the default above.

Consequences:

- **Dev, CI and e2e can configure the module with no database rows**, e.g.
  `SM_AI_CHAT_PROVIDER=openai_compatible`, `SM_AI_CHAT_MODEL=…`,
  `SM_AI_CHAT_BASE_URL=http://127.0.0.1:8001/v1`.
- **A database row always wins.** A save writes only the fields whose value
  changed, so a field left as the environment set it keeps following the
  environment. Once a field is saved with a different value, changing its
  `SM_AI_*` variable does nothing.
- **Clearing a key stores an empty value**, and that row also wins: a cleared
  key doesn't fall back to `SM_AI_*_API_KEY`.
- A key seeded from the environment is plaintext. It works, and a one-time
  warning per field asks you to re-save it on the AI page to encrypt it.
- Environment values are read at process start; restart to pick up a change.

The settings can also be written headlessly with the repo's script, e.g.
`python scripts/set_setting.py sm_ai chat_model claude-opus-5`. Don't use it
for API keys: it writes the value as given, so the key would be stored
unencrypted.

## Keys at rest

Keys saved through the AI page or `PUT /api/ai/settings` are stored as
`enc:v1:<Fernet token>`. The Fernet key is the SHA-256 of the app's secret,
URL-safe base64-encoded. The secret is the running app's `secret_key` (which a
host may set in code via `create_app(settings=...)`), falling back to
`SM_SECRET_KEY` from the environment, then from `.env`. If none is set,
encrypting or decrypting raises `RuntimeError("SM_SECRET_KEY is not set …")`.

When a key is read:

| Stored value | Result |
|---|---|
| `enc:v1:…` that decrypts | the key |
| `enc:v1:…` that doesn't decrypt | `AiKeyUnreadableError` — never a silent fallback |
| no prefix | used as plaintext; a warning is logged once per field |

### Secret key rotation

Changing `SM_SECRET_KEY` makes every stored `enc:v1:` key unreadable. Nothing
breaks at boot. Each consumer's `resolve_*` call and each **Test connection**
fails with "The stored key '…' cannot be decrypted — SM_SECRET_KEY has
changed." Re-enter the chat and embedding keys on the AI page after a
rotation. The module doesn't re-encrypt old keys.

## Multiple workers

A save hot-reloads the settings of the worker process that handled the
request. Other uvicorn workers keep their previous settings until they
restart. On a multi-worker deployment, restart the app after changing AI
settings. (This comes from the framework's hot-reload design and applies to
branding too.)

## Troubleshooting

| Symptom | Likely cause | Check / fix |
|---|---|---|
| A module fails with "AI is not configured: 'module' …" | the code runs outside a host with `simple_module_ai` installed, or before the host's settings are registered | Install the module in the host; don't resolve at import time. |
| "'chat_api_key' is missing or invalid" | no key for a provider that needs one | Enter the key on the AI page. For a keyless local server, use `openai_compatible`. |
| "'chat_base_url' … needs the server's /v1 URL" | `openai_compatible` without a base URL | Set the base URL, ending in `/v1`. |
| "'embedding_provider' … not configured" | the embedding slot is empty | Configure **Embeddings**. |
| "'embedding_dim' … Set the vector width" | `embedding_dim` is `0` | Set **Vector dimension** to the model's output width. |
| "cannot be decrypted — SM_SECRET_KEY has changed" | secret rotated, or the host's in-code `secret_key` differs from the one used to save | Re-enter the keys. |
| Saving a key returns 500, log says `SM_SECRET_KEY is not set` | no secret anywhere | Set `SM_SECRET_KEY` (`make env`) and restart. |
| Every save fails with `chat_provider must be one of …` | an env-seeded provider outside the list (shown as "(unknown provider)") | Pick a real provider on the page, or fix `SM_AI_CHAT_PROVIDER`. |
| Save returns 403 "Invalid or missing CSRF token" | API called without the token, or the session changed | Reload `/ai/`; scripted clients must send `X-CSRF-Token` from the `sm_ai_csrf` cookie. |
| Warning "stored unencrypted" | a key came from `SM_AI_*`, `set_setting.py` or the generic settings screen | Re-save it on the AI page. |
| Saved a change but some requests still use the old model | other workers have stale settings | Restart the app. |
| Changing `SM_AI_CHAT_MODEL` has no effect | a database row for that field wins | Change it on the AI page instead. |
| **Test connection** OK, but a module still fails | the module's own call (prompt, output schema, model override) | That is the module's behaviour; check its logs. |
