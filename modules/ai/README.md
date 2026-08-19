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
from sm_ai.contracts import AiNotConfiguredError, resolve_model, resolve_embedder

agent = Agent(instructions="...", output_type=MySchema)
result = await agent.run(text, model=resolve_model())

embedder = resolve_embedder()          # raises AiNotConfiguredError until the
result = await embedder.embed_documents(chunks)  # embedding slot is set up
```

`resolve_model(model_name=...)` overrides the configured model name for
same-endpoint multi-model setups. `embedding_dim()` returns the configured
vector width. All errors subclass `AiError`.

> The import package is `sm_ai`, not `ai` — the bare name belongs to another
> PyPI project and would collide in hosts that install it.

## Settings

Two slots — chat and embeddings — each with provider (`anthropic`, `openai`,
`google`, `openai_compatible`), model, base URL and API key. The
`openai_compatible` provider covers vLLM, Ollama and LM Studio (base URL
required; a blank key is replaced by a protocol-satisfying placeholder).

Configure at `/ai/` (permission `ai.manage`) or seed via `SM_AI_*` env vars
(e.g. `SM_AI_CHAT_MODEL`); DB values win over env. API keys are encrypted at
rest with a key derived from `SM_SECRET_KEY` — rotating that secret means
re-entering provider keys, and the derived Fernet is built once per process,
so a rotation takes effect on restart. A settings save hot-reloads the
worker that handled it; other workers pick the change up on restart.

## Routes

| Route | Purpose |
|---|---|
| `GET /ai/` | admin settings page |
| `GET`/`PUT /api/ai/settings` | read (secrets masked) / update |
| `POST /api/ai/test` | probe the chat or embedding slot |

Writes require an `X-CSRF-Token` header bound to the session (the admin page
sends it automatically; the token is mirrored to the `sm_ai_csrf` cookie).
