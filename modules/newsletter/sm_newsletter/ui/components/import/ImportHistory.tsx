/** Recent imports; *Open* reloads one (a running import is resumed in the view). */

import { Button } from '@simple-module-py/ui/components/ui/button';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@simple-module-py/ui/components/ui/table';
import { useEffect, useState } from 'react';

import { errorMessage } from '../../utils/http';
import { keys, useT } from '../../utils/i18n';
import { listImports } from '../../utils/importApi';
import type { ImportSummary } from '../../utils/importTypes';
import { STATUS_LABELS } from './ImportProgress';

const copy = keys.newsletter.import;

interface Props {
  /** Changes whenever the open job does; the list is fetched again. */
  refreshKey: string;
  onOpen: (id: number) => void;
}

export function ImportHistory({ refreshKey, onOpen }: Props) {
  const { t, locale } = useT();
  const [items, setItems] = useState<ImportSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const date = new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeStyle: 'short' });

  // biome-ignore lint/correctness/useExhaustiveDependencies: refreshKey is the trigger
  useEffect(() => {
    let current = true;
    listImports()
      .then((found) => {
        if (!current) return;
        setItems(found);
        setError(null);
      })
      .catch((e) => current && setError(errorMessage(e, t)));
    return () => {
      current = false;
    };
  }, [refreshKey, t]);

  if (error)
    return (
      <p role="alert" className="text-sm text-destructive">
        {error}
      </p>
    );
  if (items === null) return null;
  if (items.length === 0)
    return <p className="text-sm text-muted-foreground">{t(copy.history_empty)}</p>;
  return (
    <Table>
      <TableHeader>
        <TableRow>
          <TableHead>{t(copy.list_label)}</TableHead>
          <TableHead>{t(copy.status_label)}</TableHead>
          <TableHead>{t(copy.rows)}</TableHead>
          <TableHead />
        </TableRow>
      </TableHeader>
      <TableBody>
        {items.map((item) => (
          <TableRow key={item.id}>
            <TableCell>
              {item.list_type_key}
              <span className="ml-2 text-xs text-muted-foreground">
                {date.format(new Date(item.created_at))}
              </span>
            </TableCell>
            <TableCell>{t(STATUS_LABELS[item.status])}</TableCell>
            <TableCell>
              {item.processed} / {item.total}
            </TableCell>
            <TableCell className="text-right">
              <Button
                type="button"
                variant="ghost"
                size="sm"
                aria-label={t(copy.open_import, { id: item.id })}
                onClick={() => onOpen(item.id)}
              >
                {t(copy.open)}
              </Button>
            </TableCell>
          </TableRow>
        ))}
      </TableBody>
    </Table>
  );
}
