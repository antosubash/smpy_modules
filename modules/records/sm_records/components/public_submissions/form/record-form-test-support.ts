/**
 * Shared by the `RecordForm` render and submit tests (#101): a definition
 * builder, a scripted `fetch`, and the few interactions a visitor performs.
 * Not shipped (`*-test-support.ts` is excluded from the wheel).
 */

import { vi } from 'vitest';

import { click, type Mounted, settle, setValue } from '../../../test-dom';
import type { SubmissionDefinition } from '../../../utils/submissions-form-api';

export function field(key: string, type: string, extra: Record<string, unknown> = {}) {
  return {
    key,
    type,
    label: `${key} label`,
    help: null,
    required: false,
    choices: [],
    constraints: {},
    default: null,
    ...extra,
  };
}

export function definition(overrides: Partial<SubmissionDefinition> = {}): SubmissionDefinition {
  return {
    kind: 'form',
    schema_version: 1,
    fields: [
      field('name', 'text', { required: true }),
      field('email', 'email', { required: true }),
      field('age', 'integer'),
      field('message', 'longtext'),
      field('topic', 'select', { choices: [{ value: 'sales', label: 'Sales' }] }),
      field('news', 'boolean'),
    ],
    consent: { required: true, text: 'I agree to be contacted.' },
    token: 'tok-1',
    captcha: null,
    ...overrides,
  } as SubmissionDefinition;
}

type Reply = { status: number; body?: unknown; headers?: Record<string, string> };

/** A `fetch` that answers in order and records each request. */
export function server(...replies: Reply[]) {
  const calls: { url: string; init?: RequestInit }[] = [];
  const fetch = vi.fn(async (url: string, init?: RequestInit) => {
    calls.push({ url, init });
    const next = replies.shift() ?? { status: 500 };
    return new Response(next.body === undefined ? null : JSON.stringify(next.body), {
      status: next.status,
      headers: next.headers,
    });
  });
  vi.stubGlobal('fetch', fetch);
  return calls;
}

export const input = (view: Mounted, key: string) =>
  view.find<HTMLInputElement>(
    `[data-testid="records-form-field-${key}"] input, [data-testid="records-form-field-${key}"] textarea, [data-testid="records-form-field-${key}"] select`,
  );

export async function fill(view: Mounted) {
  await setValue(input(view, 'name') as HTMLInputElement, 'Ada');
  await setValue(input(view, 'email') as HTMLInputElement, 'ada@example.org');
  await setValue(input(view, 'age') as HTMLInputElement, '36');
  await click(view.find('[data-testid="records-form-consent"] input'));
}

export async function send(view: Mounted) {
  await click(view.find('button[type="submit"]'));
  await settle();
  await settle();
}
