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
const FEATURE_RE = LIMIT_KEY_RE;
const AMOUNT_RE = /^\d+(\.\d{1,2})?$/;
const WHOLE_RE = /^\d+$/;
const INT_RE = /^-?\d+$/;
/** The API's `PlanIn` bounds. */
export const MAX_NAME = 120;
export const MAX_DESCRIPTION = 500;
const MAX_TRIAL_DAYS = 730;
const MAX_MINOR = 2_000_000_000;
const MAX_LIMIT = 2_000_000_000;
const MAX_SORT = 1_000_000;

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

/**
 * Change the pricing model. Free hides the price/amount/trial fields, so their
 * values are cleared rather than validated invisibly; paid plans cannot be the
 * default, so the (then disabled) checkbox is unticked.
 */
export function withPricingModel(form: PlanForm, model: PricingModel): PlanForm {
  if (model === 'free') {
    return {
      ...form,
      pricing_model: model,
      stripe_price_month: '',
      stripe_price_year: '',
      amount_month: '',
      amount_year: '',
      trial_days: '0',
    };
  }
  return { ...form, pricing_model: model, is_default: false };
}

export function planPayload(form: PlanForm): PlanPayload {
  const free = form.pricing_model === 'free';
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
    amount_month: free ? null : toMinor(form.amount_month),
    amount_year: free ? null : toMinor(form.amount_year),
    stripe_price_month: free ? null : orNull(form.stripe_price_month),
    stripe_price_year: free ? null : orNull(form.stripe_price_year),
    trial_days: free ? 0 : Number(form.trial_days || 0),
    limits,
    features: parseFeatures(form.features),
    is_default: form.is_default,
    is_public: form.is_public,
    sort_order: Number(form.sort_order || 0),
  };
}

const amountOk = (text: string) =>
  !text.trim() || (AMOUNT_RE.test(text.trim()) && (toMinor(text) ?? 0) <= MAX_MINOR);

function validatePrice(form: PlanForm): string | null {
  const amounts = [
    ['Monthly', form.amount_month],
    ['Yearly', form.amount_year],
  ] as const;
  for (const [label, amount] of amounts) {
    if (!amountOk(amount)) {
      return `${label} amount must be a number from 0 to 20,000,000 with at most two decimals.`;
    }
  }
  const trial = form.trial_days.trim() || '0';
  if (!WHOLE_RE.test(trial) || Number(trial) > MAX_TRIAL_DAYS) {
    return `Trial days must be a whole number from 0 to ${MAX_TRIAL_DAYS}.`;
  }
  if (!form.stripe_price_month.trim() && !form.stripe_price_year.trim()) {
    return 'A paid plan needs at least one Stripe price ID.';
  }
  if (form.is_default) return 'Only a free plan can be the default.';
  return null;
}

function validateLimits(form: PlanForm): string | null {
  const seen = new Set<string>();
  for (const row of form.limits) {
    const key = row.key.trim();
    const value = row.value.trim();
    if (!key && !value) continue;
    if (!LIMIT_KEY_RE.test(key)) return `"${row.key}" is not a valid limit key.`;
    if (seen.has(key)) return `Limit '${key}' is listed twice.`;
    seen.add(key);
    if (!WHOLE_RE.test(value) || Number(value) > MAX_LIMIT) {
      return `Limit "${key}" must be a whole number from 0 to 2,000,000,000.`;
    }
  }
  return null;
}

/** The first problem with the form, or null. Mirrors the server's invariants. */
export function validatePlanForm(form: PlanForm): string | null {
  if (!KEY_RE.test(form.key.trim())) {
    return 'The key must be 1-64 lowercase letters, digits, "-" or "_".';
  }
  if (!form.name.trim()) return 'Give the plan a name.';
  if (form.name.trim().length > MAX_NAME) return `The name is at most ${MAX_NAME} characters.`;
  if (form.description.trim().length > MAX_DESCRIPTION) {
    return `The description is at most ${MAX_DESCRIPTION} characters.`;
  }
  if (!/^[a-zA-Z]{3}$/.test(form.currency.trim())) return 'Currency is a 3-letter code.';
  if (form.pricing_model !== 'free') {
    const problem = validatePrice(form);
    if (problem) return problem;
  }
  const sort = form.sort_order.trim() || '0';
  if (!INT_RE.test(sort) || Math.abs(Number(sort)) > MAX_SORT) {
    return 'Sort order must be a whole number from -1,000,000 to 1,000,000.';
  }
  const limitProblem = validateLimits(form);
  if (limitProblem) return limitProblem;
  const badFeature = parseFeatures(form.features).find((f) => !FEATURE_RE.test(f));
  if (badFeature !== undefined) {
    return `Feature "${badFeature}" is not valid: use lowercase letters, digits, ".", "_" or "-".`;
  }
  return null;
}
