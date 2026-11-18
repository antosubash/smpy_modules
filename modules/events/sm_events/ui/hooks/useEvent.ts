import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { errorText, isGone } from '../utils/api';
import { getEvent } from '../utils/api-events';
import { emptyForm, type FormState, type TextForm, toForm } from '../utils/event-form';
import type { EventDetail } from '../utils/types-events';
import { useLatestRequest } from './useLatestRequest';
import type { ScopedRequest } from './useRequestScope';

export type LoadState = 'loading' | 'ready' | 'gone' | 'error';

/** The editor's event and its form. `base` is what the form is compared with to
 *  find what to save: the loaded event, or after a conflict the newer one the
 *  form is about to be saved over. */
export function useEvent({
  eventId,
  locales,
  timezone,
}: {
  eventId: string | null;
  locales: readonly string[];
  timezone: string;
}) {
  const [event, setEvent] = useState<EventDetail | null>(null);
  const [state, setState] = useState<LoadState>(eventId ? 'loading' : 'ready');
  const [loadError, setLoadError] = useState<string | null>(null);
  const [form, setForm] = useState<FormState>(() => emptyForm(timezone, locales));
  const [base, setBase] = useState<FormState>(form);
  const [tab, setTab] = useState(locales[0] ?? 'en');
  const begin = useLatestRequest();

  const adopt = useCallback(
    (next: EventDetail) => {
      const loaded = toForm(next, locales);
      setEvent(next);
      setForm(loaded);
      setBase(loaded);
      setState('ready');
    },
    [locales],
  );
  /** Their version becomes the base the form is saved against; the form stays. */
  const rebase = useCallback(
    (theirs: EventDetail) => {
      setEvent(theirs);
      setBase(toForm(theirs, locales));
    },
    [locales],
  );
  const fetchEvent = useCallback(
    (request: ScopedRequest) => getEvent(eventId ?? '', undefined, request.signal),
    [eventId],
  );
  const load = useCallback(async () => {
    if (!eventId) return;
    const request = begin();
    setState('loading');
    setLoadError(null);
    try {
      const next = await fetchEvent(request);
      if (request.alive()) adopt(next);
    } catch (e) {
      if (!request.alive()) return;
      if (isGone(e)) setState('gone');
      else {
        setState('error');
        setLoadError(errorText(e));
      }
    }
  }, [eventId, begin, fetchEvent, adopt]);
  useEffect(() => {
    void load();
  }, [load]);

  /** Fetch again and replace the form: for use only when it holds no edits. */
  const reload = useCallback(async () => {
    const request = begin();
    const next = await fetchEvent(request);
    if (request.alive()) adopt(next);
  }, [begin, fetchEvent, adopt]);

  const dirty = useMemo(() => JSON.stringify(form) !== JSON.stringify(base), [form, base]);
  /** What the form and its base are right now, for a completion that must not
   *  trust what it captured when its request started. */
  const latest = useRef({ form, base });
  latest.current = { form, base };
  const setFields = useCallback(
    (patch: Partial<FormState>) => setForm((now) => ({ ...now, ...patch })),
    [],
  );
  const setText = useCallback(
    (locale: string, patch: Partial<TextForm>) =>
      setForm((now) => {
        const current = now.texts[locale];
        return current
          ? { ...now, texts: { ...now.texts, [locale]: { ...current, ...patch } } }
          : now;
      }),
    [],
  );
  return {
    event,
    state,
    loadError,
    form,
    base,
    dirty,
    latest,
    tab,
    setTab,
    setForm,
    setFields,
    setText,
    adopt,
    rebase,
    fetchEvent,
    load,
    reload,
    markGone: useCallback(() => setState('gone'), []),
  };
}

export type EventState = ReturnType<typeof useEvent>;
