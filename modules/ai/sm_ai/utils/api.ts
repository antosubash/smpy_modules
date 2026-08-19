/** Client for the AI settings API. */

export type AiSettingsOut = {
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

/** Turn a failed response into something worth showing a person — our own
 * JSON `detail` when present, the status line otherwise (never raw HTML). */
async function errorFrom(response: Response): Promise<Error> {
  const text = await response.text();
  try {
    const detail = (JSON.parse(text) as { detail?: unknown }).detail;
    if (typeof detail === 'string') return new Error(detail);
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
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    }),
  );
}

export async function testSlot(slot: 'chat' | 'embedding'): Promise<TestResult> {
  return checkedJson(
    await fetch(`${BASE}/test`, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ slot }),
    }),
  );
}
