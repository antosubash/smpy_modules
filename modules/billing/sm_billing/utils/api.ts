/** fetch wrapper for the billing API: JSON in/out, CSRF header, readable errors. */

const CSRF_HEADER = 'X-CSRF-Token';

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly detail: string,
    public readonly body: Record<string, unknown>,
  ) {
    super(describeError(detail, body));
  }
}

const MESSAGES: Record<string, string> = {
  checkout_unavailable: 'Online payment is not set up for this site.',
  plan_not_found: 'That plan is no longer available.',
  plan_is_free: 'The free plan needs no checkout.',
  interval_unavailable: 'That plan is not sold for this billing period.',
  already_subscribed: 'You already have a subscription — change plan instead.',
  already_on_plan: 'You are already on this plan.',
  no_subscription: 'There is no paid subscription to change yet.',
  no_customer: 'There is no billing account yet — subscribe to a plan first.',
  tenant_owner_required: 'Only the organisation owner can change billing.',
  tenant_required: 'Pick an organisation first.',
  provider_error: 'The payment provider refused the request.',
  provider_managed: 'Subscriptions are managed by Stripe; use Resync instead.',
  no_provider_subscription: 'This tenant has no Stripe subscription to resync.',
  tenant_not_found: 'That organisation no longer exists.',
  paid_plan_needs_price: 'A paid plan needs at least one Stripe price ID.',
  free_plan_has_price: 'Free plans have no Stripe price.',
  free_plan_has_trial: 'Free plans have no trial.',
  default_must_be_free: 'Only a free plan can be the default.',
  default_required: 'Mark another free plan as default first.',
  cannot_archive_default: 'The default plan cannot be archived.',
  plan_key_taken: 'Another plan already uses that key.',
  plan_key_immutable: 'A plan key cannot change once created.',
  price_taken: 'Another plan already uses that Stripe price.',
  price_not_found: 'Stripe has no price with that ID.',
};

export function describeError(detail: string, body: Record<string, unknown> = {}): string {
  if (detail === 'too_many_members') {
    const over = Number(body.used) - Number(body.limit);
    return `That plan allows ${body.limit} seats and you use ${body.used} — remove ${over} first.`;
  }
  if (detail === 'validation_error' && typeof body.message === 'string') return body.message;
  if (detail === 'price_mismatch') return `Stripe price ${body.price}: ${body.reason}.`;
  if (detail === 'provider_error' && typeof body.message === 'string') {
    return `${MESSAGES.provider_error} ${body.message}`;
  }
  return MESSAGES[detail] ?? 'Something went wrong. Please try again.';
}

/** FastAPI's 422 body: `detail` is a list of `{loc, msg}`; show the first. */
function validationMessage(items: unknown[]): string {
  const first = (items[0] ?? {}) as { loc?: unknown; msg?: unknown };
  const msg = typeof first.msg === 'string' ? first.msg : 'Invalid input';
  const field = Array.isArray(first.loc) ? first.loc[first.loc.length - 1] : undefined;
  return field === undefined ? `${msg}.` : `${field}: ${msg}.`;
}

export async function api<T>(
  url: string,
  csrf: string,
  init: { method?: string; body?: unknown } = {},
): Promise<T> {
  const method = init.method ?? (init.body === undefined ? 'GET' : 'POST');
  const response = await fetch(url, {
    method,
    credentials: 'same-origin',
    headers: {
      Accept: 'application/json',
      ...(init.body === undefined ? {} : { 'Content-Type': 'application/json' }),
      ...(method === 'GET' ? {} : { [CSRF_HEADER]: csrf }),
    },
    body: init.body === undefined ? undefined : JSON.stringify(init.body),
  });
  const body = (await response.json().catch(() => ({}))) as Record<string, unknown>;
  if (!response.ok) {
    if (Array.isArray(body.detail)) {
      throw new ApiError(response.status, 'validation_error', {
        ...body,
        message: validationMessage(body.detail),
      });
    }
    const detail = typeof body.detail === 'string' ? body.detail : `http_${response.status}`;
    throw new ApiError(response.status, detail, body);
  }
  return body as T;
}

export const BILLING_API = '/api/billing';
export const ADMIN_API = '/api/billing/admin';
