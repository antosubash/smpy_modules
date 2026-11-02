// @vitest-environment happy-dom
import * as React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { afterEach, describe, expect, it, vi } from 'vitest';
import type { MeterUsage, Plan, Status, SubjectMode } from '../utils/types';
import { CurrentPlanCard } from './CurrentPlanCard';

(globalThis as unknown as { React: unknown }).React = React;

let props: Record<string, unknown> = {};

vi.mock('@inertiajs/react', () => ({
  Head: () => null,
  router: { reload: vi.fn() },
  usePage: () => ({ props }),
}));
vi.mock('sonner', () => ({ toast: Object.assign(vi.fn(), { error: vi.fn() }) }));

const { default: Billing } = await import('../pages/Billing');

const free: Plan = {
  id: 1,
  key: 'free',
  name: 'Free',
  description: '',
  pricing_model: 'free',
  currency: 'eur',
  amount_month: null,
  amount_year: null,
  stripe_price_month: null,
  stripe_price_year: null,
  trial_days: 0,
  limits: {},
  features: [],
  is_default: true,
  is_public: true,
  sort_order: 0,
  archived_at: null,
};

const status: Status = {
  plan: free,
  subscription: null,
  seats: { used: 1, limit: null },
  provider: 'manual',
  checkout_available: false,
  portal_available: false,
};

const used: MeterUsage = {
  meter: 'exports.monthly',
  kind: 'counter',
  unit: 'count',
  label_key: '',
  used: 2,
  limit: 10,
  period_start: '2026-10-01T00:00:00Z',
  period_end: '2026-11-01T00:00:00Z',
  holds: null,
};

function text(html: string): string {
  return new DOMParser().parseFromString(`<div>${html}</div>`, 'text/html').body.textContent ?? '';
}

function page(subjectMode: SubjectMode | undefined, canManage = true): string {
  props = {
    status,
    plans: [free],
    usage: [used],
    can_manage: canManage,
    restore: false,
    csrf_token: 'x',
    checkout: '',
    subject_mode: subjectMode,
  };
  return text(renderToStaticMarkup(<Billing />));
}

afterEach(() => {
  props = {};
});

describe('owner Billing page', () => {
  it('speaks of the organisation and its seats in tenant mode', () => {
    const html = page('tenant');
    expect(html).toContain("Your organisation's plan, seats and payment.");
    expect(html).toContain('Seats');
    expect(html).toContain('Unlimited seats');
    expect(html).toContain('What your organisation has used');
  });

  it('speaks to the user and shows no seats in user mode', () => {
    const html = page('user');
    expect(html).toContain('Your plan and payment.');
    expect(html).toContain('What you have used, against your plan');
    expect(html).not.toMatch(/organi[sz]ation/i);
    expect(html).not.toMatch(/seat/i);
  });

  it('names no organisation owner when a user may not change their plan', () => {
    expect(page('tenant', false)).toContain('Only the organisation owner can change the plan.');
    const html = page('user', false);
    expect(html).toContain('You cannot change your plan here');
    expect(html).not.toMatch(/organi[sz]ation/i);
  });
});

describe('CurrentPlanCard', () => {
  it('hides the Seats row when asked', () => {
    const html = renderToStaticMarkup(
      <CurrentPlanCard
        status={status}
        canManage
        busy={false}
        onPortal={() => {}}
        showSeats={false}
      />,
    );
    expect(text(html)).not.toMatch(/seat/i);
  });
});
