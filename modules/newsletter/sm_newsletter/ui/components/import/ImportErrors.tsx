/** The first rows that could not be imported, and the link to the whole list. */

import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@simple-module-py/ui/components/ui/table';

import { keys, useT } from '../../utils/i18n';
import { errorsCsvUrl } from '../../utils/importApi';
import type { ImportJob } from '../../utils/importTypes';

const copy = keys.newsletter.import;
const ROW_ERRORS = copy.row_errors as Record<string, string>;

export function ImportErrors({ job }: { job: ImportJob }) {
  const { t } = useT();
  if (job.errors_total === 0) return null;
  return (
    <div className="grid gap-3">
      <h3 className="text-sm font-medium">{t(copy.errors)}</h3>
      <Table>
        <TableHeader>
          <TableRow>
            <TableHead>{t(copy.error_file)}</TableHead>
            <TableHead>{t(copy.error_line)}</TableHead>
            <TableHead>{t(copy.error_problem)}</TableHead>
            <TableHead>{t(copy.error_field)}</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {job.errors.map((error, index) => (
            // biome-ignore lint/suspicious/noArrayIndexKey: the list has no identity of its own
            <TableRow key={index}>
              <TableCell>
                {error.file === null ? '' : (job.files[error.file]?.name ?? '')}
              </TableCell>
              <TableCell>{error.line ?? ''}</TableCell>
              <TableCell>
                {Object.hasOwn(ROW_ERRORS, error.code) ? t(ROW_ERRORS[error.code]) : error.code}
              </TableCell>
              <TableCell>{error.field ?? ''}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
      <p className="text-sm text-muted-foreground">
        {t(copy.errors_more, { shown: job.errors.length, total: job.errors_total })}{' '}
        <a className="underline" href={errorsCsvUrl(job.id)} download>
          {t(copy.errors_download)}
        </a>
      </p>
    </div>
  );
}
