/** Formatting for the usage card and the admin usage screen. */

import { keys, translate } from './i18n';
import { intlLocale } from './locale';
import type { HoldStatus, MeterUnit, UsageKind } from './types';

const BYTE_UNITS = ['byte', 'kilobyte', 'megabyte', 'gigabyte', 'terabyte', 'petabyte'] as const;

/** Bytes in decimal (SI) units — `1.5 MB` — in the console's locale. */
export function formatBytes(value: number, locale: string | undefined): string {
  let scaled = Math.abs(value);
  let step = 0;
  while (scaled >= 1000 && step < BYTE_UNITS.length - 1) {
    scaled /= 1000;
    step += 1;
  }
  return new Intl.NumberFormat(intlLocale(locale), {
    style: 'unit',
    unit: BYTE_UNITS[step],
    unitDisplay: 'short',
    maximumFractionDigits: step === 0 ? 0 : 1,
  }).format(value < 0 ? -scaled : scaled);
}

const UNIT_KEY: Record<MeterUnit, string> = {
  count: keys.billing.units.count,
  bytes: keys.billing.units.bytes,
  tokens: keys.billing.units.tokens,
  ms: keys.billing.units.ms,
};

/** A quantity in its meter's unit: `1,200`, `1.2 MB`, `5,000 tokens`, `350 ms`. */
export function formatQuantity(value: number, unit: string, locale: string | undefined): string {
  if (unit === 'bytes') return formatBytes(value, locale);
  const number = new Intl.NumberFormat(intlLocale(locale)).format(value);
  return translate(UNIT_KEY[unit as MeterUnit] ?? UNIT_KEY.count, { value: number });
}

/**
 * A meter's name. `label_key` lives in the *consumer's* catalogue, which
 * billing never sees: a key that does not resolve shows the meter key, not
 * the dotted label key.
 */
export function meterLabel(labelKey: string, meter: string): string {
  return labelKey ? translate(labelKey, { defaultValue: meter }) : meter;
}

/** `used / limit` in percent, as the server computes it; `null` when unlimited. */
export function percentOf(used: number, limit: number | null): number | null {
  if (limit === null) return null;
  if (limit <= 0) return used > 0 ? 100 : 0;
  return Math.round((used * 1000) / limit) / 10;
}

export type UsageTone = 'normal' | 'warning' | 'over';

/** At or above 90% is a warning; at or past the limit, it is reached. */
export function usageTone(percent: number | null): UsageTone {
  if (percent === null) return 'normal';
  if (percent >= 100) return 'over';
  return percent >= 90 ? 'warning' : 'normal';
}

export const USAGE_KINDS: ReadonlyArray<UsageKind> = ['consume', 'record', 'refund', 'adjust'];

const KIND_KEY: Record<UsageKind, string> = {
  consume: keys.billing.admin_usage.kinds.consume,
  record: keys.billing.admin_usage.kinds.record,
  refund: keys.billing.admin_usage.kinds.refund,
  adjust: keys.billing.admin_usage.kinds.adjust,
};

export function kindLabel(kind: string): string {
  const key = KIND_KEY[kind as UsageKind];
  return key ? translate(key) : kind;
}

const HOLD_STATUS_KEY: Record<HoldStatus, string> = {
  held: keys.billing.admin_usage.hold_status.held,
  committed: keys.billing.admin_usage.hold_status.committed,
  released: keys.billing.admin_usage.hold_status.released,
  expired: keys.billing.admin_usage.hold_status.expired,
};

export function holdStatusLabel(status: string): string {
  const key = HOLD_STATUS_KEY[status as HoldStatus];
  return key ? translate(key) : status;
}

/** A date and time in the console's locale; '' when there is none. */
export function formatDateTime(iso: string | null, locale: string | undefined): string {
  if (!iso) return '';
  return new Intl.DateTimeFormat(intlLocale(locale), {
    dateStyle: 'medium',
    timeStyle: 'short',
  }).format(new Date(iso));
}

/**
 * A signed quantity for the adjust dialog: a whole number other than 0,
 * within the server's bound. `null` when the text is not one.
 */
export function parseAdjustQuantity(text: string): number | null {
  const trimmed = text.trim();
  if (!/^[-+]?\d+$/.test(trimmed)) return null;
  const value = Number(trimmed);
  if (!Number.isSafeInteger(value) || value === 0) return null;
  return value;
}
