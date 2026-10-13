import { Head, router, usePage } from '@inertiajs/react';
import { EmptyState } from '@simple-module-py/ui/components/EmptyState';
import { PageShell } from '@simple-module-py/ui/components/PageShell';
import { Card } from '@simple-module-py/ui/components/ui/card';
import { Label } from '@simple-module-py/ui/components/ui/label';
import { NativeSelect, NativeSelectOption } from '@simple-module-py/ui/components/ui/native-select';
import { AdminLayout } from '@simple-module-py/ui/layouts/AdminLayout';
import { Building2 } from 'lucide-react';
import { useState } from 'react';
import { toast } from 'sonner';
import { AdminNav } from '../components/AdminNav';
import { AssignDialog } from '../components/AssignDialog';
import { SubscriptionsTable } from '../components/SubscriptionsTable';
import { ADMIN_API, api } from '../utils/api';
import { STATUSES, statusLabel } from '../utils/format';
import { keys, useT } from '../utils/i18n';
import type { AdminCommon, Plan, SubscriptionRow, SubscriptionStatus } from '../utils/types';

interface Props extends AdminCommon {
  rows: SubscriptionRow[];
  plans: Plan[];
  status_filter: string;
}

const VIEW_URL = '/admin/billing/subscriptions';

function Subscriptions() {
  const { t } = useT();
  const c = keys.billing.subscriptions;
  const { rows, plans, status_filter, csrf_token, can_manage, checkout_available, provider } =
    usePage<{ props: Props }>().props as unknown as Props;
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

  const filter = (value: string) =>
    router.get(VIEW_URL, value ? { status: value } : {}, { preserveScroll: true });

  return (
    <>
      <Head title={t(c.head_title)} />
      <PageShell
        title={t(keys.billing.page.title)}
        description={
          checkout_available ? t(c.description_stripe) : t(c.description_manual, { provider })
        }
      >
        <AdminNav active="subscriptions" />
        <div className="mb-4 flex max-w-xs items-center gap-2">
          <Label htmlFor="status-filter" className="shrink-0">
            {t(c.status)}
          </Label>
          <NativeSelect
            id="status-filter"
            value={status_filter}
            onChange={(e) => filter(e.target.value)}
          >
            <NativeSelectOption value="">{t(c.all)}</NativeSelectOption>
            {STATUSES.map((s) => (
              <NativeSelectOption key={s} value={s}>
                {statusLabel(s)}
              </NativeSelectOption>
            ))}
          </NativeSelect>
        </div>
        <Card className="overflow-hidden p-0">
          {rows.length === 0 ? (
            <EmptyState
              icon={Building2}
              title={t(c.empty_title)}
              description={status_filter ? t(c.empty_filtered) : t(c.empty_none)}
            />
          ) : (
            <SubscriptionsTable
              rows={rows}
              canManage={can_manage}
              mode={checkout_available ? 'resync' : 'assign'}
              busy={busy}
              onResync={resync}
              onAssign={setAssigning}
            />
          )}
        </Card>
      </PageShell>
      <AssignDialog
        row={assigning}
        plans={plans}
        busy={busy}
        onClose={() => setAssigning(null)}
        onAssign={assign}
      />
    </>
  );
}

Subscriptions.layout = [AdminLayout];
export default Subscriptions;
