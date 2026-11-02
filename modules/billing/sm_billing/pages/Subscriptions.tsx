import { Head, router, usePage } from '@inertiajs/react';
import { EmptyState } from '@simple-module-py/ui/components/EmptyState';
import { PageShell } from '@simple-module-py/ui/components/PageShell';
import { Card } from '@simple-module-py/ui/components/ui/card';
import { AdminLayout } from '@simple-module-py/ui/layouts/AdminLayout';
import { Building2, User } from 'lucide-react';
import { useState } from 'react';
import { toast } from 'sonner';
import { AdminNav } from '../components/AdminNav';
import { AssignDialog } from '../components/AssignDialog';
import { ProviderFallbackBanner } from '../components/ProviderFallbackBanner';
import { SubscriptionsFilters } from '../components/SubscriptionsFilters';
import { SubscriptionsPager, visitSubscriptions } from '../components/SubscriptionsPager';
import { SubscriptionsTable } from '../components/SubscriptionsTable';
import { SyncHealthBar } from '../components/SyncHealthBar';
import { ADMIN_API, api } from '../utils/api';
import { keys, useT } from '../utils/i18n';
import type {
  AdminCommon,
  Paged,
  Plan,
  SubscriptionRow,
  SubscriptionStatus,
  SyncHealth,
} from '../utils/types';

interface Props extends AdminCommon {
  subscriptions: Paged<SubscriptionRow>;
  plans: Plan[];
  status_filter: string;
  /** The search the rows were filtered by ("" for none). */
  search: string;
  sync_health: SyncHealth;
}

function Subscriptions() {
  const { t } = useT();
  const c = keys.billing.subscriptions;
  const {
    subscriptions,
    plans,
    status_filter,
    search,
    sync_health,
    csrf_token,
    can_manage,
    checkout_available,
    provider,
    provider_error,
    subject_mode,
  } = usePage<{ props: Props }>().props as unknown as Props;
  const byUser = subject_mode === 'user';
  const [assigning, setAssigning] = useState<SubscriptionRow | null>(null);
  const [busy, setBusy] = useState(false);

  async function run(work: () => Promise<void>) {
    setBusy(true);
    try {
      await work();
      router.reload();
    } catch (err) {
      toast.error((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const resync = (row: SubscriptionRow) =>
    run(async () => {
      await api(`${ADMIN_API}/subscriptions/${row.tenant_id}/resync`, csrf_token, { body: {} });
      toast.success(t(c.resynced, { name: row.tenant_name }));
    });

  const assign = (planId: number, status: SubscriptionStatus) =>
    run(async () => {
      if (!assigning) return;
      await api(`${ADMIN_API}/subscriptions/${assigning.tenant_id}/assign`, csrf_token, {
        body: { plan_id: planId, status },
      });
      toast.success(t(c.assigned, { name: assigning.tenant_name }));
      setAssigning(null);
    });

  const { items: rows } = subscriptions;
  const filters = { status: status_filter, q: search ?? '' };

  return (
    <>
      <Head title={t(c.head_title)} />
      <PageShell
        title={t(keys.billing.page.title)}
        description={
          checkout_available
            ? t(byUser ? c.description_stripe_users : c.description_stripe)
            : t(c.description_manual, { provider })
        }
      >
        <AdminNav active="subscriptions" />
        {provider_error && (
          <div className="mb-4">
            <ProviderFallbackBanner error={provider_error} />
          </div>
        )}
        {checkout_available && <SyncHealthBar health={sync_health} />}
        <SubscriptionsFilters
          status={status_filter}
          search={search ?? ''}
          subjectMode={subject_mode}
          onChange={(next) => visitSubscriptions(next)}
        />
        <Card className="overflow-hidden p-0">
          {rows.length === 0 ? (
            <EmptyState
              icon={byUser ? User : Building2}
              title={t(byUser ? c.empty_title_users : c.empty_title)}
              description={
                search ? t(c.empty_search) : status_filter ? t(c.empty_filtered) : t(c.empty_none)
              }
            />
          ) : (
            <SubscriptionsTable
              rows={rows}
              canManage={can_manage}
              mode={checkout_available ? 'resync' : 'assign'}
              busy={busy}
              onResync={resync}
              onAssign={setAssigning}
              subjectMode={subject_mode}
            />
          )}
          <SubscriptionsPager
            filters={filters}
            page={subscriptions.page}
            perPage={subscriptions.per_page}
            total={subscriptions.total}
          />
        </Card>
      </PageShell>
      <AssignDialog
        row={assigning}
        plans={plans}
        busy={busy}
        onClose={() => setAssigning(null)}
        onAssign={assign}
        subjectMode={subject_mode}
      />
    </>
  );
}

Subscriptions.layout = [AdminLayout];
export default Subscriptions;
