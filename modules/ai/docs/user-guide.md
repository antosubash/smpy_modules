# AI user guide

The AI settings page is for platform administrators. It appears as **AI** in
the sidebar's **Administration** group for users with the `admin` role. The
page lives at `/ai/`. The page and its API both require the `ai.manage`
permission.

The page is titled **AI**, with the description "Connection settings for the
chat and embedding providers every module shares." It shows two cards and one
**Save** button below them. The page configures connections only. What the AI
is used for (summaries, search, and so on) is up to the modules that use it.

## The two slots

| Card | Description on the page | Required? |
|---|---|---|
| **Chat** | "The model modules use for text generation." | Yes. Modules that generate text fail until it works. |
| **Embeddings** | "Optional second endpoint for vector embeddings." | No. It starts as **Not configured**, and only modules that need vectors (search, retrieval) use it. |

The two slots are separate because many deployments run chat and embeddings
on different endpoints, for example two vLLM processes on one GPU host.

## Fields

Both cards have the same fields. **Embeddings** adds **Vector dimension**.

| Field | What it means |
|---|---|
| **Provider** | Who serves the model. Chat offers `anthropic`, `openai`, `google` and `openai_compatible`. Embeddings offers `openai`, `google` and `openai_compatible`, plus **Not configured**. Anthropic has no embeddings API, so it isn't offered there. |
| **Model** | The model name exactly as the provider spells it, *without* a provider prefix: `claude-opus-5`, not `anthropic:claude-opus-5`. The placeholder says "model name, no provider prefix". Chat's model can't be saved blank. |
| **Base URL** | Labelled **Base URL (required)** when the provider is `openai_compatible`, with the placeholder `http://your-server:8000/v1`: point it at the server's `/v1` URL. For other providers it is **Base URL (optional override)** (placeholder "provider default"). Leave it blank unless you route through a proxy or gateway. |
| **API key** | The provider's key. The field never shows a stored key. Its placeholder says **saved — leave blank to keep** when a key is stored, or **not set** when none is. For `openai_compatible` the key may stay empty (vLLM, Ollama and LM Studio usually don't check it). |
| **Vector dimension** (Embeddings only) | The width of the vectors the embedding model produces, e.g. `1536`. The page reminds you: "Vector stores fix collection width to this — changing it means re-indexing." `0` means not set. |

### `openai_compatible`

Use this provider for any server that speaks the OpenAI API: vLLM, Ollama, LM
Studio, or a self-hosted gateway. It needs a **Base URL**. If you leave the
**API key** empty, the module sends a placeholder key, because the OpenAI
protocol requires one.

### An unknown provider

A provider seeded from the environment can hold a value that isn't in the list,
for example a typo. The select then shows it as "`<value>` (unknown provider)",
and every save fails until you pick a real provider.

## Keeping, replacing and clearing a key

- **Keep it:** leave **API key** blank. The stored key is untouched.
- **Replace it:** type the new key and **Save**. Leading and trailing spaces
  are trimmed (a key copied with a trailing newline would otherwise fail at
  the provider).
- **Remove it:** click **Clear** next to the field (shown only while a key is
  stored). The button turns into **Will clear**, the field is disabled, and the
  key is deleted on **Save**. Click **Will clear** again to cancel.

Keys are encrypted before they are stored, and the page and API never send a
stored key back. They only report whether one is set.

## Saving

**Save** writes both cards at once. On success the page shows "AI settings
saved" and reloads the values from the server. On failure it shows "Save
failed: …" with the reason, e.g. `chat_provider: Value error, chat_provider
must be one of …`.

A save applies at once to the server process that handled it. On a deployment
with several worker processes, see [operations.md](operations.md#multiple-workers).

## Test connection

Each card has a **Test connection** button. It makes one small real call
through that slot's *saved* settings. Chat sends the prompt "Reply with the
single word: ok"; Embeddings embeds the same text.

- While a card has unsaved edits, its button is disabled and the card says
  "Save your changes first — the test runs against saved settings."
- Success shows **OK — `<model>` (`<n>` ms)**.
- Failure shows the error message in red: a missing model, a missing key, a
  key that can no longer be decrypted, a wrong URL, a rejected key, or
  "Timed out after 30s." A failed test is a result, not an error page.
- Saving clears earlier test results, since they described the old
  configuration.

Run **Test connection** after every change. The modules that use AI only
discover a bad key or URL when they make their own call.

## "The stored key … cannot be decrypted"

This message, in a test result or from a module, means the server's
`SM_SECRET_KEY` changed after the key was saved. Type the key again and
**Save**. See [operations.md](operations.md#secret-key-rotation).
