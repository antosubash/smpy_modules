import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@simple-module-py/ui/components/ui/table';

import { keys, useT } from '../../utils/i18n';
import type { LinkStat } from '../../utils/types';

const copy = keys.newsletter.report;

/** Tracked links with their clicks. A URL is text, never an anchor: the admin must not click through to it. */
export function LinkTable({ links, trackingOff }: { links: LinkStat[]; trackingOff: boolean }) {
  const { t } = useT();
  return (
    <section>
      <h2 className="mb-2 text-lg font-semibold">{t(copy.links.title)}</h2>
      {trackingOff && (
        <p className="mb-2 text-sm text-muted-foreground">{t(copy.tracking_off.clicks)}</p>
      )}
      {links.length === 0 ? (
        // With click tracking off the note already explains the empty table.
        !trackingOff && (
          <p className="rounded-lg border border-dashed p-6 text-center text-sm text-muted-foreground">
            {t(copy.links.empty)}
          </p>
        )
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>#</TableHead>
              <TableHead>{t(copy.links.url)}</TableHead>
              <TableHead className="text-right">{t(copy.links.unique)}</TableHead>
              <TableHead className="text-right">{t(copy.links.total)}</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {links.map((l) => (
              <TableRow key={l.position}>
                <TableCell>{l.position}</TableCell>
                <TableCell className="max-w-md">
                  <span className="block truncate font-mono text-xs" title={l.url}>
                    {l.url}
                  </span>
                </TableCell>
                <TableCell className="text-right tabular-nums">{l.unique}</TableCell>
                <TableCell className="text-right tabular-nums">{l.total}</TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}
    </section>
  );
}
