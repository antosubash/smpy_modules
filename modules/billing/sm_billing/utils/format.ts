import type { Interval, Plan, Status, SubscriptionStatus } from './types';

/** Minor units → localized currency string; '' when there is no amount. */
export function formatMoney(minor: number | null, currency: string, locale?: string): string {
  if (minor === null || minor === undefined) return '';
  return new Intl.NumberFormat(locale, {
    style: 'currency',
    currency: currency.toUpperCase(),
  }).format(minor / 100);
}

export function formatDate(iso: string | null, locale?: string): string {
  if (!iso) return '';
  return new Intl.DateTimeFormat(locale, { dateStyle: 'medium' }).format(new Date(iso));
}

export function priceFor(plan: Plan, interval: Interval): string | null {
  return interval === 'month' ? plan.stripe_price_month : plan.stripe_price_year;
}

export function priceLabel(plan: Plan, interval: Interval, locale?: string): string {
  if (plan.pricing_model === 'free') return 'Free';
  if (!priceFor(plan, interval)) {
    return interval === 'month' ? 'Not available monthly' : 'Not available yearly';
  }
  const amount = interval === 'month' ? plan.amount_month : plan.amount_year;
  const money = formatMoney(amount, plan.currency, locale) || 'Paid';
  const seat = plan.pricing_model === 'per_seat' ? ' / seat' : '';
  return `${money}${seat} / ${interval}`;
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

export const STATUS_LABEL: Record<SubscriptionStatus, string> = {
  trialing: 'Trial',
  active: 'Active',
  past_due: 'Payment failed',
  unpaid: 'Unpaid',
  canceled: 'Canceled',
  incomplete: 'Incomplete',
};

export function statusLabel(status: SubscriptionStatus | null): string {
  return status ? STATUS_LABEL[status] : 'No subscription';
}
