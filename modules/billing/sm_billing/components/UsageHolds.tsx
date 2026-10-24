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
import { keys, useT } from '../utils/i18n';
import type { UsageHold } from '../utils/types';
import { formatDateTime, holdStatusLabel } from '../utils/usage';

interface Props {
  holds: UsageHold[] | null;
  canManage: boolean;
  busy: boolean;
  onRelease: (hold: UsageHold) => void;
}

/** The holds that make up the gauges: held (expiring) or committed (until released). */
export function UsageHolds({ holds, canManage, busy, onRelease }: Props) {
  const { t, locale } = useT();
  const c = keys.billing.admin_usage.holds;
  return (
    <section className="space-y-3" aria-labelledby="usage-holds-title">
      <h3 id="usage-holds-title" className="text-sm font-semibold">
        {t(c.title)}
      </h3>
      {holds === null ? (
        <p className="text-sm text-muted-foreground">
          {t(keys.billing.admin_usage.ledger.loading)}
        </p>
      ) : holds.length === 0 ? (
        <p className="text-sm text-muted-foreground">{t(c.empty)}</p>
      ) : (
        <div className="rounded-md border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t(c.meter)}</TableHead>
                <TableHead className="text-right">{t(c.quantity)}</TableHead>
                <TableHead>{t(c.status)}</TableHead>
                <TableHead>{t(c.expires)}</TableHead>
                <TableHead>{t(c.source)}</TableHead>
                {canManage && <TableHead className="text-right" />}
              </TableRow>
            </TableHeader>
            <TableBody>
              {holds.map((hold) => (
                <TableRow key={hold.id} data-hold={hold.id}>
                  <TableCell className="font-mono text-xs">{hold.meter}</TableCell>
                  <TableCell className="text-right tabular-nums">{hold.quantity}</TableCell>
                  <TableCell>
                    <Badge variant="outline">{holdStatusLabel(hold.status)}</Badge>
                  </TableCell>
                  <TableCell className="whitespace-nowrap text-xs">
                    {hold.expires_at ? formatDateTime(hold.expires_at, locale) : t(c.never)}
                  </TableCell>
                  <TableCell className="text-xs">
                    <div>{hold.source}</div>
                    <div
                      className="max-w-40 truncate font-mono text-muted-foreground"
                      title={hold.idempotency_key}
                    >
                      {hold.idempotency_key}
                    </div>
                  </TableCell>
                  {canManage && (
                    <TableCell className="text-right">
                      <Button
                        size="sm"
                        variant="outline"
                        disabled={busy}
                        onClick={() => onRelease(hold)}
                      >
                        {t(c.release)}
                      </Button>
                    </TableCell>
                  )}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </section>
  );
}
