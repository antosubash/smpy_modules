import { useEffect, useState } from 'react';
import { errorText } from '../utils/api';
import { previewRecurrence } from '../utils/api-events';
import type { PreviewOccurrence, TimesInput } from '../utils/types-events';
import { useLatestRequest } from './useLatestRequest';

const DEBOUNCE_MS = 400;
const NEXT = 10;

/** The next occurrences of the schedule in the form, asked after the typing
 *  pauses. A newer ask supersedes the one before it, and a failed one shows
 *  its message instead of a list. */
export function usePreview({
  times,
  rrule,
  eventId,
  calendarId,
}: {
  times: TimesInput;
  rrule: string;
  eventId: string | null;
  calendarId: string;
}) {
  const [occurrences, setOccurrences] = useState<PreviewOccurrence[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const begin = useLatestRequest();
  const ready = Boolean(rrule.trim() && times.start && times.end && times.timezone);
  const key = JSON.stringify([times, rrule, eventId, calendarId]);
  // biome-ignore lint/correctness/useExhaustiveDependencies: `key` stands for its parts
  useEffect(() => {
    if (!ready) {
      begin(); // whatever is still in flight no longer applies
      setOccurrences([]);
      setError(null);
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
    return () => clearTimeout(timer);
  }, [key, ready, begin]);
  return { occurrences, loading, error, enabled: ready };
}
