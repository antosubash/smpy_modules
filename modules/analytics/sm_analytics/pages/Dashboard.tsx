import { Head } from '@inertiajs/react';
import { PageShell } from '@simple-module-py/ui/components/PageShell';
import { Button } from '@simple-module-py/ui/components/ui/button';
import { Label } from '@simple-module-py/ui/components/ui/label';
import { AuthenticatedLayout } from '@simple-module-py/ui/layouts/AuthenticatedLayout';
import { useState } from 'react';
import { DeleteProperty } from '../ui/components/DeleteProperty';
import { PropertyEditor } from '../ui/components/PropertyEditor';
import { ReportFilters } from '../ui/components/ReportFilters';
import { ReportView } from '../ui/components/ReportView';
import { deleteProperty, saveProperty } from '../ui/utils/api';
import { keys, useT } from '../ui/utils/i18n';
import { useAnalytics } from '../ui/utils/useAnalytics';

export default function Dashboard({ can_manage = false }: { can_manage?: boolean }) {
  const { t } = useT();
  const data = useAnalytics();
  const [editing, setEditing] = useState<'new' | 'edit' | null>(null);
  const property = data.properties.find((item) => item.id === data.selected);
  return (
    <AuthenticatedLayout>
      <Head title={t(keys.analytics.title)} />
      <PageShell title={t(keys.analytics.title)} description={t(keys.analytics.description)}>
        <div className="space-y-6">
          <div className="flex flex-wrap items-end justify-between gap-4">
            <div className="min-w-56 space-y-2">
              <Label htmlFor="analytics-property">{t(keys.analytics.property)}</Label>
              <select
                id="analytics-property"
                className="h-10 w-full rounded-md border bg-background px-3 text-sm"
                value={data.selected}
                onChange={(event) => {
                  data.setSelected(event.target.value);
                  setEditing(null);
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
            <div className="flex flex-wrap gap-2">
              <Button variant="outline" onClick={data.reload}>
                {t(keys.analytics.refresh)}
              </Button>
              {can_manage && (
                <>
                  <Button onClick={() => setEditing('new')}>
                    {t(keys.analytics.new_property)}
                  </Button>
                  {property && (
                    <Button variant="outline" onClick={() => setEditing('edit')}>
                      {t(keys.analytics.edit)}
                    </Button>
                  )}
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
          {can_manage && editing && (
            <PropertyEditor
              key={editing === 'edit' ? property?.id : 'new'}
              property={editing === 'edit' ? property : undefined}
              onCancel={() => setEditing(null)}
              onSave={async (input) => {
                const saved = await saveProperty(
                  input,
                  editing === 'edit' ? property?.id : undefined,
                );
                setEditing(null);
                data.reload();
                data.setSelected(saved.id);
              }}
            />
          )}
          {property && (
            <div className="flex flex-wrap items-center justify-between gap-3">
              <p className="text-sm text-muted-foreground">
                {t(property.enabled ? keys.analytics.tracking_on : keys.analytics.tracking_off)} ·{' '}
                {t(property.kind === 'public' ? keys.analytics.public : keys.analytics.application)}
              </p>
              {can_manage && (
                <DeleteProperty
                  key={property.id}
                  onDelete={async () => {
                    await deleteProperty(property.id);
                    setEditing(null);
                    data.setSelected('');
                    data.reload();
                  }}
                />
              )}
            </div>
          )}
          {data.geo && (
            <aside className="rounded-md bg-muted/50 p-4 text-sm">
              <p>
                {t(
                  !data.geo.enabled
                    ? keys.analytics.geo_disabled
                    : data.geo.available
                      ? keys.analytics.geo_ready
                      : keys.analytics.geo_unavailable,
                )}
              </p>
              {data.geo.age_days !== null && (
                <p className="mt-1 text-muted-foreground">
                  {t(keys.analytics.geo_age, { days: data.geo.age_days })}
                </p>
              )}
            </aside>
          )}
          {!data.loading && data.properties.length === 0 && (
            <p className="py-12 text-center text-muted-foreground">
              {t(keys.analytics.no_properties)}
            </p>
          )}
          {property && (
            <ReportFilters value={data.filters} onChange={data.setFilters} report={data.report} />
          )}
          {data.loading && (
            <p role="status" className="py-8 text-center text-sm text-muted-foreground">
              {t(keys.analytics.loading)}
            </p>
          )}
          {data.report && !data.loading && (
            <ReportView report={data.report} filters={data.filters} onFilter={data.setFilters} />
          )}
          {can_manage && property && (
            <section className="rounded-lg border p-4">
              <h2 className="font-semibold">{t(keys.analytics.setup)}</h2>
              <p className="mt-2 max-w-3xl text-sm text-muted-foreground">
                {t(keys.analytics.setup_help)}
              </p>
              <p className="mt-2 break-all text-xs text-muted-foreground">{property.id}</p>
            </section>
          )}
        </div>
      </PageShell>
    </AuthenticatedLayout>
  );
}
