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
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>Organisation</TableHead>
          <TableHead>Plan</TableHead>
          <TableHead>Status</TableHead>
          <TableHead>Members</TableHead>
          <TableHead>Period end</TableHead>
          <TableHead className="text-right">Actions</TableHead>
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
                    {row.suspended_by_billing ? 'Suspended (unpaid)' : 'Suspended'}
                  </Badge>
                )}
              </div>
              <div className="font-mono text-xs text-muted-foreground">{row.tenant_slug}</div>
            </TableCell>
            <TableCell>
              {row.plan_name}
              {row.interval && <span className="text-muted-foreground"> · {row.interval}ly</span>}
            </TableCell>
            <TableCell>
              <StatusBadge status={row.status} />
              {row.cancel_at_period_end && (
                <div className="mt-1 text-xs text-muted-foreground">Ends at period end</div>
              )}
            </TableCell>
            <TableCell>
              {row.members}
              {row.quantity !== null && row.quantity !== row.members && (
                <span className="text-xs text-muted-foreground"> (billed {row.quantity})</span>
              )}
            </TableCell>
            <TableCell>{formatDate(row.current_period_end) || '—'}</TableCell>
            <TableCell className="text-right">
              {canManage && mode === 'assign' && (
                <Button size="sm" variant="outline" disabled={busy} onClick={() => onAssign(row)}>
                  Assign plan
                </Button>
              )}
              {canManage && mode === 'resync' && row.provider_subscription_id && (
                <Button size="sm" variant="outline" disabled={busy} onClick={() => onResync(row)}>
                  Resync
                </Button>
              )}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
