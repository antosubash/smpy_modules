import { Button } from '@simple-module-py/ui/components/ui/button';
import { Checkbox } from '@simple-module-py/ui/components/ui/checkbox';
import { Input } from '@simple-module-py/ui/components/ui/input';
import { Label } from '@simple-module-py/ui/components/ui/label';
import { NativeSelect, NativeSelectOption } from '@simple-module-py/ui/components/ui/native-select';
import { Search } from 'lucide-react';
import { useEffect, useState } from 'react';
import { keys, useT } from '../utils/i18n';
import type { MeterInfo, SubjectMode } from '../utils/types';
import { meterLabel } from '../utils/usage';

export interface UsageFilterValues {
  meter: string;
  q: string;
  over: boolean;
  period: 'current' | 'previous';
}

interface Props {
  value: UsageFilterValues;
  meters: MeterInfo[];
  onChange: (next: UsageFilterValues) => void;
  /** "user": the search names users (by email) instead of organisations. */
  subjectMode?: SubjectMode;
}

/**
 * Meter, organisation search, "over 80%" and period. Held locally as well as
 * in the URL, so a control shows its new value at once rather than flipping
 * back until the filtered page arrives.
 */
export function UsageFilters({ value, meters, onChange, subjectMode = 'tenant' }: Props) {
  const { t } = useT();
  const c = keys.billing.admin_usage.filters;
  const byUser = subjectMode === 'user';
  const [draft, setDraft] = useState(value);
  useEffect(() => setDraft(value), [value]);

  const change = (patch: Partial<UsageFilterValues>) => {
    const next = { ...draft, ...patch };
    setDraft(next);
    onChange(next);
  };

  return (
    <form
      className="mb-4 flex flex-wrap items-end gap-3"
      onSubmit={(event) => {
        event.preventDefault();
        change({ q: draft.q.trim() });
      }}
    >
      <div className="space-y-1.5">
        <Label htmlFor="usage-meter">{t(c.meter)}</Label>
        <NativeSelect
          id="usage-meter"
          value={draft.meter}
          onChange={(e) => change({ meter: e.target.value })}
        >
          <NativeSelectOption value="">{t(c.all_meters)}</NativeSelectOption>
          {meters.map((m) => (
            <NativeSelectOption key={m.key} value={m.key}>
              {meterLabel(m.label_key, m.key)}
            </NativeSelectOption>
          ))}
        </NativeSelect>
      </div>
      <div className="space-y-1.5">
        <Label htmlFor="usage-period">{t(c.period)}</Label>
        <NativeSelect
          id="usage-period"
          value={draft.period}
          onChange={(e) => change({ period: e.target.value as UsageFilterValues['period'] })}
        >
          <NativeSelectOption value="current">{t(c.current)}</NativeSelectOption>
          <NativeSelectOption value="previous">{t(c.previous)}</NativeSelectOption>
        </NativeSelect>
      </div>
      <div className="min-w-48 flex-1 space-y-1.5 sm:max-w-xs">
        <Label htmlFor="usage-search">{t(byUser ? c.search_user : c.search)}</Label>
        <div className="flex gap-2">
          <Input
            id="usage-search"
            type="search"
            maxLength={120}
            placeholder={t(byUser ? c.search_placeholder_user : c.search_placeholder)}
            value={draft.q}
            onChange={(e) => setDraft({ ...draft, q: e.target.value })}
          />
          <Button type="submit" variant="outline" size="icon" aria-label={t(c.submit)}>
            <Search aria-hidden="true" />
          </Button>
        </div>
      </div>
      <div className="flex h-9 items-center gap-2 max-lg:min-h-11">
        <Checkbox
          id="usage-over"
          checked={draft.over}
          onCheckedChange={(checked) => change({ over: checked === true })}
        />
        <Label htmlFor="usage-over">{t(c.over)}</Label>
      </div>
    </form>
  );
}
