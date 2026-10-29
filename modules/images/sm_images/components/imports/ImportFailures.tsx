import { keys, useT } from '../../utils/i18n';
import { errorCodeLabel } from '../../utils/labels';
import type { ImportError } from '../../utils/types';

/** How many failed rows the card lists; the rest are counted. */
export const FAILURES_SHOWN = 5;

/** A failed row's entry (it names its `item`), as opposed to a job-level error. */
export const isRowError = (e: ImportError) => typeof e.item === 'number';

/**
 * Why rows of an import failed, collapsed: each listed row's HTTP answer (or
 * its error's label) and the host and path it was fetched from; past
 * {@link FAILURES_SHOWN}, how many more failed (`failed` counts every one).
 */
export function ImportFailures({ errors, failed }: { errors: ImportError[]; failed: number }) {
  const { t } = useT();
  const text = keys.images.imports.job;
  const rows = errors.filter(isRowError);
  if (rows.length === 0 || failed === 0) return null;
  const shown = rows.slice(0, FAILURES_SHOWN);
  const more = Math.max(0, failed - shown.length);
  return (
    <details className="text-sm" data-testid="images-import-failures">
      <summary className="cursor-pointer text-destructive">
        {t(text.failures, { count: failed })}
      </summary>
      <ul className="mt-1 space-y-0.5 text-muted-foreground">
        {shown.map((e) => {
          const why =
            e.status !== undefined
              ? t(text.failure_http, { status: e.status, reason: e.reason ?? '' }).trim()
              : errorCodeLabel(t, e.code);
          return (
            <li
              key={`${e.item}-${e.at ?? ''}`}
              className="break-words"
              title={e.code}
              data-testid="images-import-failure"
            >
              {t(text.failure_row, { row: (e.item ?? 0) + 1, why })}
              {e.where ? ` · ${e.where}` : ''}
            </li>
          );
        })}
        {more > 0 && (
          <li data-testid="images-import-failures-more">
            {t(text.failures_more, { count: more })}
          </li>
        )}
      </ul>
    </details>
  );
}
