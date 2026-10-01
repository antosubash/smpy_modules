import { describe, expect, it } from 'vitest';
import { formatMoney, planCta, priceLabel, statusTone } from './format';
import type { Plan, Status } from './types';

const plan = (over: Partial<Plan> = {}): Plan => ({
  id: 2,
  key: 'team',
  name: 'Team',
  description: '',
  pricing_model: 'flat',
  currency: 'eur',
  amount_month: 1900,
  amount_year: 19000,
  stripe_price_month: 'pm',
  stripe_price_year: 'py',
  trial_days: 0,
  limits: {},
  features: [],
  is_default: false,
  is_public: true,
  sort_order: 0,
  archived_at: null,
  ...over,
});

const free = plan({
  id: 1,
  key: 'free',
  pricing_model: 'free',
  is_default: true,
  stripe_price_month: null,
  stripe_price_year: null,
  amount_month: null,
  amount_year: null,
});

const status = (over: Partial<Status> = {}): Status => ({
  plan: free,
  subscription: null,
  seats: { used: 1, limit: null },
  provider: 'stripe',
  checkout_available: true,
  portal_available: false,
  ...over,
});

const paidSub = {
  status: 'active' as const,
  interval: 'month' as const,
  quantity: 1,
  trial_end: null,
  current_period_end: null,
  cancel_at_period_end: false,
  has_provider_subscription: true,
};

describe('formatMoney', () => {
  it('formats minor units in the plan currency', () => {
    expect(formatMoney(1900, 'eur', 'en-US')).toBe('€19.00');
    expect(formatMoney(0, 'usd', 'en-US')).toBe('$0.00');
  });
  it('returns an empty string for a missing amount', () => {
    expect(formatMoney(null, 'eur')).toBe('');
  });
});

describe('priceLabel', () => {
  it('shows free plans as Free', () => {
    expect(priceLabel(free, 'month')).toBe('Free');
  });
  it('adds per seat and the interval', () => {
    const seat = plan({ pricing_model: 'per_seat' });
    expect(priceLabel(seat, 'month', 'en-US')).toBe('€19.00 / seat / month');
    expect(priceLabel(plan(), 'year', 'en-US')).toBe('€190.00 / year');
  });
  it('says when an interval is not sold', () => {
    expect(priceLabel(plan({ stripe_price_year: null }), 'year')).toBe('Not available yearly');
  });
});

describe('planCta', () => {
  it('marks the plan in force as current', () => {
    expect(planCta(status(), free, 'month')).toBe('current');
  });
  it('sends a free tenant to checkout', () => {
    expect(planCta(status(), plan(), 'month')).toBe('checkout');
  });
  it('switches between paid plans on a live subscription', () => {
    const s = status({ plan: plan(), subscription: paidSub });
    expect(planCta(s, plan({ id: 3, key: 'pro' }), 'month')).toBe('change');
    expect(planCta(s, plan(), 'year')).toBe('change');
    expect(planCta(s, plan(), 'month')).toBe('current');
  });
  it('downgrades to free by cancelling at period end', () => {
    const s = status({ plan: plan(), subscription: paidSub });
    expect(planCta(s, free, 'month')).toBe('downgrade');
    const ending = status({
      plan: plan(),
      subscription: { ...paidSub, cancel_at_period_end: true },
    });
    expect(planCta(ending, free, 'month')).toBe('current');
  });
  it('is unavailable without checkout or without a price', () => {
    expect(planCta(status({ checkout_available: false }), plan(), 'month')).toBe('unavailable');
    expect(planCta(status(), plan({ stripe_price_year: null }), 'year')).toBe('unavailable');
  });
});

describe('statusTone', () => {
  it('flags payment problems', () => {
    expect(statusTone('past_due')).toBe('destructive');
    expect(statusTone('unpaid')).toBe('destructive');
    expect(statusTone('active')).toBe('default');
    expect(statusTone(null)).toBe('outline');
  });
});
