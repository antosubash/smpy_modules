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
import type { SubjectMode, SubscriptionRow } from '../utils/types';
import { StatusBadge } from './StatusBadge';

interface Props {
  rows: SubscriptionRow[];
  canManage: boolean;
  /** Stripe: resync from the provider. Manual: assign a plan by hand. */
  mode: 'resync' | 'assign';
  busy: boolean;
  onResync: (row: SubscriptionRow) => void;
  onAssign: (row: SubscriptionRow) => void;
  /** "user": each row is a user (named by email), and there are no members. */
  subjectMode?: SubjectMode;
}

export function SubscriptionsTable({
  rows,
  canManage,
  mode,
  busy,
  onResync,
  onAssign,
  subjectMode = 'tenant',
}: Props) {
  const { t, locale } = useT();
  const c = keys.billing.subscriptions_table;
  const byUser = subjectMode === 'user';
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>{byUser ? t(c.col_user) : t(c.col_organisation)}</TableHead>
          <TableHead>{t(c.col_plan)}</TableHead>
          <TableHead>{t(c.col_status)}</TableHead>
          {!byUser && <TableHead>{t(c.col_members)}</TableHead>}
          <TableHead>{t(c.col_period_end)}</TableHead>
          <TableHead className="sticky right-0 bg-background text-right">
            {t(c.col_actions)}
          </TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((row) => (
          <TableRow key={row.tenant_id}>
            <TableCell>
              <div className="flex flex-wrap items-center gap-2 font-medium">
                <span className="block max-w-32 truncate sm:max-w-64" title={row.tenant_name}>
                  {row.tenant_name}
                </span>
                {row.tenant_status === 'suspended' && (
                  <Badge variant="destructive">
                    {row.suspended_by_billing ? t(c.suspended_unpaid) : t(c.suspended)}
                  </Badge>
                )}
              </div>
              {row.tenant_slug && (
                <div className="font-mono text-xs text-muted-foreground">{row.tenant_slug}</div>
              )}
            </TableCell>
            <TableCell>
              <span className="block max-w-32 truncate sm:max-w-64" title={row.plan_name}>
                {row.plan_name}
              </span>
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
            {!byUser && (
              <TableCell>
                {row.members}
                {row.quantity !== null && row.quantity !== row.members && (
                  <span className="text-xs text-muted-foreground">
                    {` ${t(c.billed, { quantity: row.quantity })}`}
                  </span>
                )}
              </TableCell>
            )}
            <TableCell>{formatDate(row.current_period_end, locale) || '—'}</TableCell>
            <TableCell className="sticky right-0 bg-background text-right">
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
