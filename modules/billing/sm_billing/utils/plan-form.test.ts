import { describe, expect, it } from 'vitest';
import {
  emptyPlanForm,
  formFromPlan,
  planPayload,
  validatePlanForm,
  withPricingModel,
} from './plan-form';

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
    expect(validatePlanForm({ ...base, limits: [{ key: 'seats', value: '-1' }] })).toContain(
      'whole number',
    );
    const paid = { ...base, pricing_model: 'flat' as const, stripe_price_month: 'p' };
    expect(validatePlanForm({ ...paid, amount_month: 'abc' })).toContain('amount');
    expect(validatePlanForm({ ...paid, trial_days: '731' })).toContain('730');
    expect(validatePlanForm({ ...paid, trial_days: '730' })).toBeNull();
    expect(validatePlanForm(base)).toBeNull();
  });

  const base = { ...emptyPlanForm(), key: 'team', name: 'Team' };
  const paid = { ...base, pricing_model: 'flat' as const, stripe_price_month: 'p' };

  it('states the actual rule for amounts (BUG-003, BUG-007)', () => {
    const rule = 'Monthly amount must be a number from 0 to 20,000,000 with at most two decimals.';
    expect(validatePlanForm({ ...paid, amount_month: '-5' })).toBe(rule);
    expect(validatePlanForm({ ...paid, amount_month: '1.234' })).toBe(rule);
    expect(validatePlanForm({ ...paid, amount_month: '20000000.01' })).toBe(rule);
    expect(validatePlanForm({ ...paid, amount_year: '99999999' })).toBe(
      'Yearly amount must be a number from 0 to 20,000,000 with at most two decimals.',
    );
    expect(validatePlanForm({ ...paid, amount_month: '20000000.00' })).toBeNull();
    expect(validatePlanForm({ ...paid, amount_month: '0' })).toBeNull();
  });

  it('states the actual rule for trial days (BUG-003)', () => {
    const rule = 'Trial days must be a whole number from 0 to 730.';
    expect(validatePlanForm({ ...paid, trial_days: '-1' })).toBe(rule);
    expect(validatePlanForm({ ...paid, trial_days: '1.5' })).toBe(rule);
    expect(validatePlanForm({ ...paid, trial_days: '731' })).toBe(rule);
  });

  it('validates sort order (BUG-004)', () => {
    const rule = 'Sort order must be a whole number from -1,000,000 to 1,000,000.';
    expect(validatePlanForm({ ...base, sort_order: 'abc' })).toBe(rule);
    expect(validatePlanForm({ ...base, sort_order: '1.5' })).toBe(rule);
    expect(validatePlanForm({ ...base, sort_order: '1000001' })).toBe(rule);
    expect(validatePlanForm({ ...base, sort_order: '-1000001' })).toBe(rule);
    expect(validatePlanForm({ ...base, sort_order: '-1000000' })).toBeNull();
    expect(validatePlanForm({ ...base, sort_order: '' })).toBeNull();
  });

  it('clears hidden paid fields when switching to free (BUG-005)', () => {
    const filled = {
      ...paid,
      stripe_price_year: 'py',
      amount_month: '9.00',
      amount_year: '90.00',
      trial_days: '14',
    };
    const free = withPricingModel(filled, 'free');
    expect(free).toMatchObject({
      pricing_model: 'free',
      stripe_price_month: '',
      stripe_price_year: '',
      amount_month: '',
      amount_year: '',
      trial_days: '0',
    });
    expect(validatePlanForm(free)).toBeNull();
  });

  it('ignores and nulls hidden paid fields on a free plan (BUG-005)', () => {
    const stale = { ...base, stripe_price_month: 'p', amount_month: '-1', trial_days: 'x' };
    expect(validatePlanForm(stale)).toBeNull();
    const payload = planPayload(stale);
    expect(payload.stripe_price_month).toBeNull();
    expect(payload.stripe_price_year).toBeNull();
    expect(payload.amount_month).toBeNull();
    expect(payload.amount_year).toBeNull();
    expect(payload.trial_days).toBe(0);
  });

  it('unsets default when switching to a paid model (BUG-006)', () => {
    const def = { ...base, is_default: true };
    expect(withPricingModel(def, 'flat').is_default).toBe(false);
    expect(withPricingModel(def, 'per_seat').is_default).toBe(false);
    expect(withPricingModel(def, 'free').is_default).toBe(true);
  });

  it('caps limit values (BUG-007)', () => {
    const rule = 'Limit "seats" must be a whole number from 0 to 2,000,000,000.';
    expect(validatePlanForm({ ...base, limits: [{ key: 'seats', value: '2000000001' }] })).toBe(
      rule,
    );
    expect(
      validatePlanForm({ ...base, limits: [{ key: 'seats', value: '99999999999999999999' }] }),
    ).toBe(rule);
    expect(
      validatePlanForm({ ...base, limits: [{ key: 'seats', value: '2000000000' }] }),
    ).toBeNull();
  });

  it('rejects duplicate limit keys', () => {
    const limits = [
      { key: 'tenants.seats', value: '3' },
      { key: ' tenants.seats ', value: '9' },
    ];
    expect(validatePlanForm({ ...base, limits })).toBe("Limit 'tenants.seats' is listed twice.");
  });

  it('validates feature keys client-side (BUG-008)', () => {
    expect(validatePlanForm({ ...base, features: 'sso, bad feature!' })).toBe(
      'Feature "bad feature!" is not valid: use lowercase letters, digits, ".", "_" or "-".',
    );
    expect(validatePlanForm({ ...base, features: 'SSO' })).toContain('"SSO"');
    expect(validatePlanForm({ ...base, features: 'sso, audit.log, a-b_c' })).toBeNull();
  });

  it('caps name and description length', () => {
    expect(validatePlanForm({ ...base, name: 'n'.repeat(121) })).toBe(
      'The name is at most 120 characters.',
    );
    expect(validatePlanForm({ ...base, name: 'n'.repeat(120) })).toBeNull();
    expect(validatePlanForm({ ...base, description: 'd'.repeat(501) })).toBe(
      'The description is at most 500 characters.',
    );
    expect(validatePlanForm({ ...base, description: 'd'.repeat(500) })).toBeNull();
  });
});
