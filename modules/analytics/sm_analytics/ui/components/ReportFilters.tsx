import { Button } from '@simple-module-py/ui/components/ui/button';
import { Input } from '@simple-module-py/ui/components/ui/input';
import { Label } from '@simple-module-py/ui/components/ui/label';
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@simple-module-py/ui/components/ui/popover';
import { useId, useState } from 'react';
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
  const [open, setOpen] = useState(false);
  const [draft, setDraft] = useState(value);
  const set = (key: keyof Filters, next: string) =>
    setDraft({
      ...draft,
      [key]: next,
      ...(key === 'country' ? { region: '', city: '' } : key === 'region' ? { city: '' } : {}),
    });
  const geoFields = ['country', 'region', 'city'] as const;
  const inputFields = ['path', 'event'] as const;
  const inputLabels = {
    path: keys.analytics.page_filter,
    event: keys.analytics.event_filter,
  };
  return (
    <Popover
      open={open}
      onOpenChange={(next) => {
        setDraft(value);
        setOpen(next);
      }}
    >
      <PopoverTrigger asChild>
        <Button variant="outline">{t(keys.analytics.ui.filters_button)}</Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-[min(28rem,calc(100vw-2rem))]">
        <fieldset>
          <legend className="px-2 text-sm font-medium">{t(keys.analytics.filters)}</legend>
          <div className="grid gap-4 sm:grid-cols-2">
            {inputFields.map((key) => (
              <div key={key} className="space-y-2">
                <Label htmlFor={`${id}-${key}`}>{t(inputLabels[key])}</Label>
                <Input
                  id={`${id}-${key}`}
                  type="text"
                  value={draft[key]}
                  onChange={(e) => set(key, e.target.value)}
                />
              </div>
            ))}
          </div>
          <div className="mt-4 grid items-end gap-4 sm:grid-cols-3">
            {geoFields.map((key) => {
              const options = report?.breakdowns[key] ?? [];
              const selected = draft[key];
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
                    {selected &&
                      !options.some((row) => (row.value || '__unknown__') === selected) && (
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
          </div>
          <div className="mt-4 flex justify-end gap-2">
            <Button variant="outline" onClick={() => setOpen(false)}>
              {t(keys.analytics.cancel)}
            </Button>
            <Button
              onClick={() => {
                onChange({
                  ...value,
                  path: draft.path,
                  event: draft.event,
                  country: draft.country,
                  region: draft.region,
                  city: draft.city,
                });
                setOpen(false);
              }}
            >
              {t(keys.analytics.ui.apply)}
            </Button>
          </div>
        </fieldset>
      </PopoverContent>
    </Popover>
  );
}
