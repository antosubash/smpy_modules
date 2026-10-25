import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from '@simple-module-py/ui/components/ui/card';
import { cn } from '@simple-module-py/ui/lib/utils';
import { formatDate } from '../utils/format';
import { keys, useT } from '../utils/i18n';
import type { MeterUsage } from '../utils/types';
import { formatQuantity, meterLabel, percentOf, usageTone } from '../utils/usage';
import { UsageBar } from './UsageBar';

const TONE_TEXT = {
  normal: 'text-muted-foreground',
  warning: 'text-amber-700 dark:text-amber-400',
  over: 'text-destructive',
} as const;

/**
 * What the organisation used, one row per meter its plan limits or it has
 * used: `used / limit` in the meter's unit (or "Unlimited"), a bar, and when
 * a counter resets — a gauge is a level held right now and never resets.
 * Renders nothing when there is no row (a host that meters nothing).
 */
export function UsageCard({ usage }: { usage: MeterUsage[] }) {
  const { t, locale } = useT();
  const c = keys.billing.usage;
  if (usage.length === 0) return null;
  return (
    <Card data-testid="usage-card">
      <CardHeader>
        <CardTitle>{t(c.title)}</CardTitle>
        <CardDescription>{t(c.description)}</CardDescription>
      </CardHeader>
      <CardContent>
        <ul className="grid gap-5 sm:grid-cols-2">
          {usage.map((row) => {
            const label = meterLabel(row.label_key, row.meter);
            const used = formatQuantity(row.used, row.unit, locale);
            const percent = percentOf(row.used, row.limit);
            const tone = usageTone(percent);
            const amount =
              row.limit === null
                ? t(c.used_no_limit, { used })
                : t(c.of_limit, { used, limit: formatQuantity(row.limit, row.unit, locale) });
            const note =
              row.kind === 'gauge'
                ? t(c.in_use)
                : row.period_end
                  ? t(c.resets_on, { date: formatDate(row.period_end, locale) })
                  : '';
            return (
              <li key={row.meter} className="space-y-1.5" data-meter={row.meter}>
                <div className="flex flex-wrap items-baseline justify-between gap-2 text-sm">
                  <span className="font-medium">{label}</span>
                  <span className="tabular-nums">{amount}</span>
                </div>
                {percent === null ? (
                  <p className="text-xs text-muted-foreground">{t(c.unlimited)}</p>
                ) : (
                  <UsageBar percent={percent} tone={tone} label={label} />
                )}
                <div className="flex flex-wrap justify-between gap-2 text-xs">
                  <span className="text-muted-foreground">{note}</span>
                  {tone !== 'normal' && (
                    <span className={cn('font-medium', TONE_TEXT[tone])}>
                      {tone === 'over' ? t(c.over_limit) : t(c.near_limit)}
                    </span>
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      </CardContent>
    </Card>
  );
}
