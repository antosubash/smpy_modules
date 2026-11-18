import { useEffect, useState } from 'react';
import { errorText } from '../utils/api';
import { previewRecurrence } from '../utils/api-events';
import { knownZone } from '../utils/datetime';
import { keys, translate as t } from '../utils/i18n';
import type { PreviewOccurrence, TimesInput } from '../utils/types-events';
import { useLatestRequest } from './useLatestRequest';

const DEBOUNCE_MS = 400;
const NEXT = 10;

/** Why the server could not answer for these inputs yet, or `null` when it can:
 *  `missing` while something is not filled in, else the message for a zone it
 *  does not know or an end that is not after the start (on or after it for
 *  all-day dates). Each would be refused with a 422. */
function unusable(times: TimesInput, rrule: string, incomplete: boolean): string | null {
  if (incomplete || !rrule.trim() || !times.start || !times.end || !times.timezone) {
    return 'missing';
  }
  if (!knownZone(times.timezone)) return t(keys.events.errors.default_timezone_invalid);
  const ordered = times.all_day ? times.end >= times.start : times.end > times.start;
  return ordered ? null : t(keys.events.errors.end_before_start);
}

/** The next occurrences of the schedule in the form, asked after the typing
 *  pauses and only once the inputs are usable (a half-filled form would be
 *  refused). A newer ask supersedes the one before it, and a failed one shows
 *  its message instead of a list. */
export function usePreview({
  times,
  rrule,
  eventId,
  calendarId,
  incomplete = false,
}: {
  times: TimesInput;
  rrule: string;
  eventId: string | null;
  calendarId: string;
  /** The rule says "ends on a date" and has none yet. */
  incomplete?: boolean;
}) {
  const [occurrences, setOccurrences] = useState<PreviewOccurrence[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const begin = useLatestRequest();
  const reason = unusable(times, rrule, incomplete);
  const ready = reason === null;
  const key = JSON.stringify([times, rrule, eventId, calendarId]);
  // biome-ignore lint/correctness/useExhaustiveDependencies: `key` stands for its parts
  useEffect(() => {
    if (!ready) {
      begin(); // whatever is still in flight no longer applies
      setOccurrences([]);
      setError(reason === 'missing' ? null : reason);
      setLoading(false);
      return;
    }
    setLoading(true);
    const timer = setTimeout(() => {
      const request = begin();
      previewRecurrence(
        {
          times,
          rrule,
          count: NEXT,
          ...(eventId ? { event_id: eventId } : { calendar_id: calendarId }),
        },
        request.signal,
      )
        .then((preview) => {
          if (!request.alive()) return;
          setOccurrences(preview.occurrences);
          setError(null);
        })
        .catch((e) => {
          if (!request.alive()) return;
          setOccurrences([]);
          setError(errorText(e));
        })
        .finally(() => {
          if (request.alive()) setLoading(false);
        });
    }, DEBOUNCE_MS);
    return () => {
      clearTimeout(timer);
      begin(); // an ask still in flight is for the schedule before this edit
    };
  }, [key, reason, begin]);
  return { occurrences, loading, error, enabled: ready };
}
