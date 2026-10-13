import { Badge } from '@simple-module-py/ui/components/ui/badge';
import { Button } from '@simple-module-py/ui/components/ui/button';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@simple-module-py/ui/components/ui/table';
import { formatDate } from '../utils/format';
import { keys, useT } from '../utils/i18n';
import type { SubscriptionRow } from '../utils/types';
import { StatusBadge } from './StatusBadge';

interface Props {
  rows: SubscriptionRow[];
  canManage: boolean;
  /** Stripe: resync from the provider. Manual: assign a plan by hand. */
  mode: 'resync' | 'assign';
  busy: boolean;
  onResync: (row: SubscriptionRow) => void;
  onAssign: (row: SubscriptionRow) => void;
}

export function SubscriptionsTable({ rows, canManage, mode, busy, onResync, onAssign }: Props) {
  const { t } = useT();
  const c = keys.billing.subscriptions_table;
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>{t(c.col_organisation)}</TableHead>
          <TableHead>{t(c.col_plan)}</TableHead>
          <TableHead>{t(c.col_status)}</TableHead>
          <TableHead>{t(c.col_members)}</TableHead>
          <TableHead>{t(c.col_period_end)}</TableHead>
          <TableHead className="text-right">{t(c.col_actions)}</TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((row) => (
          <TableRow key={row.tenant_id}>
            <TableCell>
              <div className="flex flex-wrap items-center gap-2 font-medium">
                {row.tenant_name}
                {row.tenant_status === 'suspended' && (
                  <Badge variant="destructive">
                    {row.suspended_by_billing ? t(c.suspended_unpaid) : t(c.suspended)}
                  </Badge>
                )}
              </div>
              <div className="font-mono text-xs text-muted-foreground">{row.tenant_slug}</div>
            </TableCell>
            <TableCell>
              {row.plan_name}
              {row.interval && (
                <span className="text-muted-foreground">
                  {` · ${row.interval === 'month' ? t(c.interval_month) : t(c.interval_year)}`}
                </span>
              )}
            </TableCell>
            <TableCell>
              <StatusBadge status={row.status} />
              {row.cancel_at_period_end && (
                <div className="mt-1 text-xs text-muted-foreground">{t(c.ends_at_period_end)}</div>
              )}
            </TableCell>
            <TableCell>
              {row.members}
              {row.quantity !== null && row.quantity !== row.members && (
                <span className="text-xs text-muted-foreground">
                  {` ${t(c.billed, { quantity: row.quantity })}`}
                </span>
              )}
            </TableCell>
            <TableCell>{formatDate(row.current_period_end) || '—'}</TableCell>
            <TableCell className="text-right">
              {canManage && mode === 'assign' && (
                <Button size="sm" variant="outline" disabled={busy} onClick={() => onAssign(row)}>
                  {t(c.assign_plan)}
                </Button>
              )}
              {canManage && mode === 'resync' && row.provider_subscription_id && (
                <Button size="sm" variant="outline" disabled={busy} onClick={() => onResync(row)}>
                  {t(c.resync)}
                </Button>
              )}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
