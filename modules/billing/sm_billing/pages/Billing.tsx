import { Head, router, usePage } from '@inertiajs/react';
import { ConfirmActionDialog } from '@simple-module-py/ui/components/ConfirmActionDialog';
import { InlineBanner } from '@simple-module-py/ui/components/InlineBanner';
import { PageShell } from '@simple-module-py/ui/components/PageShell';
import { SegmentedControl } from '@simple-module-py/ui/components/SegmentedControl';
import { AuthenticatedLayout } from '@simple-module-py/ui/layouts/AuthenticatedLayout';
import { ArrowRightLeft, Info, Loader2 } from 'lucide-react';
import { useCallback, useState } from 'react';
import { toast } from 'sonner';
import { CurrentPlanCard } from '../components/CurrentPlanCard';
import { PlanCard } from '../components/PlanCard';
import { useCheckoutPolling } from '../hooks/useCheckoutPolling';
import { api, BILLING_API } from '../utils/api';
import { type PlanCta, planCta, priceLabel } from '../utils/format';
import type { Interval, Plan, Status } from '../utils/types';

interface Props {
  status: Status;
  plans: Plan[];
  can_manage: boolean;
  csrf_token: string;
  checkout: string;
}

function Billing() {
  const { status, plans, can_manage, csrf_token, checkout } = usePage<{ props: Props }>()
    .props as unknown as Props;
  const [interval, setBillingInterval] = useState<Interval>(
    status.subscription?.interval ?? 'month',
  );
  const [busy, setBusy] = useState(false);
  const [pending, setPending] = useState<{ plan: Plan; cta: PlanCta } | null>(null);
  const reload = useCallback(() => router.reload(), []);
  const polling = useCheckoutPolling(checkout === 'success', csrf_token, reload);
  const sellsYearly = plans.some((p) => p.stripe_price_year);

  async function run(work: () => Promise<void>) {
    setBusy(true);
    try {
      await work();
    } catch (err) {
      toast.error((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  const openPortal = () =>
    run(async () => {
      const { url } = await api<{ url: string }>(`${BILLING_API}/portal`, csrf_token, {
        body: {},
      });
      window.location.assign(url);
    });

  function choose(plan: Plan, cta: PlanCta) {
    if (cta === 'checkout') {
      void run(async () => {
        const { url } = await api<{ url: string }>(`${BILLING_API}/checkout`, csrf_token, {
          body: { plan_id: plan.id, interval },
        });
        window.location.assign(url);
      });
      return;
    }
    setPending({ plan, cta });
  }

  const confirmChange = () =>
    run(async () => {
      if (!pending) return;
      await api<Status>(`${BILLING_API}/change-plan`, csrf_token, {
        body: { plan_id: pending.plan.id, interval },
      });
      toast.success(
        pending.cta === 'downgrade'
          ? 'Your plan ends at the end of the billing period.'
          : `Switched to ${pending.plan.name}.`,
      );
      setPending(null);
      reload();
    });

  return (
    <>
      <Head title="Billing" />
      <PageShell title="Billing" description="Your organisation's plan, seats and payment.">
        <div className="space-y-8">
          {polling === 'waiting' && (
            <InlineBanner
              icon={Loader2}
              title="Activating your subscription…"
              description="Stripe confirmed the payment; this page updates once it reaches us."
            />
          )}
          {polling === 'timeout' && (
            <InlineBanner
              icon={Info}
              tone="warning"
              title="Still waiting for Stripe"
              description="Your payment went through, but the confirmation is late. Refresh in a minute."
            />
          )}
          {checkout === 'cancel' && (
            <InlineBanner icon={Info} title="Checkout cancelled — nothing was charged." />
          )}
          <CurrentPlanCard
            status={status}
            canManage={can_manage}
            busy={busy}
            onPortal={openPortal}
          />

          <section className="space-y-4">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <h2 className="text-lg font-semibold">Plans</h2>
              {sellsYearly && (
                <SegmentedControl
                  aria-label="Billing period"
                  value={interval}
                  onChange={setBillingInterval}
                  options={[
                    { value: 'month', label: 'Monthly' },
                    { value: 'year', label: 'Yearly' },
                  ]}
                />
              )}
            </div>
            {!can_manage && (
              <p className="text-sm text-muted-foreground">
                Only the organisation owner can change the plan.
              </p>
            )}
            {!status.checkout_available && can_manage && (
              <p className="text-sm text-muted-foreground">
                Online payment is not set up here — contact the site administrator to change plan.
              </p>
            )}
            <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
              {plans.map((plan) => (
                <PlanCard
                  key={plan.id}
                  plan={plan}
                  interval={interval}
                  cta={planCta(status, plan, interval)}
                  canManage={can_manage}
                  busy={busy}
                  onChoose={choose}
                />
              ))}
            </div>
          </section>
        </div>
      </PageShell>
      <ConfirmActionDialog
        open={pending !== null}
        onOpenChange={(open) => !open && setPending(null)}
        tone="primary"
        icon={ArrowRightLeft}
        title={pending?.cta === 'downgrade' ? 'Downgrade to the free plan?' : 'Change plan?'}
        description={
          pending?.cta === 'downgrade'
            ? 'Your paid plan stays active until the end of the current period, then ends.'
            : `You will be moved to ${pending?.plan.name} (${
                pending ? priceLabel(pending.plan, interval) : ''
              }). Stripe prorates the difference on your next invoice.`
        }
        confirmLabel={pending?.cta === 'downgrade' ? 'Downgrade' : 'Change plan'}
        cancelLabel="Keep current plan"
        busy={busy}
        onConfirm={confirmChange}
      />
    </>
  );
}

Billing.layout = [AuthenticatedLayout];
export default Billing;
