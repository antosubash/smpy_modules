import { keys, useT } from '../utils/i18n';
import type { Filters, Report } from '../utils/types';
import { type RankingDimension, RankingPanel } from './RankingPanel';
import { RecentActivity } from './RecentActivity';
import { TrafficChart } from './TrafficChart';

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
  const choose = (dimension: RankingDimension, value: string) => {
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
  const groups = (dimensions: RankingDimension[]) =>
    dimensions.map((dimension) => ({
      dimension,
      rows: report.breakdowns[dimension],
    }));
  const properties = Object.keys(report.breakdowns).filter((d): d is `property:${string}` =>
    d.startsWith('property:'),
  );
  return (
    <div className="min-w-0 space-y-6">
      <section aria-label={t(keys.analytics.ui.overview)} className="border-b pb-6">
        <div className="grid grid-cols-2 gap-x-6 gap-y-5 lg:grid-cols-4">
          {(['pageviews', 'visitors', 'sessions', 'events'] as const).map((metric) => (
            <div key={metric} className="min-w-0">
              <p className="text-sm text-muted-foreground">{t(keys.analytics[metric])}</p>
              <p className="mt-1 break-words text-3xl font-semibold tabular-nums sm:text-4xl">
                {report.totals[metric].toLocaleString(locale)}
              </p>
            </div>
          ))}
        </div>
        <p className="mt-4 text-xs leading-relaxed text-muted-foreground">
          {t(keys.analytics.estimates)}
        </p>
      </section>
      <TrafficChart series={report.series} />
      <div className="grid min-w-0 gap-5 lg:grid-cols-2">
        <RankingPanel
          title={t(keys.analytics.dimensions.path)}
          groups={groups(['path'])}
          onFilter={choose}
        />
        <RankingPanel
          title={t(keys.analytics.ui.sources)}
          groups={groups(['referrer', 'utm_source', 'utm_medium', 'utm_campaign'])}
          onFilter={choose}
        />
        <RankingPanel
          title={t(keys.analytics.ui.audience)}
          groups={groups(['browser', 'os', 'device'])}
          onFilter={choose}
        />
        <RankingPanel
          title={t(keys.analytics.geo_title)}
          help={t(keys.analytics.geo_approximate)}
          groups={groups(['country', 'region', 'city'])}
          onFilter={choose}
        />
        <RankingPanel
          title={t(keys.analytics.dimensions.event)}
          groups={groups(['event', ...properties])}
          onFilter={choose}
        />
        <RecentActivity recent={report.recent} />
      </div>
    </div>
  );
}
