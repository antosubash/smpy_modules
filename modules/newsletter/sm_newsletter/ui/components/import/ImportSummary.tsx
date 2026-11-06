/** The staged files (name, kind, rows) and the totals with duplicates and invalid. */

import { Badge } from '@simple-module-py/ui/components/ui/badge';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@simple-module-py/ui/components/ui/table';

import { keys, useT } from '../../utils/i18n';
import type { ImportJob, ImportKind } from '../../utils/importTypes';

const copy = keys.newsletter.import;

export const KIND_LABELS: Record<ImportKind, string> = {
  subscribed: copy.kinds.subscribed,
  unsubscribed: copy.kinds.unsubscribed,
  cleaned: copy.kinds.cleaned,
  ignored: copy.kinds.ignored,
};

export function ImportSummary({ job }: { job: ImportJob }) {
  const { t } = useT();
  return (
    <div className="grid gap-3">
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>{t(copy.files)}</TableHead>
            <TableHead>{t(copy.kind)}</TableHead>
            <TableHead className="text-right">{t(copy.rows)}</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {job.files.map((file, index) => (
            // biome-ignore lint/suspicious/noArrayIndexKey: two files may share a name
            <TableRow key={index}>
              <TableCell>{file.name}</TableCell>
              <TableCell>
                <Badge variant="secondary">{t(KIND_LABELS[file.kind])}</Badge>
              </TableCell>
              <TableCell className="text-right">{file.rows}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      <p className="text-sm">
        {t(copy.summary, { total: job.total, files: job.files.length })}
        {' · '}
        {t(copy.duplicates)}: {job.duplicates}
        {' · '}
        {t(copy.invalid)}: {job.invalid}
      </p>
      <p className="text-sm text-muted-foreground">{t(copy.suppression_note)}</p>
    </div>
  );
}
