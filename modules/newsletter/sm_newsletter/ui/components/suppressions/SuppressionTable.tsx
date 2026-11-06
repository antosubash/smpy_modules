/** Suppressed addresses: fingerprint, reason, list, source and date; *Lift* where allowed. */

import { Button } from '@simple-module-py/ui/components/ui/button';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@simple-module-py/ui/components/ui/table';

import { keys, useT } from '../../utils/i18n';
import type { Suppression } from '../../utils/types';
import { REASON_LABELS, SOURCE_LABELS } from './labels';

const copy = keys.newsletter.suppressions;

interface Props {
  items: Suppression[];
  onLift: (s: Suppression) => void;
}

export function SuppressionTable({ items, onLift }: Props) {
  const { t, locale } = useT();
  const date = new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeStyle: 'short' });
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>{t(copy.fingerprint)}</TableHead>
          <TableHead>{t(copy.reason)}</TableHead>
          <TableHead>{t(copy.list)}</TableHead>
          <TableHead>{t(copy.source)}</TableHead>
          <TableHead>{t(copy.created)}</TableHead>
          <TableHead>
            <span className="sr-only">{t(copy.lift.action)}</span>
          </TableHead>
        </TableRow>
      </TableHeader>
      <TableBody>
        {items.map((s) => (
          <TableRow key={s.id}>
            <TableCell className="font-mono text-xs">{s.fingerprint}</TableCell>
            <TableCell>{t(REASON_LABELS[s.reason] ?? copy.reason)}</TableCell>
            <TableCell>{s.list_type_key || t(copy.all_lists)}</TableCell>
            <TableCell className="text-muted-foreground">
              {SOURCE_LABELS[s.source] ? t(SOURCE_LABELS[s.source]) : s.source}
            </TableCell>
            <TableCell className="text-muted-foreground">
              {date.format(new Date(s.created_at))}
            </TableCell>
            <TableCell className="text-right">
              {s.liftable && s.reason !== 'complaint' && (
                <Button type="button" variant="ghost" size="sm" onClick={() => onLift(s)}>
                  {t(copy.lift.action)}
                </Button>
              )}
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
