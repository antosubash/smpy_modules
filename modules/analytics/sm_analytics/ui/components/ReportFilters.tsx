import { Button } from '@simple-module-py/ui/components/ui/button';
import { Input } from '@simple-module-py/ui/components/ui/input';
import { Label } from '@simple-module-py/ui/components/ui/label';
import { useId } from 'react';
import { keys, useT } from '../utils/i18n';
import type { Filters, Report } from '../utils/types';

export function ReportFilters({
  value,
  onChange,
  report,
}: {
  value: Filters;
  onChange: (filters: Filters) => void;
  report: Report | null;
}) {
  const { t } = useT();
  const id = useId();
  const set = (key: keyof Filters, next: string) =>
    onChange({
      ...value,
      [key]: next,
      ...(key === 'country' ? { region: '', city: '' } : key === 'region' ? { city: '' } : {}),
    });
  const geoFields = ['country', 'region', 'city'] as const;
  const inputFields = ['start', 'end', 'path', 'event'] as const;
  const inputLabels = {
    start: keys.analytics.start,
    end: keys.analytics.end,
    path: keys.analytics.page_filter,
    event: keys.analytics.event_filter,
  };
  return (
    <fieldset className="rounded-lg border p-4">
      <legend className="px-2 text-sm font-medium">{t(keys.analytics.filters)}</legend>
      <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {inputFields.map((key) => (
          <div key={key} className="space-y-2">
            <Label htmlFor={`${id}-${key}`}>{t(inputLabels[key])}</Label>
            <Input
              id={`${id}-${key}`}
              type={key === 'start' || key === 'end' ? 'date' : 'text'}
              value={value[key]}
              onChange={(e) => set(key, e.target.value)}
            />
          </div>
        ))}
      </div>
      <div className="mt-4 grid items-end gap-4 sm:grid-cols-2 xl:grid-cols-4">
        {geoFields.map((key) => {
          const options = report?.breakdowns[key] ?? [];
          const selected = value[key];
          return (
            <div key={key} className="space-y-2">
              <Label htmlFor={`${id}-${key}`}>{t(keys.analytics[key])}</Label>
              <select
                id={`${id}-${key}`}
                value={selected}
                onChange={(e) => set(key, e.target.value)}
                className="h-10 w-full rounded-md border bg-background px-3 text-sm"
              >
                <option value="">{t(keys.analytics.all)}</option>
                {selected && !options.some((row) => (row.value || '__unknown__') === selected) && (
                  <option value={selected}>
                    {selected === '__unknown__' ? t(keys.analytics.unknown) : selected}
                  </option>
                )}
                {options.map((row) => (
                  <option key={row.value} value={row.value || '__unknown__'}>
                    {row.value ? row.label : t(keys.analytics.unknown)}
                  </option>
                ))}
              </select>
            </div>
          );
        })}
        <Button
          variant="outline"
          onClick={() =>
            onChange({ ...value, path: '', event: '', country: '', region: '', city: '' })
          }
        >
          {t(keys.analytics.clear_filters)}
        </Button>
      </div>
    </fieldset>
  );
}
