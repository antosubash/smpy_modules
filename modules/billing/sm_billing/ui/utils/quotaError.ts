/**
 * The message for a 402 `quota_exceeded`, which `RequiresQuota` and
 * `holding()` answer with `{meter, limit, used, requested, resets_at}`.
 *
 * Shared through `describeError`, so every billing call shows it the same
 * way. A consumer module can copy this helper (it needs only its own
 * catalogue's two strings): billing is never imported at runtime.
 */

import i18next from 'i18next';
import { formatDate } from './format';
import { keys, translate } from './i18n';

export function quotaMessage(body: Record<string, unknown>, locale?: string): string {
  const params = {
    meter: String(body.meter ?? ''),
    used: body.used,
    limit: body.limit,
  };
  const resets = typeof body.resets_at === 'string' ? body.resets_at : '';
  if (!resets) return translate(keys.billing.errors.quota_exceeded_gauge, params);
  // The console's language, not the browser's (#189).
  const date = formatDate(resets, locale ?? i18next.language);
  return translate(keys.billing.errors.quota_exceeded, { ...params, date });
}
