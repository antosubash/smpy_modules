# AI operations

## Install

1. Add the package to the host. Modules use version ranges; the host pins the
   framework exactly:

   ```toml
   dependencies = [
       "simple_module_hosting==0.0.38",
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
| `chat_base_url` | `""` | required for `openai_compatible` (a save without one is a `422`); an optional proxy/gateway override otherwise |
| `chat_api_key` | `""` | stored `enc:v2:…` when saved through the AI page |
| `embedding_provider` | `""` | `""` = not configured; `openai`, `google`, `openai_compatible` |
| `embedding_model` | `""` | |
| `embedding_base_url` | `""` | as for chat |
| `embedding_api_key` | `""` | as for chat |
| `embedding_dim` | `0` | vector width; `0` = not set. A negative stored value (only `set_setting.py` can write one) is read as `0` with a warning |
| `allow_private_base_url` | `false` | allow a base URL on a private or local address (Ollama, an in-network gateway); see [Base URLs and the network](#base-urls-and-the-network). Changing it on the AI page needs `settings.edit` |

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
`enc:v2:<Fernet token>`. The Fernet key is HKDF-SHA256 of the app's secret with
the info string `sm_ai:settings` (so no other module's key opens it), URL-safe
base64-encoded. 0.0.15 wrote `enc:v1:` (the SHA-256 of the secret); that is
still read, with one warning per field, until 0.1.0. The secret is the running app's `secret_key` (which a
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
| `enc:v2:…` that `SM_SECRET_KEY` or a key in `SM_SECRET_KEY_PREVIOUS` opens | the key |
| `enc:v1:…` that one of them opens | the key; a warning is logged once per field |
| `enc:…` that none opens, or another version | `AiKeyUnreadableError` — never a silent fallback |
| no prefix | used as plaintext; a warning is logged once per field |

### Secret key rotation

Rotate with `SM_SECRET_KEY_PREVIOUS` and `scripts/reencrypt_secrets.py`, as
[docs/secret-key-rotation.md](../../../docs/secret-key-rotation.md) describes:
with the old key in `SM_SECRET_KEY_PREVIOUS` the stored keys keep working, and
the script re-encrypts them under the new one. Changing `SM_SECRET_KEY`
*without* keeping the old key makes every stored key unreadable. Nothing breaks
at boot, but each consumer's `resolve_*` call and each **Test connection**
fails with "The stored key '…' cannot be decrypted with SM_SECRET_KEY or any
key in SM_SECRET_KEY_PREVIOUS …"; add the old key back, or re-enter the chat
and embedding keys on the AI page.

## Base URLs and the network

A base URL receives the slot's API key in every request, so the module checks
where it points (#347). With `allow_private_base_url` off (the default):

- **On save** (`PUT /api/ai/settings`) the URL must be `http(s)` without
  userinfo, and its host is resolved: every address must be public. Loopback,
  private (RFC 1918, IPv6 ULA), link-local (including `169.254.169.254`),
  CGNAT, multicast, unspecified and reserved addresses are refused, and so is
  an IPv4-mapped, NAT64, 6to4 or Teredo form of one. Any port is allowed. The
  rules are images' URL guard, copied to `sm_ai.core.url_safety` (a parity
  test keeps the copies equal).
- **At client build** (`resolve_model`, `resolve_embedder`, the probes) the
  scheme is checked again and a private IP literal is refused, without DNS:
  the build is synchronous and runs inside async code.
- **At connect** the SDK's HTTP client is the module's pinned client
  (`sm_ai.connections.pinned`): each request resolves the
  host again, refuses it unless every address is public, and connects to the
  validated address while sending the name as `Host` and TLS SNI (the
  certificate is verified against the name). A DNS answer that changes after
  the check (rebinding) cannot redirect the key.

Every SDK the module uses accepts that client, so all of them are pinned:
OpenAI and `openai_compatible` (`AsyncOpenAI(http_client=…)`, through
pydantic-ai's `OpenAIProvider`), Anthropic (`AsyncAnthropic(http_client=…)`,
`AnthropicProvider`) and Google (`google-genai`'s
`HttpOptions(httpx_async_client=…)`, `GoogleProvider`), for chat, embeddings
and model listing alike. A slot without a base URL uses the provider's own
endpoint and the SDK's own client; it is not checked.

What remains:

- Neither client a base URL gets follows redirects (the SDKs' default clients
  do, and a followed hop would carry the key's header to another host): a base
  URL that answers `301`/`307`, such as `http://` to `https://` or a missing
  trailing slash, fails with the `other` code (a 3xx is not an `http_error`) until the URL is
  the final one. That holds with `allow_private_base_url` on too.
- One client is kept per event loop and base-URL origin
  (`sm_ai.connections.clients`, at most 8 origins per loop; a finished loop's
  clients go with it), shared by every model built on that loop. The pinned
  client keeps no idle connections, so each call to a custom base URL opens a
  new connection; model listing uses a client of its own and closes it.
- The pinned client ignores `HTTPS_PROXY`/`HTTP_PROXY`: a proxy would resolve
  the name itself. A deployment that must reach a public gateway through an
  egress proxy turns on `allow_private_base_url`: its client honours the proxy
  variables and checks no address.
- With `allow_private_base_url` on, only the scheme rule applies: whoever
  holds `ai.manage` can then point a slot, and its key, at any address the
  server reaches. That is why turning it on needs `settings.edit`.
- `scripts/set_setting.py` writes a base URL without the save check; the
  connect-time check still applies to it.

**Upgrading from 0.0.15:** a slot whose base URL is private (a local Ollama or
vLLM, `http://vllm:8000/v1` on a container network) stops working: calls fail
and **Test connection** says the base URL was refused. Turn on **Allow private
base URLs** on the AI page (needs `settings.edit`), or
`python scripts/set_setting.py sm_ai allow_private_base_url true`.

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
restart; `sm_ai.core.services.invalidate()` forces a re-read. If the database
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
| Save fails with "this URL points at a private or local address", or calls fail with `AiBaseUrlRefusedError` / **Test connection** says the base URL was refused | a base URL on a local or private network while `allow_private_base_url` is off (#347) | Turn on **Allow private base URLs** (needs `settings.edit`); see [Base URLs and the network](#base-urls-and-the-network). |
| Save fails with "the host of this URL could not be resolved" | a typo, or a name only another network resolves | Fix the name; a name that resolves only to private addresses also needs **Allow private base URLs**. |
| Every save fails with `chat_base_url: a base URL is required …` | a slot is stored as `openai_compatible` with no URL (possible before #164) | Enter the server's base URL on that card. |
| "'embedding_dim' … Set the vector width" | `embedding_dim` is `0` | Set **Vector dimension** to the model's output width. |
| "cannot be decrypted with SM_SECRET_KEY or any key in SM_SECRET_KEY_PREVIOUS" | secret rotated without keeping the old one, or the host's in-code `secret_key` differs from the one used to save | Add the old key to `SM_SECRET_KEY_PREVIOUS`, or re-enter the keys. |
| Saving a key returns 500, log says `SM_SECRET_KEY is not set` | no secret anywhere | Set `SM_SECRET_KEY` (`make env`) and restart. |
| Every save fails with `chat_provider must be one of …` | a provider written by `set_setting.py` outside the list (shown as "(unknown provider)") | Pick a real provider on the page. |
| Save says the page's security token is out of date (API: 403 "CSRF token missing or invalid") | API called without the token, or the session changed | Reload `/ai/`; scripted clients must send `X-CSRF-Token` with the `csrf_token` prop of the `/ai/` page. |
| Warning "stored unencrypted" | a key came from `set_setting.py` (or, before #164, the generic settings screen) | Re-save it on the AI page. |
| Saved a change but some requests still use the old model | other workers have stale settings | Restart the app. |
| Setting `SM_AI_CHAT_MODEL` (or any `SM_AI_*`) has no effect | the module reads no environment variables | Change it on the AI page or with `set_setting.py`; see [Moving off `SM_AI_*` variables](#moving-off-sm_ai-variables). |
| A module's AI feature answers 402 "AI requests limit reached" | the organisation used its plan's `ai.requests` allowance for the period (billing installed) | Billing → Usage: raise the plan's limit, or credit with **Adjust**. The settings page's own **Test connection** is not metered. |
| **Test connection** OK, but a module still fails | the module's own call (prompt, output schema, model override) | That is the module's behaviour; check its logs. |
