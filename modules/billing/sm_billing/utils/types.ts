/** Shapes the billing API and views send — mirrors sm_billing/schemas.py. */

export type PricingModel = 'free' | 'flat' | 'per_seat';
export type Interval = 'month' | 'year';
export type SubscriptionStatus =
  | 'trialing'
  | 'active'
  | 'past_due'
  | 'unpaid'
  | 'canceled'
  | 'incomplete';

export interface Plan {
  id: number;
  key: string;
  name: string;
  description: string;
  pricing_model: PricingModel;
  currency: string;
  amount_month: number | null;
  amount_year: number | null;
  stripe_price_month: string | null;
  stripe_price_year: string | null;
  trial_days: number;
  limits: Record<string, number>;
  features: string[];
  is_default: boolean;
  is_public: boolean;
  sort_order: number;
  archived_at: string | null;
}

export interface Subscription {
  status: SubscriptionStatus | null;
  interval: Interval | null;
  quantity: number;
  trial_end: string | null;
  current_period_end: string | null;
  cancel_at_period_end: boolean;
  has_provider_subscription: boolean;
}

export interface Status {
  plan: Plan;
  subscription: Subscription | null;
  seats: { used: number; limit: number | null };
  provider: string;
  checkout_available: boolean;
  portal_available: boolean;
}

export interface SubscriptionRow {
  tenant_id: string;
  tenant_name: string;
  tenant_slug: string;
  tenant_status: string;
  members: number;
  plan_id: number;
  plan_key: string;
  plan_name: string;
  status: SubscriptionStatus | null;
  interval: Interval | null;
  quantity: number | null;
  current_period_end: string | null;
  cancel_at_period_end: boolean;
  suspended_by_billing: boolean;
  provider_subscription_id: string | null;
  synced_at: string | null;
}

export interface Connection {
  provider: string;
  active_provider: string;
  provider_error: string;
  has_secret_key: boolean;
  has_webhook_secret: boolean;
  return_base_url: string;
  webhook_path: string;
}

/** Props every admin page receives. */
export interface AdminCommon {
  csrf_token: string;
  can_manage: boolean;
  provider: string;
  checkout_available: boolean;
}
