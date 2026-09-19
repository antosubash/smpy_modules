import { Head, Link } from '@inertiajs/react';
import { useT } from '@simple-module-py/i18n';
import { PageShell } from '@simple-module-py/ui/components/PageShell';
import { Button } from '@simple-module-py/ui/components/ui/button';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@simple-module-py/ui/components/ui/table';
import { AdminLayout } from '@simple-module-py/ui/layouts/AdminLayout';
import type React from 'react';

import { RecordsToaster } from '../components/RecordsToaster';
import type { TypeRead } from '../utils/types';

type Props = { types: TypeRead[] };

/** `Records/Types` — `/admin/records/`. Lists every Record Type with a link
 *  to edit its schema and a link into its records; "New type" opens the
 *  schema editor at `/admin/records/types/new`. */
function Types({ types }: Props) {
  const { t } = useT();
  return (
    <>
      <Head title={t('records.types.title', { defaultValue: 'Record Types' })} />
      <PageShell
        title={t('records.types.title', { defaultValue: 'Record Types' })}
        actions={
          <Button type="button" asChild>
            <Link href="/admin/records/types/new">
              {t('records.types.new', { defaultValue: 'New type' })}
            </Link>
          </Button>
        }
      >
        {types.length === 0 ? (
          <div className="rounded-lg border border-dashed p-8 text-center text-muted-foreground">
            {t('records.types.empty', { defaultValue: 'No record types yet' })}
          </div>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>{t('records.types.label', { defaultValue: 'Label' })}</TableHead>
                <TableHead>{t('records.types.key', { defaultValue: 'Key' })}</TableHead>
                <TableHead>{t('records.records.title', { defaultValue: 'Records' })}</TableHead>
                <TableHead />
              </TableRow>
            </TableHeader>
            <TableBody>
              {types.map((type) => (
                <TableRow key={type.key} data-testid="records-type-row" data-type-key={type.key}>
                  <TableCell className="font-medium">
                    <Link href={`/admin/records/types/${type.key}`} className="hover:underline">
                      {type.label}
                    </Link>
                  </TableCell>
                  <TableCell className="font-mono text-sm text-muted-foreground">
                    {type.key}
                  </TableCell>
                  <TableCell>
                    {t('records.types.record_count', {
                      count: type.record_count,
                      defaultValue: '{count} record',
                      defaultValue_other: '{count} records',
                    })}
                    {type.trashed_record_count > 0 && (
                      <span className="ml-1 text-muted-foreground">
                        {t('records.types.trashed_record_count', {
                          count: type.trashed_record_count,
                          defaultValue: '({count} trashed)',
                          defaultValue_other: '({count} trashed)',
                        })}
                      </span>
                    )}
                  </TableCell>
                  <TableCell className="text-right space-x-3">
                    <Link
                      href={`/admin/records/types/${type.key}`}
                      className="text-sm text-primary hover:underline"
                    >
                      {t('records.types.edit', { defaultValue: 'Edit' })}
                    </Link>
                    <Link
                      href={`/admin/records/${type.key}`}
                      className="text-sm text-primary hover:underline"
                    >
                      {t('records.types.view_records', { defaultValue: 'View records' })}
                    </Link>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </PageShell>
    </>
  );
}

Types.layout = (page: React.ReactNode) => (
  <AdminLayout>
    {page}
    <RecordsToaster />
  </AdminLayout>
);
export default Types;
