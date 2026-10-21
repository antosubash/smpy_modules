# AI operations

## Install

1. Add the package to the host. Modules use version ranges; the host pins the
   framework exactly:

   ```toml
   dependencies = [
       "simple_module_hosting==0.0.36",
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

| Field | Default | Notes |
|---|---|---|
| `chat_provider` | `anthropic` | `anthropic`, `openai`, `google`, `openai_compatible` |
| `chat_model` | `claude-opus-5` | bare model name, no provider prefix |
| `chat_base_url` | `""` | required for `openai_compatible`; an optional proxy/gateway override otherwise |
| `chat_api_key` | `""` | stored `enc:v1:…` when saved through the AI page |
| `embedding_provider` | `""` | `""` = not configured; `openai`, `google`, `openai_compatible` |
| `embedding_model` | `""` | |
| `embedding_base_url` | `""` | as for chat |
| `embedding_api_key` | `""` | as for chat |
| `embedding_dim` | `0` | vector width; `0` = not set |

Out of scope by design: temperature, max tokens, prompts, retries, timeouts
and streaming. Each consuming module sets those on its own `Agent` or call.

### Where a value comes from

Like `pagebuilder`, `news` and `billing`, the AI module reads **no
environment variables**. `AiSettings` is a `DbBackedSettings`: it has no env,
`.env` or secrets-file source, so a field is either its row in the settings
store (SYSTEM scope, package `sm_ai`) or the default above. An `SM_AI_*`
variable anywhere is dead. Nothing is read only at boot, so no field needs a
restart; a save applies on the next call.

### One configuration for every tenant

The settings are SYSTEM-scope only. On a multi-tenant host every tenant uses
the same chat and embedding providers, and **the same API keys** — usage by
every organisation is billed to the one provider account behind them. There
is no per-tenant key or model. A consumer that needs to separate tenants'
usage has to do it itself (for example, tagging requests in a gateway set as
`chat_base_url`).

### Configuring without the UI

A fresh deployment, CI job or e2e stack configures the module with the repo's
script, run from the repo root, e.g.
`python scripts/set_setting.py sm_ai chat_model claude-opus-5`. It writes the
value as given, so an API key written that way is stored unencrypted. It
works, and a one-time warning per field asks you to re-save it on the AI page
to encrypt it; for a production key, prefer entering it on the AI page.

### Moving off `SM_AI_*` variables

Before #124 a field with no row fell back to `SM_AI_<FIELD>` in the
environment or a `.env` in the working directory. A deployment that relied on
that now gets the defaults. For each variable you set, write the row once and
delete the variable:

```bash
python scripts/set_setting.py sm_ai chat_provider openai_compatible
python scripts/set_setting.py sm_ai chat_model my-model
python scripts/set_setting.py sm_ai chat_base_url http://127.0.0.1:8001/v1
```

then enter the API keys on the AI page so they are stored encrypted. Fields
already saved on the AI page are unaffected: their row always won.

## Keys at rest

Keys saved through the AI page or `PUT /api/ai/settings` are stored as
`enc:v1:<Fernet token>`. The Fernet key is the SHA-256 of the app's secret,
URL-safe base64-encoded. The secret is the running app's `secret_key` (which a
host may set in code via `create_app(settings=...)`), falling back to
`SM_SECRET_KEY` from the environment, then from the project `.env` as the
framework's `BootstrapSettings` locates it: `$SM_PROJECT_ROOT/.env` when that
variable is set, otherwise the first `.env` found walking up from the working
directory to the project root (the directory holding `.git` or
`.env.example`). That is the file the host itself reads, so a process started
from `host/` or `modules/ai/` finds the same secret; one started outside the
project must set `SM_PROJECT_ROOT` (or `SM_SECRET_KEY`). If none is set,
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

### Background workers

A Celery worker (or any process that imports a consumer without running the
web host) reads the AI settings itself: the same settings table the web app
uses, through `SM_DATABASE_URL`, with the defaults beneath it. To decrypt
stored keys it needs the web app's secret — the same `SM_SECRET_KEY` (in its
environment, or in the project `.env`; start a worker outside the project
with `SM_PROJECT_ROOT` pointing at it), or, when that is unset, read access
to the `host.secret_key` row the web app generated. Settings are cached per worker process for 60
seconds, so a save on the AI page reaches workers within a minute without a
restart; `sm_ai.services.invalidate()` forces a re-read. If the database
can't be read, the worker uses the defaults for 5 seconds and then tries
again; each read is capped at 5 seconds, and while one thread re-reads, the
others keep the previous settings. A SQLite file that doesn't exist yet is
never opened, so a worker can't create an empty one.

## Troubleshooting

| Symptom | Likely cause | Check / fix |
|---|---|---|
| A worker logs "AI settings: database read failed (…)" — once per outage; the bracket names the error type only | `SM_DATABASE_URL` unset or unreachable in the worker, not migrated, or a SQLite path with no file | Give the worker the web app's `SM_DATABASE_URL`; the defaults apply meanwhile. |
| A worker fails with "cannot be decrypted" but the web app works | the worker has a different `SM_SECRET_KEY` (or none and cannot read `host.secret_key`), often because it was started outside the project and found no `.env` | Give it the web app's secret, or set `SM_PROJECT_ROOT` to the project directory. |
| "'chat_api_key' is missing or invalid" | no key for a provider that needs one | Enter the key on the AI page. For a keyless local server, use `openai_compatible`. |
| "'chat_base_url' … needs the server's /v1 URL" | `openai_compatible` without a base URL | Set the base URL, ending in `/v1`. |
| "'embedding_provider' … not configured" | the embedding slot is empty | Configure **Embeddings**. |
| "'embedding_dim' … Set the vector width" | `embedding_dim` is `0` | Set **Vector dimension** to the model's output width. |
| "cannot be decrypted — SM_SECRET_KEY has changed" | secret rotated, or the host's in-code `secret_key` differs from the one used to save | Re-enter the keys. |
| Saving a key returns 500, log says `SM_SECRET_KEY is not set` | no secret anywhere | Set `SM_SECRET_KEY` (`make env`) and restart. |
| Every save fails with `chat_provider must be one of …` | a provider written by `set_setting.py` or the Settings screen outside the list (shown as "(unknown provider)") | Pick a real provider on the page. |
| Save says the page's security token is out of date (API: 403 "CSRF token missing or invalid") | API called without the token, or the session changed | Reload `/ai/`; scripted clients must send `X-CSRF-Token` with the `csrf_token` prop of the `/ai/` page. |
| Warning "stored unencrypted" | a key came from `set_setting.py` or the generic settings screen | Re-save it on the AI page. |
| Saved a change but some requests still use the old model | other workers have stale settings | Restart the app. |
| Setting `SM_AI_CHAT_MODEL` (or any `SM_AI_*`) has no effect | the module reads no environment variables | Change it on the AI page or with `set_setting.py`; see [Moving off `SM_AI_*` variables](#moving-off-sm_ai-variables). |
| **Test connection** OK, but a module still fails | the module's own call (prompt, output schema, model override) | That is the module's behaviour; check its logs. |
