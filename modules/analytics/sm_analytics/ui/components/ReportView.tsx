import { keys, useT } from '../utils/i18n';
import {
  type Breakdown,
  DIMENSIONS,
  type Dimension,
  type Filters,
  type Report,
} from '../utils/types';

function BreakdownTable({
  dimension,
  rows,
  onFilter,
}: {
  dimension: Dimension | `property:${string}`;
  rows: Breakdown[];
  onFilter: (dimension: Dimension | `property:${string}`, value: string) => void;
}) {
  const { t, locale } = useT();
  const actionable = ['path', 'event', 'country', 'region', 'city'].includes(dimension);
  return (
    <section className="min-w-0 rounded-lg border p-4">
      <h3 className="mb-3 font-medium">
        {dimension.startsWith('property:')
          ? t(keys.analytics.event_property, { name: dimension.slice(9) })
          : t(keys.analytics.dimensions[dimension as Dimension])}
      </h3>
      {rows.length === 0 ? (
        <p className="text-sm text-muted-foreground">{t(keys.analytics.no_data)}</p>
      ) : (
        <div className="max-h-80 overflow-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b text-left text-muted-foreground">
                <th className="pb-2 font-normal">{t(keys.analytics.value)}</th>
                <th className="pb-2 text-right font-normal">{t(keys.analytics.count)}</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.value} className="border-b last:border-0">
                  <td className="max-w-64 break-words py-2 pr-4">
                    {actionable ? (
                      <button
                        type="button"
                        className="text-left underline decoration-muted-foreground/40 underline-offset-4 hover:decoration-current"
                        onClick={() => onFilter(dimension, row.value || '__unknown__')}
                      >
                        {row.value ? row.label : t(keys.analytics.unknown)}
                      </button>
                    ) : row.value ? (
                      row.label
                    ) : (
                      t(keys.analytics.unknown)
                    )}
                  </td>
                  <td className="py-2 text-right tabular-nums">
                    {row.count.toLocaleString(locale)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

export function ReportView({
  report,
  filters,
  onFilter,
}: {
  report: Report;
  filters: Filters;
  onFilter: (filters: Filters) => void;
}) {
  const { t, locale } = useT();
  const max = Math.max(1, ...report.series.map((row) => row.pageviews));
  const choose = (dimension: Dimension | `property:${string}`, value: string) => {
    if (!['path', 'event', 'country', 'region', 'city'].includes(dimension)) return;
    onFilter({
      ...filters,
      [dimension]: value,
      ...(dimension === 'country'
        ? { region: '', city: '' }
        : dimension === 'region'
          ? { city: '' }
          : {}),
    });
  };
  return (
    <div className="space-y-6">
      <section
        aria-label={t(keys.analytics.period)}
        className="grid grid-cols-2 divide-x rounded-lg border py-5 lg:grid-cols-4"
      >
        {(['pageviews', 'visitors', 'sessions', 'events'] as const).map((metric) => (
          <div key={metric} className="px-5">
            <p className="text-sm text-muted-foreground">{t(keys.analytics[metric])}</p>
            <p className="mt-1 text-3xl font-semibold tabular-nums">
              {report.totals[metric].toLocaleString(locale)}
            </p>
          </div>
        ))}
      </section>
      <p className="text-sm text-muted-foreground">{t(keys.analytics.estimates)}</p>
      <section className="rounded-lg border p-4">
        <h2 className="mb-4 font-semibold">{t(keys.analytics.period)}</h2>
        <svg
          aria-hidden="true"
          viewBox={`0 0 ${Math.max(1, report.series.length) * 12} 80`}
          preserveAspectRatio="none"
          className="h-36 w-full text-primary"
        >
          {report.series.map((row, index) => (
            <rect
              key={row.date}
              x={index * 12 + 1}
              y={80 - (row.pageviews / max) * 78}
              width={10}
              height={(row.pageviews / max) * 78}
              fill="currentColor"
            />
          ))}
        </svg>
        <details className="mt-3 text-sm">
          <summary className="cursor-pointer">
            {t(keys.analytics.date)} / {t(keys.analytics.count)}
          </summary>
          <div className="max-h-64 overflow-auto">
            <table className="mt-2 w-full text-sm">
              <thead>
                <tr className="text-left">
                  <th>{t(keys.analytics.date)}</th>
                  <th>{t(keys.analytics.pageviews)}</th>
                  <th>{t(keys.analytics.events)}</th>
                </tr>
              </thead>
              <tbody>
                {report.series.map((row) => (
                  <tr key={row.date}>
                    <td>{row.date}</td>
                    <td>{row.pageviews.toLocaleString(locale)}</td>
                    <td>{row.events.toLocaleString(locale)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      </section>
      <section aria-labelledby="analytics-locations">
        <h2 id="analytics-locations" className="mb-1 text-lg font-semibold">
          {t(keys.analytics.geo_title)}
        </h2>
        <p className="mb-4 text-sm text-muted-foreground">{t(keys.analytics.geo_approximate)}</p>
        <div className="grid gap-4 lg:grid-cols-3">
          {(['country', 'region', 'city'] as const).map((dimension) => (
            <BreakdownTable
              key={dimension}
              dimension={dimension}
              rows={report.breakdowns[dimension]}
              onFilter={choose}
            />
          ))}
        </div>
      </section>
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {DIMENSIONS.filter((d) => !['country', 'region', 'city'].includes(d)).map((dimension) => (
          <BreakdownTable
            key={dimension}
            dimension={dimension}
            rows={report.breakdowns[dimension]}
            onFilter={choose}
          />
        ))}
      </div>
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {Object.keys(report.breakdowns)
          .filter((dimension) => dimension.startsWith('property:'))
          .map((dimension) => (
            <BreakdownTable
              key={dimension}
              dimension={dimension as `property:${string}`}
              rows={report.breakdowns[dimension]}
              onFilter={choose}
            />
          ))}
      </div>
      <section className="rounded-lg border p-4">
        <h2 className="font-semibold">{t(keys.analytics.recent)}</h2>
        <p className="mt-1 text-sm text-muted-foreground">{t(keys.analytics.recent_help)}</p>
        <p className="my-3 text-sm">
          {t(keys.analytics.recent_visitors)}:{' '}
          <strong>{report.recent.visitors.toLocaleString(locale)}</strong>
        </p>
        {report.recent.events.length === 0 ? (
          <p className="text-sm text-muted-foreground">{t(keys.analytics.no_data)}</p>
        ) : (
          <div className="overflow-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-left">
                  <th className="pb-2">{t(keys.analytics.time)}</th>
                  <th>{t(keys.analytics.page_filter)}</th>
                  <th>{t(keys.analytics.event_filter)}</th>
                  <th>{t(keys.analytics.location)}</th>
                </tr>
              </thead>
              <tbody>
                {report.recent.events.map((event) => (
                  <tr key={event.event_id} className="border-b last:border-0">
                    <td className="whitespace-nowrap py-2 pr-4">
                      {new Date(event.created_at).toLocaleTimeString(locale, { timeZone: 'UTC' })}
                    </td>
                    <td className="break-all py-2 pr-4">{event.path}</td>
                    <td className="py-2 pr-4">{event.name || t(keys.analytics.pageviews)}</td>
                    <td className="py-2">
                      {[event.city, event.region, event.country].filter(Boolean).join(', ') ||
                        t(keys.analytics.unknown)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
