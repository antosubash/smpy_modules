import { Button } from '@simple-module-py/ui/components/ui/button';
import { X } from 'lucide-react';
import { keys, useT } from '../utils/i18n';
import type { Filters, Report } from '../utils/types';

export function FilterChips({
  value,
  onChange,
  report,
}: {
  value: Filters;
  onChange: (next: Filters) => void;
  report: Report | null;
}) {
  const { t } = useT();
  const fields = ['path', 'event', 'country', 'region', 'city'] as const;
  const labels = {
    path: keys.analytics.page_filter,
    event: keys.analytics.event_filter,
    country: keys.analytics.country,
    region: keys.analytics.region,
    city: keys.analytics.city,
  };
  if (!fields.some((field) => value[field])) return null;
  return (
    <div className="flex flex-wrap items-center gap-2">
      {fields
        .filter((field) => value[field])
        .map((field) => {
          const name = t(labels[field]);
          const label =
            field !== 'path' && field !== 'event' && value[field] === '__unknown__'
              ? t(keys.analytics.unknown)
              : report?.breakdowns[field]?.find((row) => row.value === value[field])?.label ||
                value[field];
          return (
            <Button
              key={field}
              variant="outline"
              size="sm"
              className="h-auto max-w-full gap-2 py-1 text-xs"
              aria-label={t(keys.analytics.ui.clear_filter, { name })}
              onClick={() =>
                onChange({
                  ...value,
                  [field]: '',
                  ...(field === 'country'
                    ? { region: '', city: '' }
                    : field === 'region'
                      ? { city: '' }
                      : {}),
                })
              }
            >
              <span className="min-w-0 whitespace-normal break-all text-left">
                {name}: {label}
              </span>
              <X className="size-3 shrink-0" aria-hidden="true" />
            </Button>
          );
        })}
      <Button
        variant="ghost"
        size="sm"
        className="h-7 text-xs text-muted-foreground"
        onClick={() =>
          onChange({ ...value, path: '', event: '', country: '', region: '', city: '' })
        }
      >
        {t(keys.analytics.clear_filters)}
      </Button>
    </div>
  );
}
