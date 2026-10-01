import { Head, Link } from '@inertiajs/react';
import { useT } from '@simple-module-py/i18n';
import { PageShell } from '@simple-module-py/ui/components/PageShell';
import { Button } from '@simple-module-py/ui/components/ui/button';
import { Input } from '@simple-module-py/ui/components/ui/input';
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
import { useMemo, useState } from 'react';

import { RecordsToaster } from '../components/RecordsToaster';
import { TenantBadge } from '../components/TenantBadge';
import { TypeCounts, TypeIdentity, TypeKey, TypesCardList } from '../components/TypesCardList';
import { useIsNarrow } from '../hooks/useIsNarrow';
import type { TenancyMode, TypeRead } from '../utils/types';

type Props = {
  types: TypeRead[];
  public_route_prefix?: string;
  /** Which tenant this screen reads, and whether the host runs several
   *  (`views_types.py::type_list`, tenancy design §J) — read-only; drives the
   *  `TenantBadge` next to "New type" and nothing else in single mode. */
  tenant?: string;
  tenancy_mode?: TenancyMode;
};

/** Above this many types the list stops being scannable and earns a filter
 *  box (UX review R13.4). Below it the box would be one more control between
 *  the operator and three rows. */
const FILTER_THRESHOLD = 12;

/** `Records/Types` — `/admin/records/`. The hub the "Records" sidebar item
 *  opens: every record type in this install, each row linking to *its
 *  records* (UX review R13.1 — browsing content is the frequent action;
 *  editing the schema is the rare one, and is a row action). */
function Types({ types, public_route_prefix, tenant, tenancy_mode }: Props) {
  const { t } = useT();
  const [query, setQuery] = useState('');
  const narrow = useIsNarrow();

  const sorted = useMemo(() => [...types].sort((a, b) => a.label.localeCompare(b.label)), [types]);
  const showFilter = types.length > FILTER_THRESHOLD;
  const needle = query.trim().toLowerCase();
  const visible =
    showFilter && needle
      ? sorted.filter(
          (type) =>
            type.label.toLowerCase().includes(needle) || type.key.toLowerCase().includes(needle),
        )
      : sorted;

  return (
    <>
      <Head title={t('records.types.page_title', { defaultValue: 'Records' })} />
      <PageShell
        title={t('records.types.page_title', { defaultValue: 'Records' })}
        description={t('records.types.page_subtitle', {
          defaultValue: 'Every record type in this install.',
        })}
        actions={
          <>
            <TenantBadge tenant={tenant} tenancyMode={tenancy_mode} />
            <Button type="button" asChild>
              <Link href="/admin/records/types/new">
                {t('records.types.new', { defaultValue: 'New type' })}
              </Link>
            </Button>
          </>
        }
      >
        <div className="space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <h2 className="text-lg font-semibold">
              {t('records.types.title', { defaultValue: 'Record Types' })}
            </h2>
            {showFilter && (
              <Input
                className="w-full sm:w-64"
                type="search"
                value={query}
                data-testid="records-types-filter"
                aria-label={t('records.types.filter_label', { defaultValue: 'Filter types' })}
                placeholder={t('records.types.filter_placeholder', {
                  defaultValue: 'Filter by name or key…',
                })}
                onChange={(e) => setQuery(e.target.value)}
              />
            )}
          </div>

          {types.length === 0 ? (
            <div className="rounded-lg border border-dashed p-8 text-center text-muted-foreground">
              {t('records.types.empty', { defaultValue: 'No record types yet' })}
            </div>
          ) : visible.length === 0 ? (
            <div
              className="rounded-lg border border-dashed p-8 text-center text-muted-foreground"
              data-testid="records-types-no-match"
            >
              {t('records.types.no_match', {
                query,
                defaultValue: 'No record type matches "{query}".',
              })}
            </div>
          ) : narrow ? (
            <TypesCardList types={visible} publicRoutePrefix={public_route_prefix} />
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
                {visible.map((type) => (
                  <TableRow key={type.key} data-testid="records-type-row" data-type-key={type.key}>
                    <TableCell className="font-medium">
                      <TypeIdentity type={type} publicRoutePrefix={public_route_prefix} />
                    </TableCell>
                    <TableCell className="font-mono text-sm text-muted-foreground align-top">
                      <TypeKey type={type} />
                    </TableCell>
                    <TableCell className="align-top">
                      <TypeCounts type={type} />
                    </TableCell>
                    <TableCell className="text-right align-top">
                      <Link
                        href={`/admin/records/types/${type.key}`}
                        className="text-sm text-primary hover:underline"
                        data-testid="records-type-edit-schema"
                      >
                        {t('records.types.edit_schema', { defaultValue: 'Edit schema' })}
                      </Link>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </div>
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
