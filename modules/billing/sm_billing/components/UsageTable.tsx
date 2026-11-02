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
import type { SubjectMode, UsageRow } from '../utils/types';
import { formatQuantity, meterLabel, usageTone } from '../utils/usage';
import { UsageBar } from './UsageBar';

interface Props {
  rows: UsageRow[];
  onOpen: (row: UsageRow) => void;
  /** "user": each row is a user, named by email. */
  subjectMode?: SubjectMode;
}

/** Organisation (or user) x meter for the period, fullest first (the server's order). */
export function UsageTable({ rows, onOpen, subjectMode = 'tenant' }: Props) {
  const { t, locale } = useT();
  const c = keys.billing.admin_usage;
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>
            {t(subjectMode === 'user' ? c.columns.user : c.columns.organisation)}
          </TableHead>
          <TableHead>{t(c.columns.meter)}</TableHead>
          <TableHead className="text-right">{t(c.columns.used)}</TableHead>
          <TableHead className="text-right">{t(c.columns.limit)}</TableHead>
          <TableHead className="min-w-32">{t(c.columns.percent)}</TableHead>
          <TableHead>{t(c.columns.period)}</TableHead>
          <TableHead className="sticky right-0 bg-background text-right">
            {t(c.columns.actions)}
          </TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {rows.map((row) => {
          const label = meterLabel(row.label_key, row.meter);
          return (
            <TableRow key={`${row.tenant_id}:${row.meter}`}>
              <TableCell>
                <span
                  className="block max-w-32 truncate font-medium sm:max-w-64"
                  title={row.tenant_name}
                >
                  {row.tenant_name}
                </span>
                <span className="font-mono text-xs text-muted-foreground">
                  {row.tenant_slug || row.tenant_id}
                </span>
              </TableCell>
              <TableCell>
                <div className="flex flex-wrap items-center gap-1.5">
                  <span>{label}</span>
                  <Badge variant="outline">
                    {row.kind === 'gauge' ? t(c.kind.gauge) : t(c.kind.counter)}
                  </Badge>
                  {!row.registered && <Badge variant="secondary">{t(c.unregistered)}</Badge>}
                </div>
                {label !== row.meter && (
                  <span className="font-mono text-xs text-muted-foreground">{row.meter}</span>
                )}
              </TableCell>
              <TableCell className="text-right tabular-nums">
                {formatQuantity(row.used, row.unit, locale)}
              </TableCell>
              <TableCell className="text-right tabular-nums">
                {row.limit === null
                  ? t(keys.billing.usage.unlimited)
                  : formatQuantity(row.limit, row.unit, locale)}
              </TableCell>
              <TableCell>
                {row.percent === null ? (
                  <span className="text-muted-foreground">—</span>
                ) : (
                  <div className="flex items-center gap-2">
                    <UsageBar
                      percent={row.percent}
                      tone={usageTone(row.percent)}
                      label={label}
                      className="w-20"
                    />
                    <span className="text-xs tabular-nums">{`${row.percent}%`}</span>
                  </div>
                )}
              </TableCell>
              <TableCell className="text-sm">
                {row.period_end
                  ? `${formatDate(row.period_start, locale)} – ${formatDate(row.period_end, locale)}`
                  : t(c.no_period)}
              </TableCell>
              <TableCell className="sticky right-0 bg-background text-right">
                <Button size="sm" variant="outline" onClick={() => onOpen(row)}>
                  {t(c.details)}
                </Button>
              </TableCell>
            </TableRow>
          );
        })}
      </TableBody>
    </Table>
  );
}
