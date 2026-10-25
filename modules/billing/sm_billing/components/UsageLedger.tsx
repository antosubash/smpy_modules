import { PaginationBar } from '@simple-module-py/ui/components/PaginationBar';
import { Badge } from '@simple-module-py/ui/components/ui/badge';
import { Label } from '@simple-module-py/ui/components/ui/label';
import { NativeSelect, NativeSelectOption } from '@simple-module-py/ui/components/ui/native-select';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@simple-module-py/ui/components/ui/table';
import { keys, useT } from '../utils/i18n';
import type { Paged, UsageEvent } from '../utils/types';
import { formatDateTime, kindLabel, USAGE_KINDS } from '../utils/usage';

interface Props {
  ledger: Paged<UsageEvent> | null;
  failed: boolean;
  kind: string;
  onKind: (kind: string) => void;
  onPage: (page: number) => void;
}

/** The ledger: every change to a counter, newest first, with who and why for adjustments. */
export function UsageLedger({ ledger, failed, kind, onKind, onPage }: Props) {
  const { t, locale } = useT();
  const c = keys.billing.admin_usage.ledger;
  return (
    <section className="space-y-3" aria-labelledby="usage-ledger-title">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <h3 id="usage-ledger-title" className="text-sm font-semibold">
          {t(c.title)}
        </h3>
        <div className="flex items-center gap-2">
          <Label htmlFor="usage-kind" className="shrink-0">
            {t(c.kind_filter)}
          </Label>
          <NativeSelect id="usage-kind" value={kind} onChange={(e) => onKind(e.target.value)}>
            <NativeSelectOption value="">{t(c.all_kinds)}</NativeSelectOption>
            {USAGE_KINDS.map((k) => (
              <NativeSelectOption key={k} value={k}>
                {kindLabel(k)}
              </NativeSelectOption>
            ))}
          </NativeSelect>
        </div>
      </div>
      {failed ? (
        <p className="text-sm text-destructive">{t(keys.billing.admin_usage.ledger.load_failed)}</p>
      ) : ledger === null ? (
        <p className="text-sm text-muted-foreground">{t(c.loading)}</p>
      ) : ledger.items.length === 0 ? (
        <p className="text-sm text-muted-foreground">{t(c.empty)}</p>
      ) : (
        <div className="rounded-md border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t(c.time)}</TableHead>
                <TableHead>{t(c.kind)}</TableHead>
                <TableHead>{t(c.meter)}</TableHead>
                <TableHead className="text-right">{t(c.quantity)}</TableHead>
                <TableHead>{t(c.source)}</TableHead>
                <TableHead>{t(c.reason)}</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {ledger.items.map((event) => (
                <TableRow key={event.id} data-kind={event.kind}>
                  <TableCell className="whitespace-nowrap text-xs">
                    {formatDateTime(event.recorded_at, locale)}
                  </TableCell>
                  <TableCell>
                    <Badge variant={event.kind === 'adjust' ? 'default' : 'outline'}>
                      {kindLabel(event.kind)}
                    </Badge>
                  </TableCell>
                  <TableCell className="font-mono text-xs">{event.meter}</TableCell>
                  <TableCell className="text-right tabular-nums">
                    {event.quantity > 0 ? `+${event.quantity}` : event.quantity}
                  </TableCell>
                  <TableCell className="text-xs">
                    <div>{event.source}</div>
                    <div
                      className="max-w-40 truncate font-mono text-muted-foreground"
                      title={event.idempotency_key}
                    >
                      {event.idempotency_key}
                    </div>
                  </TableCell>
                  <TableCell className="text-xs">
                    {event.reason && (
                      <div className="max-w-56 whitespace-normal wrap-anywhere">{event.reason}</div>
                    )}
                    {event.actor && (
                      <div className="text-muted-foreground">
                        {`${t(c.actor)} `}
                        <span className="font-mono">{event.actor}</span>
                      </div>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          <PaginationBar
            page={ledger.page}
            perPage={ledger.per_page}
            total={ledger.total}
            onPageChange={onPage}
            hideWhenSinglePage
          />
        </div>
      )}
    </section>
  );
}
