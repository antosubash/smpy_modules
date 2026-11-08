import { Head } from '@inertiajs/react';
import { PageShell } from '@simple-module-py/ui/components/PageShell';
import { Button } from '@simple-module-py/ui/components/ui/button';
import { Label } from '@simple-module-py/ui/components/ui/label';
import { AuthenticatedLayout } from '@simple-module-py/ui/layouts/AuthenticatedLayout';
import { DateRangeControl } from '../ui/components/DateRangeControl';
import { FilterChips } from '../ui/components/FilterChips';
import { PropertySettings } from '../ui/components/PropertySettings';
import { ReportFilters } from '../ui/components/ReportFilters';
import { ReportView } from '../ui/components/ReportView';
import { deleteProperty, saveProperty } from '../ui/utils/api';
import { keys, useT } from '../ui/utils/i18n';
import { useAnalytics } from '../ui/utils/useAnalytics';

export default function Dashboard({ can_manage = false }: { can_manage?: boolean }) {
  const { t } = useT();
  const data = useAnalytics();
  const property = data.properties.find((item) => item.id === data.selected);
  const settings = (
    <PropertySettings
      key={property?.id ?? 'new'}
      canManage={can_manage}
      property={property}
      geo={data.geo}
      onSave={async (input, id) => {
        const saved = await saveProperty(input, id);
        data.reload();
        data.setSelected(saved.id);
        if (saved.id !== data.selected)
          data.setFilters({
            ...data.filters,
            path: '',
            event: '',
            country: '',
            region: '',
            city: '',
          });
      }}
      onDelete={async () => {
        if (!property) return;
        await deleteProperty(property.id);
        data.setSelected('');
        data.reload();
      }}
    />
  );
  return (
    <AuthenticatedLayout>
      <Head title={t(keys.analytics.title)} />
      <PageShell title={t(keys.analytics.title)}>
        <div className="min-w-0 space-y-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex min-w-0 flex-wrap items-center gap-x-4 gap-y-2">
              <div className="min-w-0 max-w-full">
                <Label htmlFor="analytics-property" className="sr-only">
                  {t(keys.analytics.property)}
                </Label>
                <select
                  id="analytics-property"
                  className="h-9 w-full max-w-72 rounded-md border bg-background px-3 text-sm font-medium"
                  value={data.selected}
                  onChange={(event) => {
                    data.setSelected(event.target.value);
                    data.setFilters({
                      ...data.filters,
                      path: '',
                      event: '',
                      country: '',
                      region: '',
                      city: '',
                    });
                  }}
                >
                  <option value="" disabled>
                    {t(keys.analytics.properties)}
                  </option>
                  {data.properties.map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.name}
                    </option>
                  ))}
                </select>
              </div>
              {property && (
                <span
                  role="status"
                  aria-label={t(keys.analytics.status)}
                  className="flex items-center gap-2 text-xs text-muted-foreground"
                  title={t(
                    property.kind === 'public' ? keys.analytics.public : keys.analytics.application,
                  )}
                >
                  <span
                    aria-hidden="true"
                    className={`size-2 rounded-full ${property.enabled ? 'bg-emerald-500' : 'bg-muted-foreground'}`}
                  />
                  {t(property.enabled ? keys.analytics.tracking_on : keys.analytics.tracking_off)}
                </span>
              )}
              {data.report && (
                <span className="text-xs tabular-nums text-muted-foreground">
                  {t(keys.analytics.ui.active_now, { count: data.report.recent.visitors })}
                </span>
              )}
            </div>
            <div className="flex max-w-full flex-wrap items-center gap-2">
              <Button variant="ghost" size="sm" onClick={data.reload}>
                {t(keys.analytics.refresh)}
              </Button>
              {property && (
                <>
                  <DateRangeControl value={data.filters} onChange={data.setFilters} />
                  <ReportFilters
                    value={data.filters}
                    onChange={data.setFilters}
                    report={data.report}
                  />
                  {settings}
                </>
              )}
            </div>
          </div>
          {data.error && (
            <p
              role="alert"
              className="rounded-md border border-destructive p-3 text-sm text-destructive"
            >
              {data.error}
            </p>
          )}
          {data.geo && (!data.geo.enabled || !data.geo.available) && (
            <aside className="text-sm text-muted-foreground">
              {t(!data.geo.enabled ? keys.analytics.geo_disabled : keys.analytics.geo_unavailable)}
            </aside>
          )}
          {!data.loading && data.properties.length === 0 && (
            <div className="space-y-4 py-12 text-center">
              <p className="text-muted-foreground">{t(keys.analytics.no_properties)}</p>
              {settings}
            </div>
          )}
          {property && (
            <FilterChips value={data.filters} onChange={data.setFilters} report={data.report} />
          )}
          {data.loading && !data.report && (
            <p role="status" className="py-8 text-center text-sm text-muted-foreground">
              {t(keys.analytics.loading)}
            </p>
          )}
          {data.report && (
            <ReportView report={data.report} filters={data.filters} onFilter={data.setFilters} />
          )}
        </div>
      </PageShell>
    </AuthenticatedLayout>
  );
}
