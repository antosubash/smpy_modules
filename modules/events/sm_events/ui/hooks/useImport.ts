import { useCallback, useEffect, useRef, useState } from 'react';
import { errorText, isGone } from '../utils/api';
import {
  ACTIVE,
  applyImport,
  discardImport,
  getImport,
  type ImportRow,
  type ItemPage,
  listItems,
  POLL_MS,
  uploadImport,
} from '../utils/api-import';

const PATH = () => window.location.pathname;
/** Mirror the import in the address, so a reload resumes it. */
function mirror(id: number | null) {
  window.history.replaceState(null, '', id === null ? PATH() : `${PATH()}?id=${id}`);
}

export type Filter = { verdict?: string; outcome?: string; page?: number };

/** One import's life on the screen: upload, poll while a worker owns it, preview or result.
 *  Polling stops the moment the state is not a working one, and when the page goes away. */
export function useImport(initialId: number | null) {
  const [id, setId] = useState<number | null>(initialId);
  const [row, setRow] = useState<ImportRow | null>(null);
  const [items, setItems] = useState<ItemPage | null>(null);
  const [filter, setFilter] = useState<Filter>({});
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [pulse, setPulse] = useState(0);
  /** Bumped to start reading again (after an apply the import is the worker's). */
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);

  const reset = useCallback(() => {
    setId(null);
    setRow(null);
    setItems(null);
    setFilter({});
    mirror(null);
  }, []);

  // Read the import, and poll for as long as a worker holds it. `pulse` restarts it after an apply.
  // biome-ignore lint/correctness/useExhaustiveDependencies: `pulse` is the trigger, not a read
  useEffect(() => {
    if (id === null) return;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const controller = new AbortController();
    const tick = async () => {
      try {
        const next = await getImport(id, controller.signal);
        if (controller.signal.aborted) return;
        setRow(next);
        setError(null);
        if (ACTIVE.includes(next.status)) timer = setTimeout(() => void tick(), POLL_MS);
      } catch (e) {
        if (controller.signal.aborted) return;
        setError(errorText(e));
        if (isGone(e))
          reset(); // not ours, or gone: back to the upload form with the reason
        else timer = setTimeout(() => void tick(), POLL_MS); // a hiccup: try again
      }
    };
    void tick();
    return () => {
      controller.abort();
      clearTimeout(timer);
    };
  }, [id, pulse, reset]);

  const status = row?.status;
  const processed = row?.processed;
  // The rows: of the preview once staged, of the result once done (the outcome filter).
  // `processed` re-reads them while an apply finishes; it is a trigger, not a read.
  // biome-ignore lint/correctness/useExhaustiveDependencies: see above
  useEffect(() => {
    if (id === null || (status !== 'staged' && status !== 'done')) return;
    const controller = new AbortController();
    listItems(id, filter, controller.signal)
      .then((page) => {
        if (!controller.signal.aborted) setItems(page);
      })
      .catch((e) => {
        if (!controller.signal.aborted) setError(errorText(e));
      });
    return () => controller.abort();
  }, [id, status, processed, filter]);

  const upload = useCallback(async (calendarId: string, file: File) => {
    setBusy(true);
    setError(null);
    try {
      const made = await uploadImport(calendarId, file);
      if (!alive.current) return;
      setRow(made);
      setItems(null);
      setFilter({});
      setId(made.id);
      mirror(made.id);
    } catch (e) {
      if (alive.current) setError(errorText(e));
    } finally {
      if (alive.current) setBusy(false);
    }
  }, []);

  const apply = useCallback(
    async (publish: boolean) => {
      if (id === null) return;
      setBusy(true);
      setError(null);
      try {
        const queued = await applyImport(id, publish);
        if (!alive.current) return;
        setItems(null);
        setFilter({});
        setRow(queued);
        setPulse((n) => n + 1); // the import is a worker's now: poll it
      } catch (e) {
        if (alive.current) setError(errorText(e));
      } finally {
        if (alive.current) setBusy(false);
      }
    },
    [id],
  );

  const discard = useCallback(async () => {
    const current = id;
    reset();
    setError(null);
    if (current === null) return;
    try {
      await discardImport(current);
    } catch (e) {
      if (alive.current) setError(errorText(e));
    }
  }, [id, reset]);

  return { id, row, items, filter, setFilter, error, busy, upload, apply, discard };
}
