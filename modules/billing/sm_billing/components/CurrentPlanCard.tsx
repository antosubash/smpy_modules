import { InlineBanner } from '@simple-module-py/ui/components/InlineBanner';
import { Button } from '@simple-module-py/ui/components/ui/button';
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@simple-module-py/ui/components/ui/card';
import { AlertTriangle, CreditCard } from 'lucide-react';
import { formatDate } from '../utils/format';
import { keys, useT } from '../utils/i18n';
import { seatsLabel } from '../utils/seats';
import type { Status } from '../utils/types';
import { StatusBadge } from './StatusBadge';

interface Props {
  status: Status;
  canManage: boolean;
  busy: boolean;
  onPortal: () => void;
}

/** The plan in force, its renewal or end date, seats, and the payment-trouble banner. */
export function CurrentPlanCard({ status, canManage, busy, onPortal }: Props) {
  const { t } = useT();
  const sub = status.subscription;
  const { used, limit } = status.seats;
  const seats = seatsLabel(used, limit);
  const portal = canManage && status.portal_available;

  return (
    <div className="space-y-4">
      {sub?.status === 'past_due' && (
        <InlineBanner
          icon={AlertTriangle}
          tone="warning"
          title={t(keys.billing.current_plan.payment_failed_title)}
          description={t(keys.billing.current_plan.payment_failed_description)}
          action={
            portal ? (
              <Button size="sm" onClick={onPortal} disabled={busy}>
                {t(keys.billing.current_plan.update_payment)}
              </Button>
            ) : undefined
          }
        />
      )}
      <Card>
        <CardHeader>
          <CardTitle className="flex flex-wrap items-center gap-2">
            {status.plan.name}
            {sub && <StatusBadge status={sub.status} />}
          </CardTitle>
          <CardDescription>
            {status.plan.description || t(keys.billing.current_plan.default_description)}
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-wrap items-end justify-between gap-4">
          <dl className="grid gap-1 text-sm">
            <div className="flex gap-2">
              <dt className="text-muted-foreground">{t(keys.billing.current_plan.seats)}</dt>
              <dd>{seats}</dd>
            </div>
            {sub?.status === 'trialing' && sub.trial_end && (
              <div className="flex gap-2">
                <dt className="text-muted-foreground">{t(keys.billing.current_plan.trial_ends)}</dt>
                <dd>{formatDate(sub.trial_end)}</dd>
              </div>
            )}
            {sub?.current_period_end && (
              <div className="flex gap-2">
                <dt className="text-muted-foreground">
                  {sub.cancel_at_period_end
                    ? t(keys.billing.current_plan.ends_on)
                    : t(keys.billing.current_plan.renews_on)}
                </dt>
                <dd>{formatDate(sub.current_period_end)}</dd>
              </div>
            )}
          </dl>
          {portal && (
            <Button variant="outline" onClick={onPortal} disabled={busy}>
              <CreditCard aria-hidden="true" />
              {t(keys.billing.current_plan.manage_portal)}
            </Button>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
