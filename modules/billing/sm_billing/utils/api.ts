/** fetch wrapper for the billing API: JSON in/out, CSRF header, readable errors. */

import { keys, translate } from './i18n';

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
  checkout_unavailable: keys.billing.errors.checkout_unavailable,
  plan_not_found: keys.billing.errors.plan_not_found,
  plan_is_free: keys.billing.errors.plan_is_free,
  interval_unavailable: keys.billing.errors.interval_unavailable,
  already_subscribed: keys.billing.errors.already_subscribed,
  already_on_plan: keys.billing.errors.already_on_plan,
  no_subscription: keys.billing.errors.no_subscription,
  no_customer: keys.billing.errors.no_customer,
  tenant_owner_required: keys.billing.errors.tenant_owner_required,
  tenant_required: keys.billing.errors.tenant_required,
  provider_error: keys.billing.errors.provider_error,
  provider_managed: keys.billing.errors.provider_managed,
  no_provider_subscription: keys.billing.errors.no_provider_subscription,
  tenant_not_found: keys.billing.errors.tenant_not_found,
  paid_plan_needs_price: keys.billing.errors.paid_plan_needs_price,
  free_plan_has_price: keys.billing.errors.free_plan_has_price,
  free_plan_has_trial: keys.billing.errors.free_plan_has_trial,
  default_must_be_free: keys.billing.errors.default_must_be_free,
  default_required: keys.billing.errors.default_required,
  cannot_archive_default: keys.billing.errors.cannot_archive_default,
  plan_key_taken: keys.billing.errors.plan_key_taken,
  plan_key_immutable: keys.billing.errors.plan_key_immutable,
  price_taken: keys.billing.errors.price_taken,
  price_not_found: keys.billing.errors.price_not_found,
  invalid_return_url: keys.billing.errors.invalid_return_url,
};

export function describeError(detail: string, body: Record<string, unknown> = {}): string {
  if (detail === 'too_many_members') {
    const over = Number(body.used) - Number(body.limit);
    return translate(keys.billing.errors.too_many_members, {
      limit: body.limit,
      used: body.used,
      over,
    });
  }
  if (detail === 'validation_error' && typeof body.message === 'string') return body.message;
  if (detail === 'price_mismatch')
    return translate(keys.billing.errors.price_mismatch, {
      price: body.price,
      reason: body.reason,
    });
  if (detail === 'provider_error' && typeof body.message === 'string') {
    return translate(keys.billing.errors.provider_error_detail, {
      base: translate(MESSAGES.provider_error),
      message: body.message,
    });
  }
  return translate(MESSAGES[detail] ?? keys.billing.errors.generic);
}

/** FastAPI's 422 body: `detail` is a list of `{loc, msg}`; show the first. */
function validationMessage(items: unknown[]): string {
  const first = (items[0] ?? {}) as { loc?: unknown; msg?: unknown };
  const msg =
    typeof first.msg === 'string' ? first.msg : translate(keys.billing.errors.invalid_input);
  const field = Array.isArray(first.loc) ? first.loc[first.loc.length - 1] : undefined;
  return field === undefined
    ? translate(keys.billing.errors.validation_plain, { msg })
    : translate(keys.billing.errors.validation_field, { field, msg });
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
