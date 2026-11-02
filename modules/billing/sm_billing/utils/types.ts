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

/** How far the local mirror may lag Stripe (admin subscriptions screen). */
export interface SyncHealth {
  oldest_synced_at: string | null;
  never_synced: number;
  unprocessed_webhooks: number;
  reconcile_interval_minutes: number;
  reconcile_running: boolean;
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

/** Who billing bills: organisations, or each signed-in user (#274). */
export type SubjectMode = 'tenant' | 'user';

/** Props every admin page receives. */
export interface AdminCommon {
  csrf_token: string;
  can_manage: boolean;
  provider: string;
  checkout_available: boolean;
  /** Why a chosen ``stripe`` fell back to ``manual``; "" when it did not. */
  provider_error: string;
  /** "user": the admin lists name users (by email) instead of organisations. */
  subject_mode: SubjectMode;
}

// ── usage metering (sm_billing/metering/schemas.py) ─────────────────

export type MeterKind = 'counter' | 'gauge';
export type MeterUnit = 'count' | 'bytes' | 'tokens' | 'ms';
export type UsageKind = 'consume' | 'record' | 'refund' | 'adjust';
export type HoldStatus = 'held' | 'committed' | 'released' | 'expired';

/** One meter on the tenant's usage card. */
export interface MeterUsage {
  meter: string;
  kind: MeterKind;
  unit: MeterUnit;
  label_key: string;
  used: number;
  limit: number | null;
  period_start: string | null;
  period_end: string | null;
  holds: number | null;
}

/** One organisation x meter on the admin usage table. */
export interface UsageRow {
  tenant_id: string;
  tenant_name: string;
  tenant_slug: string;
  meter: string;
  kind: MeterKind;
  unit: MeterUnit;
  label_key: string;
  registered: boolean;
  used: number;
  limit: number | null;
  percent: number | null;
  period_start: string | null;
  period_end: string | null;
}

/** A page of a list, in `simple_module_db.paginate`'s shape. */
export interface Paged<T> {
  items: T[];
  total: number;
  page: number;
  per_page: number;
  pages: number;
}

export interface UsageEvent {
  id: number;
  meter: string;
  kind: UsageKind;
  quantity: number;
  idempotency_key: string;
  source: string;
  actor: string | null;
  reason: string | null;
  period_start: string | null;
  occurred_at: string;
  recorded_at: string;
}

export interface UsageHold {
  id: string;
  meter: string;
  quantity: number;
  status: HoldStatus;
  idempotency_key: string;
  source: string;
  expires_at: string | null;
  created_at: string;
  settled_at: string | null;
}

export interface MeterInfo {
  key: string;
  kind: MeterKind;
  unit: MeterUnit;
  label_key: string;
}
