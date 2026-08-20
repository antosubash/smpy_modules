/** Client for the AI settings API. */

export type AiSettingsOut = {
  chat_providers: string[];
  embedding_providers: string[];
  chat_provider: string;
  chat_model: string;
  chat_base_url: string;
  has_chat_api_key: boolean;
  embedding_provider: string;
  embedding_model: string;
  embedding_base_url: string;
  has_embedding_api_key: boolean;
  embedding_dim: number;
};

export type TestResult = {
  ok: boolean;
  model: string;
  latency_ms: number;
  error: string;
};

export type SlotValues = {
  provider: string;
  model: string;
  base_url: string;
  api_key: string; // "" = keep stored key
  clear_key: boolean;
  dim?: number;
};

const BASE = '/api/ai';
const CSRF_COOKIE = 'sm_ai_csrf';

/** The admin view mints the token into the session; middleware mirrors it to
 * this JS-readable cookie. Tolerant when absent (e.g. session not mounted) —
 * the server skips enforcement in exactly that case. */
function csrfHeader(): Record<string, string> {
  const match = document.cookie.match(new RegExp(`(?:^|; )${CSRF_COOKIE}=([^;]*)`));
  return match ? { 'X-CSRF-Token': decodeURIComponent(match[1]) } : {};
}

/** Turn a failed response into something worth showing a person — our own
 * JSON `detail` when present, the status line otherwise (never raw HTML).
 * FastAPI 422s carry a Pydantic error array; render it as "field: message"
 * lines instead of dumping the serialized structure into a toast. */
async function errorFrom(response: Response): Promise<Error> {
  const text = await response.text();
  try {
    const detail = (JSON.parse(text) as { detail?: unknown }).detail;
    if (typeof detail === 'string') return new Error(detail);
    if (Array.isArray(detail)) {
      const lines = detail
        .map((item) => {
          const entry = item as { loc?: unknown[]; msg?: string };
          const field = Array.isArray(entry.loc) ? String(entry.loc[entry.loc.length - 1]) : '';
          return entry.msg ? (field ? `${field}: ${entry.msg}` : entry.msg) : '';
        })
        .filter(Boolean);
      if (lines.length) return new Error(lines.join('; '));
    }
    if (detail) return new Error(JSON.stringify(detail));
  } catch {
    // Not JSON — fall through to the status line rather than echo markup.
  }
  return new Error(`Request failed (${response.status} ${response.statusText})`.trim());
}

async function checkedJson<T>(response: Response): Promise<T> {
  if (!response.ok) throw await errorFrom(response);
  return (await response.json()) as T;
}

export async function loadSettings(): Promise<AiSettingsOut> {
  return checkedJson(await fetch(`${BASE}/settings`, { credentials: 'same-origin' }));
}

export async function saveSettings(
  chat: SlotValues,
  embedding: SlotValues,
): Promise<AiSettingsOut> {
  const payload: Record<string, unknown> = {
    chat_provider: chat.provider,
    chat_model: chat.model,
    chat_base_url: chat.base_url,
    embedding_provider: embedding.provider,
    embedding_model: embedding.model,
    embedding_base_url: embedding.base_url,
    embedding_dim: embedding.dim ?? 0,
  };
  if (chat.api_key) payload.chat_api_key = chat.api_key;
  if (chat.clear_key) payload.clear_chat_api_key = true;
  if (embedding.api_key) payload.embedding_api_key = embedding.api_key;
  if (embedding.clear_key) payload.clear_embedding_api_key = true;
  return checkedJson(
    await fetch(`${BASE}/settings`, {
      method: 'PUT',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', ...csrfHeader() },
      body: JSON.stringify(payload),
    }),
  );
}

export async function testSlot(slot: 'chat' | 'embedding'): Promise<TestResult> {
  return checkedJson(
    await fetch(`${BASE}/test`, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', ...csrfHeader() },
      body: JSON.stringify({ slot }),
    }),
  );
}
