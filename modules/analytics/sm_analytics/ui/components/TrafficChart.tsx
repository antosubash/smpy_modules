import { Button } from '@simple-module-py/ui/components/ui/button';
import {
  ChartContainer,
  ChartTooltip,
  ChartTooltipContent,
} from '@simple-module-py/ui/components/ui/chart';
import { useId, useState } from 'react';
import { Area, AreaChart, CartesianGrid, XAxis, YAxis } from 'recharts';
import { keys, useT } from '../utils/i18n';
import type { Report } from '../utils/types';

export function TrafficChart({ series }: { series: Report['series'] }) {
  const { t, locale } = useT();
  const heading = useId();
  const [metric, setMetric] = useState<'pageviews' | 'events'>('pageviews');
  const label = t(keys.analytics[metric]);
  return (
    <section aria-labelledby={heading} className="min-w-0 border-b pb-6">
      <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
        <h2 id={heading} className="text-lg font-semibold">
          {t(keys.analytics.period)}
        </h2>
        <fieldset aria-label={t(keys.analytics.ui.chart_metric)} className="flex gap-1">
          {(['pageviews', 'events'] as const).map((value) => (
            <Button
              key={value}
              variant="ghost"
              size="sm"
              aria-pressed={metric === value}
              className={
                metric === value
                  ? 'text-blue-600 dark:text-blue-400 bg-blue-500/10'
                  : 'text-muted-foreground'
              }
              onClick={() => setMetric(value)}
            >
              {t(keys.analytics[value])}
            </Button>
          ))}
        </fieldset>
      </div>
      {series.length === 0 ? (
        <p className="flex h-64 items-center justify-center text-sm text-muted-foreground">
          {t(keys.analytics.no_data)}
        </p>
      ) : (
        <ChartContainer
          aria-label={label}
          className="h-72 w-full aspect-auto md:h-80"
          config={{ [metric]: { label, theme: { light: '#2563eb', dark: '#60a5fa' } } }}
        >
          <AreaChart
            data={series}
            accessibilityLayer
            margin={{ top: 12, right: 8, left: 0, bottom: 0 }}
          >
            <CartesianGrid vertical={false} stroke="var(--border)" strokeDasharray="3 3" />
            <XAxis
              dataKey="date"
              tickLine={false}
              axisLine={false}
              minTickGap={40}
              tickMargin={12}
              tickFormatter={(date: string) =>
                new Date(`${date}T00:00:00Z`).toLocaleDateString(locale, {
                  month: 'short',
                  day: 'numeric',
                  timeZone: 'UTC',
                })
              }
            />
            <YAxis
              tickLine={false}
              axisLine={false}
              allowDecimals={false}
              width={48}
              tickFormatter={(count: number) =>
                count.toLocaleString(locale, { notation: 'compact' })
              }
            />
            <ChartTooltip content={<ChartTooltipContent />} />
            <Area
              type="linear"
              dataKey={metric}
              name={label}
              stroke={`var(--color-${metric})`}
              fill={`var(--color-${metric})`}
              fillOpacity={0.08}
              strokeWidth={2}
              isAnimationActive={false}
              dot={series.length === 1}
              activeDot={{ r: 4 }}
            />
          </AreaChart>
        </ChartContainer>
      )}
      <details className="mt-4 text-sm">
        <summary className="w-fit cursor-pointer text-muted-foreground focus-visible:outline-ring">
          {t(keys.analytics.ui.chart_data)}
        </summary>
        <div className="max-h-64 overflow-auto">
          <table className="mt-3 w-full text-left text-sm">
            <caption className="sr-only">{label}</caption>
            <thead>
              <tr className="border-b">
                <th className="py-2">{t(keys.analytics.date)}</th>
                <th className="text-right">{label}</th>
              </tr>
            </thead>
            <tbody>
              {series.map((row) => (
                <tr key={row.date} className="border-b last:border-0">
                  <td className="py-2">{row.date}</td>
                  <td className="text-right tabular-nums">{row[metric].toLocaleString(locale)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </section>
  );
}
