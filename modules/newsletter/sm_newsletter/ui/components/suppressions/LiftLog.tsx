/** The audit trail: every lift, newest first, paged. */

import { Button } from '@simple-module-py/ui/components/ui/button';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@simple-module-py/ui/components/ui/table';
import { useEffect, useRef, useState } from 'react';

import { PAGE_SIZE } from '../../hooks/useSuppressionList';
import { api, errorMessage } from '../../utils/api';
import { keys, useT } from '../../utils/i18n';
import type { LiftPage } from '../../utils/types';
import { REASON_LABELS } from './labels';

const copy = keys.newsletter.suppressions;

export function LiftLog() {
  const { t, locale } = useT();
  const date = new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeStyle: 'short' });
  const [offset, setOffset] = useState(0);
  const [page, setPage] = useState<LiftPage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const tRef = useRef(t);
  tRef.current = t;

  useEffect(() => {
    const controller = new AbortController();
    api
      .listLifts({ offset }, controller.signal)
      .then((p) => {
        setError(null);
        setPage(p);
      })
      .catch((e) => {
        if (!controller.signal.aborted) setError(errorMessage(e, tRef.current));
      });
    return () => controller.abort();
  }, [offset]);

  if (error)
    return (
      <p role="alert" className="text-sm text-destructive">
        {error}
      </p>
    );
  if (page === null) return null;
  if (page.items.length === 0)
    return (
      <div className="rounded-lg border border-dashed p-8 text-center">
        <p className="font-medium">{t(copy.log.empty)}</p>
      </div>
    );

  return (
    <>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>{t(copy.fingerprint)}</TableHead>
            <TableHead>{t(copy.reason)}</TableHead>
            <TableHead>{t(copy.list)}</TableHead>
            <TableHead>{t(copy.log.suppressed_at)}</TableHead>
            <TableHead>{t(copy.log.lifted_at)}</TableHead>
            <TableHead>{t(copy.log.lifted_by)}</TableHead>
            <TableHead>{t(copy.log.note)}</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {page.items.map((l) => (
            <TableRow key={l.id}>
              <TableCell className="font-mono text-xs">{l.fingerprint}</TableCell>
              <TableCell>{t(REASON_LABELS[l.reason] ?? copy.reason)}</TableCell>
              <TableCell>{l.list_type_key || t(copy.all_lists)}</TableCell>
              <TableCell className="text-muted-foreground">
                {date.format(new Date(l.suppressed_at))}
              </TableCell>
              <TableCell className="text-muted-foreground">
                {date.format(new Date(l.lifted_at))}
              </TableCell>
              <TableCell>{l.lifted_by ?? ''}</TableCell>
              <TableCell className="max-w-xs whitespace-normal">{l.note}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      <div className="mt-4 flex items-center justify-between text-sm text-muted-foreground">
        <span>
          {t(keys.newsletter.campaigns.showing, {
            from: offset + 1,
            to: offset + page.items.length,
            total: page.total,
          })}
        </span>
        <div className="flex gap-2">
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={offset === 0}
            onClick={() => setOffset((o) => Math.max(0, o - PAGE_SIZE))}
          >
            {t(keys.newsletter.campaigns.previous)}
          </Button>
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={offset + PAGE_SIZE >= page.total}
            onClick={() => setOffset((o) => o + PAGE_SIZE)}
          >
            {t(keys.newsletter.campaigns.next)}
          </Button>
        </div>
      </div>
    </>
  );
}
