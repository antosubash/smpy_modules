import { router } from '@inertiajs/react';
import { PaginationBar } from '@simple-module-py/ui/components/PaginationBar';
import type { SubscriptionsFilterValues } from './SubscriptionsFilters';

export const SUBSCRIPTIONS_URL = '/admin/billing/subscriptions';

/** The query string for `filters` on `page`, leaving defaults (and page 1) out. */
export function subscriptionsQuery(
  filters: SubscriptionsFilterValues,
  page = 1,
): Record<string, string> {
  const out: Record<string, string> = {};
  if (filters.status) out.status = filters.status;
  if (filters.q) out.q = filters.q;
  if (page > 1) out.page = String(page);
  return out;
}

export function visitSubscriptions(filters: SubscriptionsFilterValues, page = 1) {
  router.get(SUBSCRIPTIONS_URL, subscriptionsQuery(filters, page), {
    preserveScroll: true,
    preserveState: true,
  });
}

interface Props {
  filters: SubscriptionsFilterValues;
  page: number;
  perPage: number;
  total: number;
}

/** Previous / Next under the table, keeping the status and search; hidden for one page. */
export function SubscriptionsPager({ filters, page, perPage, total }: Props) {
  return (
    <PaginationBar
      page={page}
      perPage={perPage}
      total={total}
      onPageChange={(next) => visitSubscriptions(filters, next)}
      hideWhenSinglePage
    />
  );
}
