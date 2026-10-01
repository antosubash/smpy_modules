import { describe, expect, it } from 'vitest';
import { emptyPlanForm, formFromPlan, planPayload, validatePlanForm } from './plan-form';

describe('plan form', () => {
  it('round-trips limits and features through rows', () => {
    const form = formFromPlan({
      id: 1,
      key: 'team',
      name: 'Team',
      description: '',
      pricing_model: 'per_seat',
      currency: 'eur',
      amount_month: 900,
      amount_year: null,
      stripe_price_month: 'pm',
      stripe_price_year: null,
      trial_days: 7,
      limits: { 'tenants.seats': 5 },
      features: ['sso'],
      is_default: false,
      is_public: true,
      sort_order: 2,
      archived_at: null,
    });
    expect(form.limits).toEqual([{ key: 'tenants.seats', value: '5' }]);
    expect(form.amount_month).toBe('9.00');
    const payload = planPayload(form);
    expect(payload.limits).toEqual({ 'tenants.seats': 5 });
    expect(payload.features).toEqual(['sso']);
    expect(payload.amount_month).toBe(900);
    expect(payload.amount_year).toBeNull();
    expect(payload.stripe_price_year).toBeNull();
  });

  it('drops blank limit rows and parses features', () => {
    const form = {
      ...emptyPlanForm(),
      key: 'x',
      name: 'X',
      limits: [
        { key: '', value: '' },
        { key: 'exports', value: '0' },
      ],
      features: 'sso, audit ,, sso',
    };
    const payload = planPayload(form);
    expect(payload.limits).toEqual({ exports: 0 });
    expect(payload.features).toEqual(['sso', 'audit']);
  });

  it('reports the errors the API would', () => {
    const base = { ...emptyPlanForm(), key: 'team', name: 'Team' };
    expect(validatePlanForm({ ...base, key: 'Bad Key' })).toContain('key');
    expect(validatePlanForm({ ...base, pricing_model: 'flat' })).toContain('price');
    expect(validatePlanForm({ ...base, stripe_price_month: 'p' })).toContain('Free plans');
    expect(validatePlanForm({ ...base, limits: [{ key: 'seats', value: '-1' }] })).toContain(
      'whole number',
    );
    expect(validatePlanForm({ ...base, amount_month: 'abc' })).toContain('amount');
    expect(validatePlanForm(base)).toBeNull();
  });
});
