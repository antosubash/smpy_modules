// @vitest-environment happy-dom
import * as React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import type { Plan, SubscriptionRow } from '../utils/types';
import { offeredPlan } from './AssignDialog';
import { PlansTable } from './PlansTable';
import { SubscriptionsTable } from './SubscriptionsTable';

(globalThis as unknown as { React: unknown }).React = React;

const name = 'X'.repeat(120);
const plan: Plan = {
  id: 1,
  key: 'test',
  name,
  description: '',
  pricing_model: 'free',
  currency: 'usd',
  amount_month: null,
  amount_year: null,
  stripe_price_month: null,
  stripe_price_year: null,
  trial_days: 0,
  limits: {},
  features: [],
  is_default: false,
  is_public: true,
  sort_order: 0,
  archived_at: null,
};
const row: SubscriptionRow = {
  tenant_id: 'test',
  tenant_name: name,
  tenant_slug: 'test',
  tenant_status: 'active',
  members: 1,
  plan_id: 1,
  plan_key: plan.key,
  plan_name: name,
  status: 'active',
  interval: 'month',
  quantity: 1,
  current_period_end: null,
  cancel_at_period_end: false,
  suspended_by_billing: false,
  provider_subscription_id: null,
  synced_at: null,
};

function assertBoundedNames(markup: string, count: number) {
  const host = document.createElement('div');
  host.innerHTML = markup;
  const names = host.querySelectorAll(`[title="${name}"]`);
  expect(names).toHaveLength(count);
  for (const element of names) {
    expect(element.textContent).toBe(name);
    expect(element.className.split(' ')).toEqual(
      expect.arrayContaining(['block', 'max-w-32', 'sm:max-w-64', 'truncate']),
    );
  }
  // Keep the header and row actions visible while a narrow viewport scrolls.
  for (const selector of ['thead th:last-child', 'tbody td:last-child']) {
    expect(host.querySelector(selector)?.className.split(' ')).toEqual(
      expect.arrayContaining(['sticky', 'right-0', 'bg-background']),
    );
  }
  expect(host.querySelector('tbody td:last-child button')).not.toBeNull();
}

describe('billing table long names', () => {
  it('bounds a 120-character plan name and preserves its full title', () => {
    assertBoundedNames(
      renderToStaticMarkup(
        <PlansTable plans={[plan]} canManage onEdit={() => {}} onArchive={() => {}} />,
      ),
      1,
    );
  });

  it('bounds subscription plan and organisation names with visible actions', () => {
    assertBoundedNames(
      renderToStaticMarkup(
        <SubscriptionsTable
          rows={[row]}
          canManage
          mode="assign"
          busy={false}
          onResync={() => {}}
          onAssign={() => {}}
        />,
      ),
      2,
    );
  });
});

describe('subscriptions table subject mode', () => {
  function headers(subjectMode?: 'tenant' | 'user'): string[] {
    const host = document.createElement('div');
    host.innerHTML = renderToStaticMarkup(
      <SubscriptionsTable
        rows={[{ ...row, tenant_id: 'user:1', tenant_name: 'a@x.io', tenant_slug: '' }]}
        canManage
        mode="assign"
        busy={false}
        onResync={() => {}}
        onAssign={() => {}}
        subjectMode={subjectMode}
      />,
    );
    return [...host.querySelectorAll('thead th')].map((th) => th.textContent ?? '');
  }

  it('names organisations and members in tenant mode', () => {
    const cols = headers();
    expect(cols[0]).toBe('Organisation');
    expect(cols).toContain('Members');
  });

  it('names users and drops members in user mode', () => {
    const cols = headers('user');
    expect(cols[0]).toBe('User');
    expect(cols).not.toContain('Members');
    expect(cols).toHaveLength(headers().length - 1);
  });
});

describe('assign dialog preselection', () => {
  const choices = [
    { ...plan, id: 1 },
    { ...plan, id: 2 },
  ];

  it('keeps the row plan when the picker offers it', () => {
    expect(offeredPlan(choices, 2)).toBe(2);
  });

  it('falls back to the first choice when the row plan is not offered', () => {
    expect(offeredPlan(choices, 9)).toBe(1);
    expect(offeredPlan(choices, undefined)).toBe(1);
    expect(offeredPlan([], 9)).toBe(0);
  });
});
