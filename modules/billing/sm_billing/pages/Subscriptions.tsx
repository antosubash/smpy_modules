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
import { STATUS_LABEL } from '../utils/format';
import type { AdminCommon, Plan, SubscriptionRow, SubscriptionStatus } from '../utils/types';

interface Props extends AdminCommon {
  rows: SubscriptionRow[];
  plans: Plan[];
  status_filter: string;
}

const VIEW_URL = '/admin/billing/subscriptions';

function Subscriptions() {
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
      toast.success(`${row.tenant_name} resynced from Stripe`);
    });

  const assign = (planId: number, status: SubscriptionStatus) =>
    run(async () => {
      if (!assigning) return;
      await api(`${ADMIN_API}/subscriptions/${assigning.tenant_id}/assign`, csrf_token, {
        body: { plan_id: planId, status },
      });
      toast.success(`Plan assigned to ${assigning.tenant_name}`);
      setAssigning(null);
    });

  const filter = (value: string) =>
    router.get(VIEW_URL, value ? { status: value } : {}, { preserveScroll: true });

  return (
    <>
      <Head title="Billing subscriptions" />
      <PageShell
        title="Billing"
        description={
          checkout_available
            ? 'Every organisation and its Stripe subscription.'
            : `Provider: ${provider}. Assign plans by hand; nobody is charged.`
        }
      >
        <AdminNav active="subscriptions" />
        <div className="mb-4 flex max-w-xs items-center gap-2">
          <Label htmlFor="status-filter" className="shrink-0">
            Status
          </Label>
          <NativeSelect
            id="status-filter"
            value={status_filter}
            onChange={(e) => filter(e.target.value)}
          >
            <NativeSelectOption value="">All</NativeSelectOption>
            {(Object.keys(STATUS_LABEL) as SubscriptionStatus[]).map((s) => (
              <NativeSelectOption key={s} value={s}>
                {STATUS_LABEL[s]}
              </NativeSelectOption>
            ))}
          </NativeSelect>
        </div>
        <Card className="overflow-hidden p-0">
          {rows.length === 0 ? (
            <EmptyState
              icon={Building2}
              title="No organisations"
              description={status_filter ? 'None match this status.' : 'Nobody has signed up yet.'}
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
