import { keys, useT } from '../../utils/i18n';
import { formatRate, rate } from '../../utils/report';
import type { Report } from '../../utils/types';

const copy = keys.newsletter.report;

function Tile({ label, value, hint }: { label: string; value: string | number; hint?: string }) {
  return (
    <div className="rounded-lg border p-4">
      <div className="text-sm text-muted-foreground">{label}</div>
      <div className="text-2xl font-semibold tabular-nums">{value}</div>
      {hint && <p className="mt-1 text-xs text-muted-foreground">{hint}</p>}
    </div>
  );
}

interface EngagementProps {
  label: string;
  unique: number;
  accepted: number;
  uniqueAll: number;
  totalAll: number;
  approx: string;
  off: string | null;
}

/** Unique engagement among accepted messages and its rate, then the all-messages line (B5). */
function Engagement({
  label,
  unique,
  accepted,
  uniqueAll,
  totalAll,
  approx,
  off,
}: EngagementProps) {
  const { t, locale } = useT();
  const rateText =
    formatRate(rate(unique, accepted), locale ?? 'en') ?? t(keys.newsletter.campaigns.no_rate);
  return (
    <div className="rounded-lg border p-4">
      <div className="text-sm text-muted-foreground">{label}</div>
      <div className="text-2xl font-semibold tabular-nums">
        {unique} <span className="text-base font-normal">({rateText})</span>
      </div>
      <p className="mt-1 text-xs text-muted-foreground">{t(copy.stats.rate_hint)}</p>
      <p className="mt-1 text-xs text-muted-foreground">
        {t(copy.stats.all_messages, { unique: uniqueAll, total: totalAll })}
      </p>
      <p className="mt-1 text-xs text-muted-foreground">{approx}</p>
      {off && <p className="mt-1 text-xs font-medium text-amber-700 dark:text-amber-400">{off}</p>}
    </div>
  );
}

/** The report's tiles: outcomes, then opens and clicks. Rates are computed here from raw counts. */
export function ReportStats({ report }: { report: Report }) {
  const { t } = useT();
  const s = copy.stats;
  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
      <Tile label={t(s.recipients)} value={report.recipients} />
      <Tile label={t(s.accepted)} value={report.sent} hint={t(s.accepted_hint)} />
      <Tile label={t(s.failed)} value={report.failed} />
      <Tile label={t(s.bounced)} value={report.bounced} />
      <Tile label={t(s.suppressed)} value={report.suppressed} />
      <Tile label={t(s.skipped)} value={report.skipped} />
      <Tile label={t(s.unsubscribed)} value={report.unsubscribed} />
      <div className="grid gap-3 sm:col-span-2 lg:col-span-4 lg:grid-cols-2">
        <Engagement
          label={t(s.opens)}
          unique={report.opens_unique_accepted}
          accepted={report.sent}
          uniqueAll={report.opens_unique}
          totalAll={report.opens_total}
          approx={t(copy.approx.opens)}
          off={report.tracking_opens ? null : t(copy.tracking_off.opens)}
        />
        <Engagement
          label={t(s.clicks)}
          unique={report.clicks_unique_accepted}
          accepted={report.sent}
          uniqueAll={report.clicks_unique}
          totalAll={report.clicks_total}
          approx={t(copy.approx.clicks)}
          off={report.tracking_clicks ? null : t(copy.tracking_off.clicks)}
        />
      </div>
    </div>
  );
}
