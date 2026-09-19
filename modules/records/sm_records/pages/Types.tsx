import { Head, Link } from '@inertiajs/react';
import { useT } from '@simple-module-py/i18n';
import { PageShell } from '@simple-module-py/ui/components/PageShell';
import { Badge } from '@simple-module-py/ui/components/ui/badge';
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

import { NewTypeDialog } from '../components/NewTypeDialog';
import type { TypeRead } from '../utils/types';

type Props = { types: TypeRead[] };

/** `Records/Types` — `/admin/records`. Lists every Record Type with a link
 *  into its records, and a dialog to define a new one. */
function Types({ types }: Props) {
  const { t } = useT();
  const fieldsLockedHint = t('records.types.fields_locked', {
    defaultValue: 'Fields are read-only while this type holds records.',
  });
  return (
    <>
      <Head title={t('records.types.title', { defaultValue: 'Record Types' })} />
      <PageShell
        title={t('records.types.title', { defaultValue: 'Record Types' })}
        actions={<NewTypeDialog />}
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
                <TableRow key={type.key}>
                  <TableCell className="font-medium">
                    <Link href={`/admin/records/${type.key}`} className="hover:underline">
                      {type.label}
                    </Link>
                  </TableCell>
                  <TableCell className="font-mono text-sm text-muted-foreground">
                    {type.key}
                  </TableCell>
                  <TableCell>
                    {t('records.types.record_count', {
                      count: type.record_count,
                      defaultValue: '{{count}} record',
                      defaultValue_other: '{{count}} records',
                    })}
                    {type.fields_locked && (
                      <Badge variant="outline" className="ml-2" title={fieldsLockedHint}>
                        {t('records.types.fields_locked_badge', { defaultValue: 'Fields locked' })}
                      </Badge>
                    )}
                  </TableCell>
                  <TableCell className="text-right">
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

Types.layout = (page: React.ReactNode) => <AdminLayout>{page}</AdminLayout>;
export default Types;
