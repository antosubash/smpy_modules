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
  const sub = status.subscription;
  const { used, limit } = status.seats;
  const seats = limit === null ? `${used} members` : `${used} of ${limit} seats used`;
  const portal = canManage && status.portal_available;

  return (
    <div className="space-y-4">
      {sub?.status === 'past_due' && (
        <InlineBanner
          icon={AlertTriangle}
          tone="warning"
          title="Your last payment failed"
          description="Stripe is retrying the charge. Update your payment method to keep your plan."
          action={
            portal ? (
              <Button size="sm" onClick={onPortal} disabled={busy}>
                Update payment method
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
          <CardDescription>{status.plan.description || 'Your current plan.'}</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-wrap items-end justify-between gap-4">
          <dl className="grid gap-1 text-sm">
            <div className="flex gap-2">
              <dt className="text-muted-foreground">Seats</dt>
              <dd>{seats}</dd>
            </div>
            {sub?.status === 'trialing' && sub.trial_end && (
              <div className="flex gap-2">
                <dt className="text-muted-foreground">Trial ends</dt>
                <dd>{formatDate(sub.trial_end)}</dd>
              </div>
            )}
            {sub?.current_period_end && (
              <div className="flex gap-2">
                <dt className="text-muted-foreground">
                  {sub.cancel_at_period_end ? 'Ends on' : 'Renews on'}
                </dt>
                <dd>{formatDate(sub.current_period_end)}</dd>
              </div>
            )}
          </dl>
          {portal && (
            <Button variant="outline" onClick={onPortal} disabled={busy}>
              <CreditCard aria-hidden="true" />
              Manage payment &amp; invoices
            </Button>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
