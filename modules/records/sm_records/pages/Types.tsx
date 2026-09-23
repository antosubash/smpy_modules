import { Head, Link } from '@inertiajs/react';
import { useT } from '@simple-module-py/i18n';
import { NavIcon } from '@simple-module-py/ui/components/NavIcon';
import { PageShell } from '@simple-module-py/ui/components/PageShell';
import { Badge } from '@simple-module-py/ui/components/ui/badge';
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

import { RecordListPublicUrl } from '../components/RecordListPublicUrl';
import { RecordsToaster } from '../components/RecordsToaster';
import { TenantBadge } from '../components/TenantBadge';
import { TypesCardList } from '../components/TypesCardList';
import { navIconName } from '../components/typeeditor/navIcons';
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
                      <div className="flex items-start gap-2">
                        {type.icon && (
                          <span
                            className="mt-0.5 shrink-0 text-muted-foreground"
                            data-testid="records-type-icon"
                            data-icon={navIconName(type.icon)}
                          >
                            {/* `NavIcon` draws from an allowlist, not from
                                all of lucide-react, and answers a name
                                outside it with an empty span — so an icon
                                this row can't draw falls back to the
                                module's own rather than to a hole. */}
                            <NavIcon name={navIconName(type.icon)} />
                          </span>
                        )}
                        <div className="min-w-0">
                          <Link
                            href={`/admin/records/${type.key}`}
                            className="hover:underline"
                            data-testid="records-type-link"
                          >
                            {type.label}
                          </Link>
                          {type.show_in_menu && (
                            <span
                              className="ml-2 text-xs font-normal text-muted-foreground"
                              data-testid="records-type-in-sidebar"
                            >
                              {t('records.types.in_sidebar', { defaultValue: 'In sidebar' })}
                            </span>
                          )}
                          {type.description && (
                            <p
                              className="text-sm font-normal text-muted-foreground"
                              data-testid="records-type-description"
                            >
                              {type.description}
                            </p>
                          )}
                          {type.is_public && (
                            <RecordListPublicUrl
                              typeKey={type.key}
                              publicRoutePrefix={public_route_prefix}
                            />
                          )}
                        </div>
                      </div>
                    </TableCell>
                    <TableCell className="font-mono text-sm text-muted-foreground align-top">
                      {type.key}
                      {type.collection && (
                        <Badge
                          variant="outline"
                          className="ml-2 font-sans"
                          data-testid="records-type-collection-badge"
                        >
                          {type.collection}
                        </Badge>
                      )}
                    </TableCell>
                    <TableCell className="align-top">
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
                      {/* A link and not a count: the number is only useful if
                          it is one click from the records it counts, which is
                          the list filtered by the same flag. */}
                      {type.invalid_record_count > 0 && (
                        <Link
                          href={`/admin/records/${type.key}?filter=invalid:eq:true`}
                          className="ml-1 text-destructive hover:underline"
                          data-testid="records-type-invalid-count"
                        >
                          {t('records.types.invalid_record_count', {
                            count: type.invalid_record_count,
                            defaultValue: '({count} invalid)',
                            defaultValue_other: '({count} invalid)',
                          })}
                        </Link>
                      )}
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
