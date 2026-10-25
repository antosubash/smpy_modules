import i18next from 'i18next';
import { afterEach, describe, expect, it, vi } from 'vitest';

import de from '../locales/de.json';
import { testSlot } from './api';
import { isQuotaExceeded, quotaMessage } from './quotaError';

/** Billing's 402 for a route metered with `RequiresAiRequest` (#99). */

vi.mock('@inertiajs/react', () => ({ router: { on: () => () => undefined } }));

const REFUSAL = {
  detail: 'quota_exceeded',
  meter: 'ai.requests',
  limit: 1,
  used: 1,
  requested: 1,
  resets_at: '2026-11-01T00:00:00+00:00',
};

/** The reset date as the message shows it: formatted in the runner's local
 * time zone, so the expectation holds under any TZ. */
const day = (iso: string, locale: string) =>
  new Intl.DateTimeFormat(locale, { dateStyle: 'medium' }).format(new Date(iso));

function flatten(node: Record<string, unknown>, prefix: string, out: Record<string, string>) {
  for (const [name, value] of Object.entries(node)) {
    const key = `${prefix}.${name}`;
    if (typeof value === 'string') out[key] = value;
    else flatten(value as Record<string, unknown>, key, out);
  }
  return out;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('quota_exceeded', () => {
  it('is recognised only as a 402 with that detail', () => {
    expect(isQuotaExceeded(402, REFUSAL)).toBe(true);
    expect(isQuotaExceeded(403, REFUSAL)).toBe(false);
    expect(isQuotaExceeded(402, { detail: 'plan_limit' })).toBe(false);
    expect(isQuotaExceeded(402, null)).toBe(false);
  });

  it('names the meter, the numbers and the reset date', () => {
    expect(quotaMessage(REFUSAL, 'en')).toBe(
      `AI requests limit reached (1/1); resets ${day(REFUSAL.resets_at, 'en')}.`,
    );
  });

  it('leaves the date out when there is none to show', () => {
    expect(quotaMessage({ ...REFUSAL, resets_at: null }, 'en')).toBe(
      'AI requests limit reached (1/1).',
    );
    expect(quotaMessage({ ...REFUSAL, resets_at: 'not a date' }, 'en_US')).toBe(
      'AI requests limit reached (1/1).',
    );
  });

  it('shows another meter by its key', () => {
    expect(quotaMessage({ ...REFUSAL, meter: 'ai.tokens' }, '')).toBe(
      `ai.tokens limit reached (1/1); resets ${day(REFUSAL.resets_at, 'en')}.`,
    );
  });

  it('speaks the console language', async () => {
    i18next.addResourceBundle('de', 'translation', flatten(de, 'ai', {}), true, true);
    await i18next.changeLanguage('de');
    try {
      expect(quotaMessage(REFUSAL)).toBe(
        `Grenze für KI-Anfragen erreicht (1/1); wird am ${day(REFUSAL.resets_at, 'de')} zurückgesetzt.`,
      );
    } finally {
      await i18next.changeLanguage('en');
    }
  });

  it('is the error a failed API call throws', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response(JSON.stringify(REFUSAL), { status: 402 })),
    );
    await expect(testSlot('chat')).rejects.toThrow(
      `AI requests limit reached (1/1); resets ${day(REFUSAL.resets_at, 'en')}.`,
    );
  });
});
