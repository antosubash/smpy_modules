import type { Plan, PricingModel } from './types';

/** The plan editor's state: amounts as decimal strings, limits as rows. */
export interface PlanForm {
  key: string;
  name: string;
  description: string;
  pricing_model: PricingModel;
  currency: string;
  amount_month: string;
  amount_year: string;
  stripe_price_month: string;
  stripe_price_year: string;
  trial_days: string;
  limits: { key: string; value: string }[];
  features: string;
  is_default: boolean;
  is_public: boolean;
  sort_order: string;
}

export type PlanPayload = Omit<Plan, 'id' | 'archived_at'>;

const KEY_RE = /^[a-z0-9][a-z0-9_-]{0,63}$/;
const LIMIT_KEY_RE = /^[a-z0-9][a-z0-9_.-]{0,99}$/;
const AMOUNT_RE = /^\d+(\.\d{1,2})?$/;
const WHOLE_RE = /^\d+$/;
/** The API's `PlanIn.trial_days` upper bound. */
const MAX_TRIAL_DAYS = 730;

export function emptyPlanForm(): PlanForm {
  return {
    key: '',
    name: '',
    description: '',
    pricing_model: 'free',
    currency: 'eur',
    amount_month: '',
    amount_year: '',
    stripe_price_month: '',
    stripe_price_year: '',
    trial_days: '0',
    limits: [],
    features: '',
    is_default: false,
    is_public: true,
    sort_order: '0',
  };
}

const toDecimal = (minor: number | null) => (minor === null ? '' : (minor / 100).toFixed(2));
const toMinor = (text: string) => (text.trim() ? Math.round(Number(text) * 100) : null);
const orNull = (text: string) => text.trim() || null;

export function formFromPlan(plan: Plan): PlanForm {
  return {
    key: plan.key,
    name: plan.name,
    description: plan.description,
    pricing_model: plan.pricing_model,
    currency: plan.currency,
    amount_month: toDecimal(plan.amount_month),
    amount_year: toDecimal(plan.amount_year),
    stripe_price_month: plan.stripe_price_month ?? '',
    stripe_price_year: plan.stripe_price_year ?? '',
    trial_days: String(plan.trial_days),
    limits: Object.entries(plan.limits).map(([key, value]) => ({ key, value: String(value) })),
    features: plan.features.join(', '),
    is_default: plan.is_default,
    is_public: plan.is_public,
    sort_order: String(plan.sort_order),
  };
}

function parseFeatures(text: string): string[] {
  return [
    ...new Set(
      text
        .split(',')
        .map((f) => f.trim())
        .filter(Boolean),
    ),
  ];
}

export function planPayload(form: PlanForm): PlanPayload {
  const limits: Record<string, number> = {};
  for (const row of form.limits) {
    if (row.key.trim() && row.value.trim()) limits[row.key.trim()] = Number(row.value);
  }
  return {
    key: form.key.trim(),
    name: form.name.trim(),
    description: form.description.trim(),
    pricing_model: form.pricing_model,
    currency: form.currency.trim().toLowerCase(),
    amount_month: toMinor(form.amount_month),
    amount_year: toMinor(form.amount_year),
    stripe_price_month: orNull(form.stripe_price_month),
    stripe_price_year: orNull(form.stripe_price_year),
    trial_days: Number(form.trial_days || 0),
    limits,
    features: parseFeatures(form.features),
    is_default: form.is_default,
    is_public: form.is_public,
    sort_order: Number(form.sort_order || 0),
  };
}

/** The first problem with the form, or null. Mirrors the server's invariants. */
export function validatePlanForm(form: PlanForm): string | null {
  if (!KEY_RE.test(form.key.trim())) {
    return 'The key must be 1-64 lowercase letters, digits, "-" or "_".';
  }
  if (!form.name.trim()) return 'Give the plan a name.';
  if (!/^[a-zA-Z]{3}$/.test(form.currency.trim())) return 'Currency is a 3-letter code.';
  for (const amount of [form.amount_month, form.amount_year]) {
    if (amount.trim() && !AMOUNT_RE.test(amount.trim())) {
      return 'Each amount is a number with at most two decimals.';
    }
  }
  if (!WHOLE_RE.test(form.trial_days.trim() || '0')) return 'Trial days is a whole number.';
  if (Number(form.trial_days || 0) > MAX_TRIAL_DAYS) {
    return `A trial is at most ${MAX_TRIAL_DAYS} days.`;
  }
  for (const row of form.limits) {
    if (!row.key.trim() && !row.value.trim()) continue;
    if (!LIMIT_KEY_RE.test(row.key.trim())) return `"${row.key}" is not a valid limit key.`;
    if (!WHOLE_RE.test(row.value.trim())) return `Limit "${row.key}" must be a whole number ≥ 0.`;
  }
  const hasPrice = Boolean(form.stripe_price_month.trim() || form.stripe_price_year.trim());
  if (form.pricing_model === 'free') {
    if (hasPrice) return 'Free plans have no Stripe price.';
    if (Number(form.trial_days || 0) > 0) return 'Free plans have no trial.';
  } else {
    if (!hasPrice) return 'A paid plan needs at least one Stripe price ID.';
    if (form.is_default) return 'Only a free plan can be the default.';
  }
  return null;
}
