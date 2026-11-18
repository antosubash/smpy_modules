import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { errorText } from '../utils/api';
import { listEvents } from '../utils/api-events';
import type { EventPage, ListStatus } from '../utils/types-events';
import { useLatestRequest } from './useLatestRequest';

export type Filters = {
  calendar: string;
  status: '' | ListStatus;
  category: string;
  from: string;
  to: string;
  q: string;
  trash: boolean;
  page: number;
};
export const NO_FILTERS: Filters = {
  calendar: '',
  status: '',
  category: '',
  from: '',
  to: '',
  q: '',
  trash: false,
  page: 1,
};
const STATUSES = ['draft', 'in_review', 'published', 'scheduled'];
const DEBOUNCE_MS = 300;
const PAGE_SIZE = 50;
const TRASH = '1';

export function filtersFromQuery(search: string): Filters {
  const qs = new URLSearchParams(search);
  const status = qs.get('status') ?? '';
  const page = Number(qs.get('page'));
  return {
    calendar: qs.get('calendar') ?? '',
    status: STATUSES.includes(status) ? (status as ListStatus) : '',
    category: qs.get('category') ?? '',
    from: qs.get('from') ?? '',
    to: qs.get('to') ?? '',
    q: qs.get('q') ?? '',
    trash: qs.get('trash') === TRASH,
    page: Number.isInteger(page) && page > 0 ? page : 1,
  };
}

function toQuery(filters: Filters): string {
  const qs = new URLSearchParams();
  const { page, trash, ...text } = filters;
  for (const [name, value] of Object.entries(text)) if (value) qs.set(name, value);
  if (trash) qs.set('trash', TRASH);
  if (page > 1) qs.set('page', String(page));
  return qs.toString();
}

/** A date from the filter in the browser's timezone, as the instant the API takes. */
const dayStart = (date: string, plusDays = 0): string | undefined => {
  if (!date) return undefined;
  const at = new Date(`${date}T00:00:00`);
  at.setDate(at.getDate() + plusDays);
  return Number.isNaN(at.getTime()) ? undefined : at.toISOString();
};

/** The list's filters (mirrored in the URL), its page of events, and a
 *  refetch that supersedes the one before it. The text filter waits for the
 *  typing to pause. `locale` asks for titles in the console's language. */
export function useEvents(locale?: string) {
  const [filters, setFilters] = useState<Filters>(() => filtersFromQuery(location.search));
  const [applied, setApplied] = useState(filters);
  const [data, setData] = useState<EventPage | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  const begin = useLatestRequest();
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);

  const change = useCallback((patch: Partial<Filters>) => {
    setFilters((now) => ({ ...now, page: 1, ...patch }));
    clearTimeout(timer.current);
    // Typing waits for a pause; any other filter applies at once.
    const typing = Object.keys(patch).length === 1 && 'q' in patch;
    const apply = () => setApplied((now) => ({ ...now, page: 1, ...patch }));
    if (typing) timer.current = setTimeout(apply, DEBOUNCE_MS);
    else apply();
  }, []);
  useEffect(() => () => clearTimeout(timer.current), []);

  useEffect(() => {
    const text = toQuery(applied);
    // Keep `history.state`: it holds the page Inertia restores on Back (a null here left a Back
    // from the editor on the editor).
    history.replaceState(
      history.state,
      '',
      text ? `${location.pathname}?${text}` : location.pathname,
    );
  }, [applied]);

  // `tick` is the reload trigger, not a read.
  // biome-ignore lint/correctness/useExhaustiveDependencies: see above
  useEffect(() => {
    const request = begin();
    setLoading(true);
    setError(null);
    listEvents(
      {
        calendar: applied.calendar,
        status: applied.status || undefined,
        category: applied.category,
        from: dayStart(applied.from),
        to: dayStart(applied.to, 1),
        q: applied.q.trim(),
        trashed: applied.trash,
        locale,
        page: applied.page,
        page_size: PAGE_SIZE,
      },
      request.signal,
    )
      .then((page) => {
        if (request.alive()) setData(page);
      })
      .catch((e) => {
        if (!request.alive()) return;
        setData(null);
        setError(errorText(e));
      })
      .finally(() => {
        if (request.alive()) setLoading(false);
      });
  }, [applied, locale, tick, begin]);

  return useMemo(
    () => ({
      filters,
      change,
      setPage: (page: number) => {
        setFilters((now) => ({ ...now, page }));
        setApplied((now) => ({ ...now, page }));
      },
      items: data?.items ?? [],
      total: data?.total ?? 0,
      pageSize: data?.page_size ?? PAGE_SIZE,
      loading,
      error,
      reload: () => setTick((n) => n + 1),
    }),
    [filters, change, data, loading, error],
  );
}
