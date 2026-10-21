import { keys, translate } from './i18n';
import type { Interval, Plan, Status, SubscriptionStatus } from './types';

/**
 * A name for a dialog title. A 120-character name with no break opportunity
 * widens the dialog past the viewport and pushes its buttons off-screen; the
 * full name stays in the table row (`title`) and the editor's Name field.
 */
export function clipName(name: string, max = 40): string {
  return name.length > max ? `${name.slice(0, max - 1)}…` : name;
}

/**
 * Minor units → localized currency string; '' when there is no amount.
 *
 * `locale` is the console's (`useT().locale`), never left to the browser: a
 * German console on an English browser would otherwise read `€19.00` (#189).
 */
export function formatMoney(
  minor: number | null,
  currency: string,
  locale: string | undefined,
): string {
  if (minor === null || minor === undefined) return '';
  return new Intl.NumberFormat(locale, {
    style: 'currency',
    currency: currency.toUpperCase(),
  }).format(minor / 100);
}

/** A date in the console's locale (`useT().locale`); '' when there is none. */
export function formatDate(iso: string | null, locale: string | undefined): string {
  if (!iso) return '';
  return new Intl.DateTimeFormat(locale, { dateStyle: 'medium' }).format(new Date(iso));
}

export function priceFor(plan: Plan, interval: Interval): string | null {
  return interval === 'month' ? plan.stripe_price_month : plan.stripe_price_year;
}

export function priceLabel(plan: Plan, interval: Interval, locale: string | undefined): string {
  const p = keys.billing.price;
  if (plan.pricing_model === 'free') return translate(p.free);
  if (!priceFor(plan, interval)) {
    return translate(interval === 'month' ? p.unavailable_month : p.unavailable_year);
  }
  const amount = interval === 'month' ? plan.amount_month : plan.amount_year;
  const money = formatMoney(amount, plan.currency, locale) || translate(p.paid);
  const perSeat = plan.pricing_model === 'per_seat';
  const key =
    interval === 'month'
      ? perSeat
        ? p.seat_month
        : p.flat_month
      : perSeat
        ? p.seat_year
        : p.flat_year;
  return translate(key, { money });
}

const LIVE: ReadonlyArray<SubscriptionStatus> = ['active', 'trialing', 'past_due'];

/**
 * Checkout has landed: a provider subscription that grants access. Not just
 * "has a provider id" — a tenant re-subscribing still carries their old,
 * canceled one, which would end the wait before the new one arrived.
 */
export function isActivated(status: Status): boolean {
  const sub = status.subscription;
  return Boolean(sub?.has_provider_subscription && sub.status && LIVE.includes(sub.status));
}

/** What the plan picker's button does for ``target``. */
export type PlanCta = 'current' | 'checkout' | 'change' | 'downgrade' | 'unavailable';

export function planCta(status: Status, target: Plan, interval: Interval): PlanCta {
  const sub = status.subscription;
  const live =
    sub?.has_provider_subscription &&
    (sub.status === 'active' || sub.status === 'trialing' || sub.status === 'past_due');
  if (target.pricing_model === 'free') {
    if (!live) return status.plan.id === target.id ? 'current' : 'unavailable';
    return sub?.cancel_at_period_end ? 'current' : 'downgrade';
  }
  if (status.plan.id === target.id && (!live || sub?.interval === interval)) {
    if (!sub?.cancel_at_period_end) return 'current';
  }
  if (!status.checkout_available || !priceFor(target, interval)) return 'unavailable';
  return live ? 'change' : 'checkout';
}

export type BadgeTone = 'default' | 'secondary' | 'destructive' | 'outline';

export function statusTone(status: SubscriptionStatus | null): BadgeTone {
  switch (status) {
    case 'past_due':
    case 'unpaid':
      return 'destructive';
    case 'active':
    case 'trialing':
      return 'default';
    case null:
      return 'outline';
    default:
      return 'secondary';
  }
}

/** Every subscription status, in the order the pickers list them. */
export const STATUSES: ReadonlyArray<SubscriptionStatus> = [
  'trialing',
  'active',
  'past_due',
  'unpaid',
  'canceled',
  'incomplete',
];

const STATUS_KEY: Record<SubscriptionStatus, string> = {
  trialing: keys.billing.status.trialing,
  active: keys.billing.status.active,
  past_due: keys.billing.status.past_due,
  unpaid: keys.billing.status.unpaid,
  canceled: keys.billing.status.canceled,
  incomplete: keys.billing.status.incomplete,
};

export function statusLabel(status: SubscriptionStatus | null): string {
  return translate(status ? STATUS_KEY[status] : keys.billing.status.none);
}
