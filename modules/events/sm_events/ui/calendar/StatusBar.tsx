/** Loading, error (with retry), empty and truncated: each in words, each with its role. */
import { Button } from '@simple-module-py/ui/components/ui/button';
import type { ReactNode } from 'react';
import type { SourceStatus } from '../extensions/types';
import { errorText } from '../utils/api';
import { keys, useT } from '../utils/i18n';
import { withName } from '../utils/isolate';
import { OCCURRENCE_LIMIT } from '../utils/limits';
import type { FilterOption } from './types';

type Props = {
  loading: boolean;
  error: unknown | null;
  empty: boolean;
  truncated: boolean;
  /** How each plugin source answered; every one that is not `ok` is named. */
  sources?: SourceStatus[];
  sourceLabels?: FilterOption[];
  noCalendars: boolean;
  /** No calendar exists at all (as against none shown), with where to make one, if allowed. */
  noneExist?: boolean;
  action?: ReactNode;
  onRetry: () => void;
};

export function StatusBar({
  loading,
  error,
  empty,
  truncated,
  sources = [],
  sourceLabels = [],
  noCalendars,
  noneExist,
  action,
  onRetry,
}: Props) {
  const { t, locale } = useT();
  const copy = keys.events.calendar.status;
  return (
    <div className="space-y-2" data-testid="calendar-status">
      {loading ? <p role="status">{t(copy.loading)}</p> : null}
      {error ? (
        <div role="alert" className="flex flex-wrap items-center gap-2 text-destructive">
          <span>{errorText(error)}</span>
          <Button type="button" size="sm" variant="outline" onClick={onRetry}>
            {t(keys.events.common.retry)}
          </Button>
        </div>
      ) : null}
      {noCalendars ? (
        <p className="text-muted-foreground">
          {t(noneExist ? copy.none_yet : copy.no_calendars)} {noneExist ? action : null}
        </p>
      ) : null}
      {empty && !loading && !error && !noCalendars ? (
        <p className="text-muted-foreground">{t(copy.empty)}</p>
      ) : null}
      <SourceNotice sources={sources} labels={sourceLabels} />
      {truncated ? (
        <p role="status" className="rounded-md border border-dashed p-2 text-sm">
          {t(copy.truncated, { count: new Intl.NumberFormat(locale).format(OCCURRENCE_LIMIT) })}
        </p>
      ) : null}
    </div>
  );
}

const NOTICE = keys.events.extensions.status;
const WORDS: Record<Exclude<SourceStatus['status'], 'ok'>, string> = {
  failed: NOTICE.failed,
  timeout: NOTICE.timeout,
  skipped: NOTICE.skipped,
  truncated: NOTICE.truncated,
  not_installed: NOTICE.not_installed,
};

/** One line per plugin source that did not answer in full, named by its label (its id when no
 *  label is known). The source's own code is never shown: it is for the logs. */
function SourceNotice({ sources, labels }: { sources: SourceStatus[]; labels: FilterOption[] }) {
  const { t } = useT();
  const seen = new Set<string>();
  const lines = sources.filter((s) => {
    if (s.status === 'ok') return false;
    const id = `${s.id}|${s.status}`;
    if (seen.has(id)) return false;
    seen.add(id);
    return true;
  });
  if (lines.length === 0) return null;
  return (
    <div
      role="status"
      data-testid="source-status"
      className="rounded-md border border-dashed p-2 text-sm"
    >
      <p className="font-medium">{t(NOTICE.heading)}</p>
      <ul className="list-disc pl-5">
        {lines.map((line) => (
          <li key={`${line.id}|${line.status}|${line.calendar_id}`}>
            {withName(
              t,
              WORDS[line.status as keyof typeof WORDS],
              labels.find((l) => l.id === line.id)?.label ?? line.id,
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}
