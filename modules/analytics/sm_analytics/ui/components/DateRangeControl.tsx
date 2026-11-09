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
import type { Filters } from '../utils/types';

export function DateRangeControl({
  value,
  onChange,
}: {
  value: Filters;
  onChange: (next: Filters) => void;
}) {
  const { t } = useT();
  const id = useId();
  const [open, setOpen] = useState(false);
  const [start, setStart] = useState(value.start);
  const [end, setEnd] = useState(value.end);
  const span = (Date.parse(end) - Date.parse(start)) / 86400000;
  const valid = start >= '0001-01-01' && end <= '9999-12-30' && span >= 0 && span <= 365;
  const apply = (from: string, to: string) => {
    onChange({ ...value, start: from, end: to });
    setOpen(false);
  };
  return (
    <Popover
      open={open}
      onOpenChange={(next) => {
        setStart(value.start);
        setEnd(value.end);
        setOpen(next);
      }}
    >
      <PopoverTrigger asChild>
        <Button
          variant="outline"
          aria-label={t(keys.analytics.ui.date_range)}
          className="max-w-full tabular-nums"
        >
          <span className="truncate">
            {value.start} – {value.end}
          </span>
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-[min(24rem,calc(100vw-2rem))]">
        <div className="grid grid-cols-2 gap-2">
          {(
            [
              ['today', 1],
              ['last_7_days', 7],
              ['last_30_days', 30],
              ['last_90_days', 90],
            ] as const
          ).map(([label, days]) => (
            <Button
              key={label}
              variant="outline"
              onClick={() => {
                const today = new Date().toISOString().slice(0, 10);
                const from = new Date(`${today}T00:00:00Z`);
                from.setUTCDate(from.getUTCDate() - days + 1);
                apply(from.toISOString().slice(0, 10), today);
              }}
            >
              {t(keys.analytics.ui[label])}
            </Button>
          ))}
        </div>
        <form
          className="mt-4 space-y-3"
          onSubmit={(event) => {
            event.preventDefault();
            if (valid) apply(start, end);
          }}
        >
          <h2 className="text-sm font-medium">{t(keys.analytics.ui.custom_range)}</h2>
          <div className="grid gap-3 sm:grid-cols-2">
            <div className="min-w-0 space-y-1">
              <Label htmlFor={`${id}-start`}>{t(keys.analytics.start)}</Label>
              <Input
                id={`${id}-start`}
                type="date"
                aria-describedby={`${id}-help`}
                min="0001-01-01"
                max={end || '9999-12-30'}
                value={start}
                onChange={(event) => setStart(event.target.value)}
                required
              />
            </div>
            <div className="min-w-0 space-y-1">
              <Label htmlFor={`${id}-end`}>{t(keys.analytics.end)}</Label>
              <Input
                id={`${id}-end`}
                type="date"
                aria-describedby={`${id}-help`}
                min={start || '0001-01-01'}
                max="9999-12-30"
                value={end}
                onChange={(event) => setEnd(event.target.value)}
                required
              />
            </div>
          </div>
          <p id={`${id}-help`} className="text-xs text-muted-foreground">
            {t(keys.analytics.ui.date_help)}
          </p>
          <div className="flex justify-end gap-2">
            <Button type="button" variant="outline" onClick={() => setOpen(false)}>
              {t(keys.analytics.cancel)}
            </Button>
            <Button type="submit" disabled={!valid} aria-describedby={`${id}-help`}>
              {t(keys.analytics.ui.apply)}
            </Button>
          </div>
        </form>
      </PopoverContent>
    </Popover>
  );
}
