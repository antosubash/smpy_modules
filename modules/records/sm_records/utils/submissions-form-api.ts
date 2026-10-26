/**
 * The anonymous client of the website-submission API (#101), as the
 * `RecordForm` block calls it: `GET /api/records/submissions/{type}` for the
 * form definition and `POST …/{type}/submit` to send it.
 *
 * Separate from `utils/api.ts` for the reason `public-api.ts` gives: that one
 * talks to the session-gated admin API. This one has no session to send and
 * no CSRF token to read — the server checks `Content-Type: application/json`,
 * the `Origin` and the signed form token instead
 * (`endpoints/api/public_submissions_public.py`). The prefix is fixed on the
 * server (`PUBLIC_SUBMISSIONS_API_PREFIX`), so it is a constant here too.
 *
 * Nothing here trusts what the page JSON says: the block names a type key,
 * and everything about the form — its fields, consent text, CAPTCHA —
 * comes from the live definition.
 */

export const SUBMISSIONS_API_PREFIX = '/api/records/submissions';

export type SubmissionChoice = { value: string; label: string };

export type SubmissionField = {
  key: string;
  type: string;
  label: string;
  help: string | null;
  required: boolean;
  choices: SubmissionChoice[];
  constraints: Record<string, unknown>;
  default: unknown;
};

export type SubmissionDefinition = {
  kind: 'form' | 'subscription';
  schema_version: number;
  fields: SubmissionField[];
  consent: { required: boolean; text: string } | null;
  token: string;
  captcha: { provider: 'turnstile' | 'hcaptcha'; site_key: string } | null;
  /** How old `token` must be before the server accepts it. */
  min_fill_seconds?: number;
};

export type DefinitionResult =
  | { status: 'ready'; definition: SubmissionDefinition }
  | { status: 'unavailable' }
  | { status: 'error' };

export type FieldError = { field: string; message: string };

export type SubmitBody = {
  data: Record<string, unknown>;
  token: string;
  hp: string;
  consent: boolean;
  block?: string;
  locale?: string;
  captcha_response?: string;
};

export type SubmitResult =
  | { ok: true }
  | {
      ok: false;
      status: number;
      /** The server's stable snake_case refusal code; `null` for the shared
       *  404 (which carries none) or a body that is not the envelope. */
      code: string | null;
      errors: FieldError[];
      definition: SubmissionDefinition | null;
      /** Seconds, from `Retry-After` on a 429. */
      retryAfter: number | null;
    };

function formPath(typeKey: string): string {
  return `${SUBMISSIONS_API_PREFIX}/${encodeURIComponent(typeKey)}`;
}

/** The form as the type defines it right now. Never cached: a definition
 *  carries a fresh signed token, and an edited field shows on the next view. */
export async function fetchDefinition(
  typeKey: string,
  locale: string | undefined,
  signal?: AbortSignal,
): Promise<DefinitionResult> {
  const query = locale ? `?locale=${encodeURIComponent(locale)}` : '';
  try {
    const response = await fetch(`${formPath(typeKey)}${query}`, {
      credentials: 'same-origin',
      headers: { Accept: 'application/json' },
      cache: 'no-store',
      signal,
    });
    if (response.status === 404) return { status: 'unavailable' };
    if (!response.ok) return { status: 'error' };
    return { status: 'ready', definition: (await response.json()) as SubmissionDefinition };
  } catch (error) {
    if ((error as { name?: string })?.name === 'AbortError') throw error;
    return { status: 'error' };
  }
}

function retryAfter(response: Response): number | null {
  const raw = response.headers.get('Retry-After');
  const seconds = raw === null ? Number.NaN : Number.parseInt(raw, 10);
  return Number.isFinite(seconds) && seconds >= 0 ? seconds : null;
}

/** Send a filled form. A network failure throws; every HTTP answer resolves. */
export async function submitForm(typeKey: string, body: SubmitBody): Promise<SubmitResult> {
  const response = await fetch(`${formPath(typeKey)}/submit`, {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
    body: JSON.stringify(body),
  });
  if (response.ok) return { ok: true };
  const payload = (await response.json().catch(() => ({}))) as {
    code?: unknown;
    errors?: unknown;
    definition?: unknown;
  };
  const errors = Array.isArray(payload.errors)
    ? (payload.errors as FieldError[]).filter((item) => typeof item?.field === 'string')
    : [];
  return {
    ok: false,
    status: response.status,
    code: typeof payload.code === 'string' ? payload.code : null,
    errors,
    definition:
      payload.definition && typeof payload.definition === 'object'
        ? (payload.definition as SubmissionDefinition)
        : null,
    retryAfter: retryAfter(response),
  };
}
