import { Head, router, usePage } from '@inertiajs/react';
import { EmptyState } from '@simple-module-py/ui/components/EmptyState';
import { PageShell } from '@simple-module-py/ui/components/PageShell';
import { PaginationBar } from '@simple-module-py/ui/components/PaginationBar';
import { Card } from '@simple-module-py/ui/components/ui/card';
import { AdminLayout } from '@simple-module-py/ui/layouts/AdminLayout';
import { Gauge } from 'lucide-react';
import { useCallback, useState } from 'react';
import { AdminNav } from '../components/AdminNav';
import { ProviderFallbackBanner } from '../components/ProviderFallbackBanner';
import { UsageDetail } from '../components/UsageDetail';
import { UsageFilters, type UsageFilterValues } from '../components/UsageFilters';
import { UsageTable } from '../components/UsageTable';
import { useReturnFocus } from '../hooks/useReturnFocus';
import { keys, useT } from '../utils/i18n';
import type { AdminCommon, MeterInfo, Paged, UsageRow } from '../utils/types';

interface Props extends AdminCommon {
  usage: Paged<UsageRow>;
  meters: MeterInfo[];
  filters: UsageFilterValues;
}

const VIEW_URL = '/admin/billing/usage';

/** The query string for `filters` on `page`, leaving defaults out. */
function query(filters: UsageFilterValues, page: number): Record<string, string> {
  const out: Record<string, string> = {};
  if (filters.meter) out.meter = filters.meter;
  if (filters.q) out.q = filters.q;
  if (filters.over) out.over = '1';
  if (filters.period !== 'current') out.period = filters.period;
  if (page > 1) out.page = String(page);
  return out;
}

function Usage() {
  const { t } = useT();
  const c = keys.billing.admin_usage;
  const { usage, meters, filters, csrf_token, can_manage, provider_error, subject_mode } = usePage<{
    props: Props;
  }>().props as unknown as Props;
  const [open, setOpen] = useState<UsageRow | null>(null);
  const drawerFocus = useReturnFocus();

  const visit = (next: UsageFilterValues, page = 1) =>
    router.get(VIEW_URL, query(next, page), { preserveScroll: true, preserveState: true });
  const reload = useCallback(() => router.reload({ only: ['usage'] }), []);
  const filtered = Boolean(filters.meter || filters.q || filters.over);
  const byUser = subject_mode === 'user';

  return (
    <>
      <Head title={t(c.head_title)} />
      <PageShell
        title={t(keys.billing.page.title)}
        description={t(byUser ? c.description_user : c.description)}
      >
        <AdminNav active="usage" />
        {provider_error && (
          <div className="mb-4">
            <ProviderFallbackBanner error={provider_error} />
          </div>
        )}
        <UsageFilters
          value={filters}
          meters={meters}
          onChange={(next) => visit(next)}
          subjectMode={subject_mode}
        />
        <Card className="overflow-hidden p-0">
          {usage.items.length === 0 ? (
            <EmptyState
              icon={Gauge}
              title={t(c.empty_title)}
              description={
                filtered
                  ? t(byUser ? c.empty_filtered_user : c.empty_filtered)
                  : t(byUser ? c.empty_none_user : c.empty_none)
              }
            />
          ) : (
            <UsageTable
              rows={usage.items}
              subjectMode={subject_mode}
              onOpen={(row) => {
                drawerFocus.remember();
                setOpen(row);
              }}
            />
          )}
          <PaginationBar
            page={usage.page}
            perPage={usage.per_page}
            total={usage.total}
            onPageChange={(page) => visit(filters, page)}
            hideWhenSinglePage
          />
        </Card>
      </PageShell>
      <UsageDetail
        row={open}
        meters={meters}
        csrf={csrf_token}
        canManage={can_manage}
        onClose={() => setOpen(null)}
        onCloseAutoFocus={drawerFocus.onCloseAutoFocus}
        onChanged={reload}
      />
    </>
  );
}

Usage.layout = [AdminLayout];
export default Usage;
