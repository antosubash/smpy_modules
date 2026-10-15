# AI: model discovery and quieter probes

Status: approved 2026-10-15 (next-phase plan, Phase 3).

Phase 3 of the plan hardens the `ai` module. Of the v2 candidates the original
spec lists (`2026-08-19-ai-module-design.md`, *Scope*), this does **model
auto-discovery**; i18n shipped earlier. Request timeouts, vision helpers and
per-module model overrides each change what consumers see and stay out.

## 1. Model discovery

Typing a model name blind is the commonest way to save a slot that fails its
test: a vLLM server serves whatever it was started with, and hosted providers
rename models every few months.

- **API.** `POST /api/ai/models` with `{"slot": "chat" | "embedding"}`,
  `ai.manage`, CSRF like the other writes. Returns
  `{"ok": bool, "models": [str], "error": str}`, sorted and de-duplicated. A failure
  of any kind is `ok: false` with the message, never a 500. That is the same
  contract as `POST /test`.
- **Saved settings, like the test.** It uses the slot's *saved* provider, base
  URL and key, so the form shows "Save first" while dirty, exactly as the test
  button does. Sending an unsaved key in the request would let a page with a
  bug send the plaintext key to an endpoint the admin hasn't saved.
- **Per provider**, through the SDK pydantic-ai already installs (no new
  dependency):
  - `openai` / `openai_compatible`: `AsyncOpenAI(...).models.list()`.
  - `anthropic`: `AsyncAnthropic(...).models.list()`.
  - `google`: `genai.Client(...).aio.models.list()`.
  - Each honours the slot's base URL and decrypted key. It shares the
    validation path with `resolve._slot_inputs`, minus the model-name
    requirement, since a missing model name is the reason to ask.
- **Bounded.** Wrapped in the same `TEST_TIMEOUT_SECONDS` and capped at 500 names.
- **UI.** Each slot card gets a **Load models** button beside **Test
  connection**. On success the model input gets a `<datalist>` of the names, so
  it stays free text, because a model a server doesn't list (an alias) must
  still be enterable. The count shows inline, and a failure shows its message.

## 2. Quieter probe logging

`POST /test` logged every failure with a traceback, so an unreachable server
filled the log with stack frames. A connection error, timeout or provider
HTTP error (`openai.APIError`, `anthropic.APIError`, google `APIError`,
`httpx.HTTPError`, pydantic-ai `ModelAPIError`, which wraps a refused connection) now logs one warning line.
Anything else keeps the traceback, which is how a real code defect stays
distinguishable from a configuration problem.

## Testing

pytest with the SDK clients stubbed covers each provider branch, the
not-configured path, the timeout, the cap and sorting, the permission and
CSRF, and both logging paths. vitest covers the card's button state and the
datalist. The e2e spec `ai-settings` gets a failing-load case: an
openai_compatible slot pointed at a closed port shows the error inline.
