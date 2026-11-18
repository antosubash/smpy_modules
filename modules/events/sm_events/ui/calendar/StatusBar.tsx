/** Loading, error (with retry), empty and truncated: each in words, each with its role. */
import { Button } from '@simple-module-py/ui/components/ui/button';
import type { ReactNode } from 'react';
import { errorText } from '../utils/api';
import { keys, useT } from '../utils/i18n';
import { OCCURRENCE_LIMIT } from '../utils/limits';

type Props = {
  loading: boolean;
  error: unknown | null;
  empty: boolean;
  truncated: boolean;
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
      {truncated ? (
        <p role="status" className="rounded-md border border-dashed p-2 text-sm">
          {t(copy.truncated, { count: new Intl.NumberFormat(locale).format(OCCURRENCE_LIMIT) })}
        </p>
      ) : null}
    </div>
  );
}
