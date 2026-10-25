/**
 * The message for billing's 402 `quota_exceeded`, which a route guarded by
 * `RequiresAiRequest` answers once the organisation's `ai.requests` allowance
 * for the period is used: `{detail, meter, limit, used, requested, resets_at}`.
 *
 * A copy of billing's `utils/quotaError.ts` over this module's own catalogue:
 * billing is optional for ai and is never imported, at runtime or here. This
 * module's API client (`api.ts`) decodes every failed call through it; a
 * consumer's chat UI that calls a metered route can do the same.
 */

import i18next from 'i18next';

import { keys, translate } from './i18n';

export const QUOTA_EXCEEDED = 'quota_exceeded';
const AI_REQUESTS = 'ai.requests';

/** Whether a failed response's status and JSON body are billing's quota refusal. */
export function isQuotaExceeded(status: number, body: unknown): boolean {
  return (
    status === 402 &&
    typeof body === 'object' &&
    body !== null &&
    (body as { detail?: unknown }).detail === QUOTA_EXCEEDED
  );
}

/** `locale` as a tag `Intl` accepts; a blank or malformed one is English. */
function intlLocale(locale: string | null | undefined): string {
  const tag = (locale ?? '').trim().replace(/_/g, '-');
  try {
    return (tag && Intl.getCanonicalLocales(tag)[0]) || 'en';
  } catch {
    return 'en';
  }
}

function resetDate(iso: unknown, locale: string | undefined): string {
  if (typeof iso !== 'string' || !iso) return '';
  const when = new Date(iso);
  if (Number.isNaN(when.getTime())) return '';
  return new Intl.DateTimeFormat(intlLocale(locale), { dateStyle: 'medium' }).format(when);
}

export function quotaMessage(body: Record<string, unknown>, locale?: string): string {
  const meter = String(body.meter ?? '');
  const params = {
    meter: meter === AI_REQUESTS ? translate(keys.ai.meters.requests) : meter,
    used: body.used,
    limit: body.limit,
  };
  // The console's language, not the browser's.
  const date = resetDate(body.resets_at, locale ?? i18next.language);
  if (!date) return translate(keys.ai.quota.exceeded_no_reset, params);
  return translate(keys.ai.quota.exceeded, { ...params, date });
}
