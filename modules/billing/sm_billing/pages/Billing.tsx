import { Head, router, usePage } from '@inertiajs/react';
import { ConfirmActionDialog } from '@simple-module-py/ui/components/ConfirmActionDialog';
import { InlineBanner } from '@simple-module-py/ui/components/InlineBanner';
import { PageShell } from '@simple-module-py/ui/components/PageShell';
import { SegmentedControl } from '@simple-module-py/ui/components/SegmentedControl';
import { Button } from '@simple-module-py/ui/components/ui/button';
import { AuthenticatedLayout } from '@simple-module-py/ui/layouts/AuthenticatedLayout';
import { ArrowRightLeft, Info, Loader2, Lock } from 'lucide-react';
import { useCallback, useState } from 'react';
import { toast } from 'sonner';
import { CurrentPlanCard } from '../components/CurrentPlanCard';
import { PlanCard } from '../components/PlanCard';
import { useCheckoutPolling } from '../hooks/useCheckoutPolling';
import { api, BILLING_API } from '../utils/api';
import { type PlanCta, planCta, priceLabel } from '../utils/format';
import { keys, useT } from '../utils/i18n';
import type { Interval, Plan, Status } from '../utils/types';

interface Props {
  status: Status;
  plans: Plan[];
  can_manage: boolean;
  /** Suspended for non-payment: paying is the only thing offered. */
  restore: boolean;
  csrf_token: string;
  checkout: string;
}

function Billing() {
  const { t } = useT();
  const c = keys.billing.page;
  const { status, plans, can_manage, restore, csrf_token, checkout } = usePage<{
    props: Props;
  }>().props as unknown as Props;
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
          ? t(c.toast_downgrade)
          : t(c.toast_switched, { plan: pending.plan.name }),
      );
      setPending(null);
      reload();
    });

  return (
    <>
      <Head title={t(c.title)} />
      <PageShell title={t(c.title)} description={t(c.description)}>
        <div className="space-y-8">
          {polling === 'waiting' && (
            <InlineBanner
              icon={Loader2}
              title={t(c.activating_title)}
              description={t(c.activating_description)}
            />
          )}
          {polling === 'timeout' && (
            <InlineBanner
              icon={Info}
              tone="warning"
              title={t(c.waiting_title)}
              description={t(c.waiting_description)}
            />
          )}
          {checkout === 'cancel' && <InlineBanner icon={Info} title={t(c.cancelled)} />}
          {restore && (
            <InlineBanner
              icon={Lock}
              tone="warning"
              title={t(c.suspended_title)}
              description={
                status.portal_available ? t(c.suspended_portal) : t(c.suspended_no_portal)
              }
              action={
                status.portal_available ? (
                  <Button size="sm" onClick={openPortal} disabled={busy}>
                    {t(c.pay_now)}
                  </Button>
                ) : undefined
              }
            />
          )}
          <CurrentPlanCard
            status={status}
            canManage={can_manage || restore}
            busy={busy}
            onPortal={openPortal}
          />

          <section className="space-y-4" hidden={restore}>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <h2 className="text-lg font-semibold">{t(c.plans_heading)}</h2>
              {sellsYearly && (
                <SegmentedControl
                  aria-label={t(c.period_label)}
                  value={interval}
                  onChange={setBillingInterval}
                  options={[
                    { value: 'month', label: t(c.monthly) },
                    { value: 'year', label: t(c.yearly) },
                  ]}
                />
              )}
            </div>
            {!can_manage && <p className="text-sm text-muted-foreground">{t(c.owner_only)}</p>}
            {!status.checkout_available && can_manage && (
              <p className="text-sm text-muted-foreground">{t(c.no_checkout)}</p>
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
        title={
          pending?.cta === 'downgrade' ? t(c.confirm_downgrade_title) : t(c.confirm_change_title)
        }
        description={
          pending?.cta === 'downgrade'
            ? t(c.confirm_downgrade_description)
            : t(c.confirm_change_description, {
                plan: pending?.plan.name ?? '',
                price: pending ? priceLabel(pending.plan, interval) : '',
              })
        }
        confirmLabel={pending?.cta === 'downgrade' ? t(c.confirm_downgrade) : t(c.confirm_change)}
        cancelLabel={t(c.keep_current)}
        busy={busy}
        onConfirm={confirmChange}
      />
    </>
  );
}

Billing.layout = [AuthenticatedLayout];
export default Billing;
