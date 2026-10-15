# AI documentation

`simple_module_ai` gives every module in a SimpleModule app one shared place to
configure its AI provider. An administrator sets up two **slots** — **chat**
(text generation) and **embeddings** (vectors) — by choosing a provider, a
model, an optional base URL and an API key. Other modules then ask the AI
module for a ready Pydantic AI model or embedder, and never handle keys or
endpoints themselves.

The module does no AI work of its own. It resolves *connections*: provider,
endpoint, key and model name. The consuming modules own *behaviour*: agents,
prompts, temperature, retries and streaming.

Start with the document that matches what you are trying to do.

## Who should read what

| You are | Read |
|---|---|
| An administrator connecting the app to a provider | [user-guide.md](user-guide.md) |
| A developer calling the settings API, or using AI from another module | [api-reference.md](api-reference.md) |
| An operator installing it, seeding it from the environment, or answering "why does the AI say it isn't configured?" | [operations.md](operations.md) |
| A developer changing the module or building a module on top of it | [architecture.md](architecture.md) |

### [user-guide.md](user-guide.md) — for administrators

The **AI** settings page, using the exact UI labels: what each field in the
**Chat** and **Embeddings** cards means, how a stored API key is kept,
replaced or cleared, and how **Test connection** reports success and failure.

### [api-reference.md](api-reference.md) — for integrators

The Python contract other modules import (`resolve_model`,
`resolve_embedder`, `embedding_dim` and the errors), then the three HTTP routes
under `/api/ai`: permission, CSRF, request and response shapes, and what each
failure looks like.

### [operations.md](operations.md) — for operators

Installing the module, every setting and its default, seeding settings from
`SM_AI_*` environment variables (and when the database wins), how keys are
encrypted, what rotating `SM_SECRET_KEY` does, multi-worker behaviour, and a
troubleshooting table that starts from the symptom.

### [architecture.md](architecture.md) — for maintainers

Why the module has no tables, how settings travel from the store to a
consumer's call, the validation rules each slot passes through, the crypto
format, the CSRF channel, and a worked example of consuming the module from
another module.

## The module in one paragraph

The AI module stores its configuration in the framework's shared settings
store, so it has no tables and no migrations. A field the database does not
hold falls back to an `SM_AI_*` environment variable or the root `.env`, then
to its built-in default. API keys entered on the settings page are encrypted
with a key derived from `SM_SECRET_KEY` and stored as `enc:v1:…`. Consumers
call `sm_ai.contracts.resolve_model()` or `resolve_embedder()`, which build a
fresh Pydantic AI object from the current settings on every call. They make no
network request; a wrong key or URL fails in the consumer's own call. The only
time the module itself calls a provider is the **Test connection** button.
Every route requires the `ai.manage` permission.
