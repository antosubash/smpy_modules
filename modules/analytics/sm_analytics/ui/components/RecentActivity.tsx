import { useId } from 'react';
import { keys, useT } from '../utils/i18n';
import type { Report } from '../utils/types';

export function RecentActivity({ recent }: { recent: Report['recent'] }) {
  const { t, locale } = useT();
  const titleId = useId();
  return (
    <section className="min-w-0 rounded-lg border bg-card p-4 sm:p-5">
      <h2 id={titleId} className="font-semibold">
        {t(keys.analytics.recent)}
      </h2>
      <p className="mt-1 text-sm text-muted-foreground">{t(keys.analytics.recent_help)}</p>
      <p className="my-3 text-sm">
        {t(keys.analytics.recent_visitors)}:{' '}
        <strong>{recent.visitors.toLocaleString(locale)}</strong>
      </p>
      {recent.events.length === 0 ? (
        <p className="text-sm text-muted-foreground">{t(keys.analytics.no_data)}</p>
      ) : (
        <section
          aria-labelledby={titleId}
          // biome-ignore lint/a11y/noNoninteractiveTabindex: A scrollable region needs keyboard access to all activity rows.
          tabIndex={0}
          className="max-h-80 overflow-auto rounded-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <table className="w-full table-fixed text-sm">
            <thead>
              <tr className="border-b text-left">
                <th className="w-24 pb-2">{t(keys.analytics.time)}</th>
                <th>{t(keys.analytics.page_filter)}</th>
                <th>{t(keys.analytics.event_filter)}</th>
                <th>{t(keys.analytics.location)}</th>
              </tr>
            </thead>
            <tbody>
              {recent.events.map((event) => (
                <tr key={event.event_id} className="border-b last:border-0">
                  <td className="whitespace-nowrap py-2 pr-4">
                    {new Date(event.created_at).toLocaleTimeString(locale, { timeZone: 'UTC' })}
                  </td>
                  <td className="break-all py-2 pr-4">{event.path}</td>
                  <td className="break-words py-2 pr-4">
                    {event.name || t(keys.analytics.pageviews)}
                  </td>
                  <td className="break-words py-2 [overflow-wrap:anywhere]">
                    {[
                      event.city_name || event.city,
                      event.region_name || event.region,
                      event.country_name || event.country,
                    ]
                      .filter(Boolean)
                      .join(', ') || t(keys.analytics.unknown)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>
      )}
    </section>
  );
}
