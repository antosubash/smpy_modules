import { keys, useT } from '../../utils/i18n';
import { bucketLabel } from '../../utils/report';
import type { ReportPoint } from '../../utils/types';

const copy = keys.newsletter.report.timeline;

const BUCKET_NAME = { hour: copy.bucket.hour, day: copy.bucket.day } as const;
const WINDOW = { hour: copy.window_hour, day: copy.window_day } as const;

function Bar({ kind, value, max }: { kind: 'opens' | 'clicks'; value: number; max: number }) {
  const width = max > 0 ? (value / max) * 100 : 0;
  return (
    <div className="flex items-center gap-2">
      <div className="h-2 flex-1 rounded bg-muted">
        <div
          data-bar={kind}
          className={`h-2 rounded ${kind === 'opens' ? 'bg-primary' : 'bg-emerald-600'}`}
          style={{ width: `${width}%` }}
        />
      </div>
      <span className="w-10 text-right text-xs tabular-nums">{value}</span>
    </div>
  );
}

/** First opens and first clicks per UTC bucket, as a table with CSS bars (no chart library, T15). */
export function ReportTimeline({
  bucket,
  points,
}: {
  bucket: 'hour' | 'day';
  points: ReportPoint[];
}) {
  const { t, locale } = useT();
  const max = Math.max(0, ...points.flatMap((p) => [p.opens, p.clicks]));
  return (
    <section>
      <h2 className="text-lg font-semibold">{t(copy.title)}</h2>
      <p className="mb-2 text-sm text-muted-foreground">{t(WINDOW[bucket])}</p>
      {max === 0 ? (
        <p className="rounded-lg border border-dashed p-6 text-center text-sm text-muted-foreground">
          {t(copy.empty)}
        </p>
      ) : (
        <table className="w-full text-sm">
          <caption className="sr-only">
            {t(copy.caption, { bucket: t(BUCKET_NAME[bucket]) })}
          </caption>
          <thead>
            <tr className="text-left text-muted-foreground">
              <th scope="col" className="w-44 py-1 font-normal" />
              <th scope="col" className="font-normal">
                {t(copy.opens)}
              </th>
              <th scope="col" className="font-normal">
                {t(copy.clicks)}
              </th>
            </tr>
          </thead>
          <tbody>
            {points.map((p) => (
              <tr key={p.at}>
                <th scope="row" className="whitespace-nowrap py-1 pr-2 text-left font-normal">
                  {bucketLabel(p.at, bucket, locale ?? 'en')}
                </th>
                <td className="pr-4">
                  <Bar kind="opens" value={p.opens} max={max} />
                </td>
                <td>
                  <Bar kind="clicks" value={p.clicks} max={max} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </section>
  );
}
