import { Input } from '@simple-module-py/ui/components/ui/input';
import { Label } from '@simple-module-py/ui/components/ui/label';
import { NativeSelect } from '@simple-module-py/ui/components/ui/native-select';
import type { ReactNode } from 'react';
import type { Filters } from '../../hooks/useEvents';
import { browserZone } from '../../utils/datetime';
import { keys, useT } from '../../utils/i18n';
import type { Category } from '../../utils/types';
import type { ListStatus } from '../../utils/types-events';
import type { CalendarChoice } from './EventRow';

const STATUSES: ListStatus[] = ['draft', 'in_review', 'published', 'scheduled'];

/** The category's name in the console language, else the first it has. */
export function categoryName(category: Category, locales: readonly string[], fallback: string) {
  for (const locale of locales) if (category.names[locale]) return category.names[locale];
  return Object.values(category.names)[0] ?? fallback;
}

function Field({ id, label, children }: { id: string; label: string; children: ReactNode }) {
  return (
    <div className="grid min-w-0 max-w-full gap-1">
      <Label htmlFor={id}>{label}</Label>
      {children}
    </div>
  );
}

export function EventFilters({
  filters,
  calendars,
  categories,
  locales,
  onChange,
}: {
  filters: Filters;
  calendars: CalendarChoice[];
  categories: Category[];
  /** The content locales, console language first, for category names. */
  locales: readonly string[];
  onChange: (patch: Partial<Filters>) => void;
}) {
  const { t } = useT();
  const copy = keys.events.list;
  return (
    <fieldset className="flex min-w-0 flex-wrap items-end gap-3" aria-label={t(copy.filters)}>
      <Field id="filter-calendar" label={t(copy.f_calendar)}>
        <NativeSelect
          id="filter-calendar"
          value={filters.calendar}
          onChange={(e) => onChange({ calendar: e.target.value })}
        >
          <option value="">{t(copy.all_calendars)}</option>
          {calendars.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </NativeSelect>
      </Field>
      <Field id="filter-status" label={t(copy.f_status)}>
        <NativeSelect
          id="filter-status"
          value={filters.status}
          onChange={(e) => onChange({ status: e.target.value as Filters['status'] })}
        >
          <option value="">{t(copy.all_statuses)}</option>
          {STATUSES.map((s) => (
            <option key={s} value={s}>
              {t(copy[`status_${s}`])}
            </option>
          ))}
        </NativeSelect>
      </Field>
      <Field id="filter-category" label={t(copy.f_category)}>
        <NativeSelect
          id="filter-category"
          value={filters.category}
          onChange={(e) => onChange({ category: e.target.value })}
        >
          <option value="">{t(copy.all_categories)}</option>
          {categories.map((c) => (
            <option key={c.id} value={c.id}>
              {categoryName(c, locales, t(copy.no_category_name))}
            </option>
          ))}
        </NativeSelect>
      </Field>
      <Field id="filter-from" label={t(copy.f_from)}>
        <Input
          id="filter-from"
          type="date"
          value={filters.from}
          onChange={(e) => onChange({ from: e.target.value })}
        />
      </Field>
      <Field id="filter-to" label={t(copy.f_to)}>
        <Input
          id="filter-to"
          type="date"
          value={filters.to}
          onChange={(e) => onChange({ to: e.target.value })}
        />
      </Field>
      <Field id="filter-text" label={t(copy.f_text)}>
        <Input
          id="filter-text"
          type="search"
          maxLength={100}
          placeholder={t(copy.f_text_placeholder)}
          value={filters.q}
          onChange={(e) => onChange({ q: e.target.value })}
        />
      </Field>
      <p className="basis-full text-xs text-muted-foreground dark:text-zinc-400">
        {t(copy.dates_hint, { zone: browserZone() })}
      </p>
    </fieldset>
  );
}
