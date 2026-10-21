# simple_module_ai

AI base module for [SimpleModule](https://docs.py.simplemodule.dev) apps: one
provider-configurable service layer (chat + embeddings) that every other
module shares, with DB-backed settings, encrypted keys and an admin page.

The module owns **connection** configuration — provider, endpoint, key, model
name. Consuming modules own **behaviour** — agents, prompts, temperature,
retries, streaming.

**Full documentation** lives in [`docs/`](docs/index.md):
[user guide](docs/user-guide.md) (the AI settings page),
[API reference](docs/api-reference.md) (the `sm_ai.contracts` API and the HTTP
routes), [operations](docs/operations.md) (install, settings, key rotation,
troubleshooting) and
[architecture](docs/architecture.md).

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

embedder = resolve_embedder()  # raises AiNotConfiguredError until the
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

Configure at `/ai/` (permission `ai.manage`), on the Settings screen, or
headlessly with `scripts/set_setting.py sm_ai <field> <value>`. The module
reads no `SM_AI_*` environment variables: settings live in the database at
SYSTEM scope, so every tenant shares one provider configuration and one API
key per slot. API keys are encrypted at
rest with a key derived from `SM_SECRET_KEY` — rotating that secret means
re-entering provider keys (the old ciphertexts surface as unreadable). A
settings save hot-reloads the worker that handled it; other workers pick
the change up on restart. Celery workers and scripts that never run the web
host read the same settings themselves, re-reading at most once a minute.

## Routes

| Route | Purpose |
|---|---|
| `GET /ai/` | admin settings page |
| `GET`/`PUT /api/ai/settings` | read (secrets masked) / update |
| `POST /api/ai/test` | probe the chat or embedding slot |
| `POST /api/ai/models` | list the model ids the slot's saved endpoint serves (first 500, sorted) |

Writes require the framework's `X-CSRF-Token` header bound to the session (the
admin page sends it automatically; it is shared as the `csrf_token` prop).
