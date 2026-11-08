/**
 * One import job on the Import screen: the upload, the mapping, the apply, and
 * the progress of a queued or running job.
 *
 * While the job is `queued` or `running` it is re-fetched every `IMPORT_POLL_MS`
 * (through a failed fetch too); polling stops with the first answer in any other
 * status. Unmounting aborts the request in flight.
 */

import { useCallback, useEffect, useRef, useState } from 'react';

import { errorMessage, HttpError } from '../utils/http';
import { useT } from '../utils/i18n';
import * as importApi from '../utils/importApi';
import type { ImportJob, ImportMapping } from '../utils/importTypes';

export const IMPORT_POLL_MS = 2_000;

const LIVE = new Set(['queued', 'running']);

export function useImport(initialId: number | null) {
  const { t } = useT();
  const [job, setJob] = useState<ImportJob | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const mounted = useRef(new AbortController());
  const latest = useRef(0);
  const tRef = useRef(t);
  tRef.current = t;
  const jobId = job?.id ?? null;
  const jobIdRef = useRef<number | null>(null);
  jobIdRef.current = jobId;
  const status = job?.status;
  const live = job !== null && LIVE.has(job.status);

  useEffect(() => {
    const abort = new AbortController();
    mounted.current = abort;
    return () => abort.abort();
  }, []);

  /** A refusal means this screen's state is stale: a 404 returns to the start (the message
   *  stays), a 409 reloads the import being shown, so the tab never acts on old state. */
  const resync = async (e: unknown, signal: AbortSignal, ticket: number) => {
    if (!(e instanceof HttpError)) return;
    if (e.status === 404) {
      setJob(null);
    } else if (e.status === 409 && jobIdRef.current !== null) {
      try {
        const fresh = await importApi.getImport(jobIdRef.current, signal);
        if (!signal.aborted && ticket === latest.current) setJob(fresh);
      } catch (again) {
        if (again instanceof HttpError && again.status === 404 && !signal.aborted) setJob(null);
      }
    }
  };

  /** Runs a call, adopting its job (null clears it); the failure becomes `error`.
   *  Resolves `true` only when the call succeeded and its answer was adopted. */
  // biome-ignore lint/correctness/useExhaustiveDependencies: `resync` uses only refs and setters
  const run = useCallback(async (call: () => Promise<ImportJob | null>): Promise<boolean> => {
    const { signal } = mounted.current;
    const ticket = ++latest.current;
    setBusy(true);
    setError(null);
    try {
      const next = await call();
      if (signal.aborted || ticket !== latest.current) return false;
      setJob(next);
      return true;
    } catch (e) {
      if (!signal.aborted && ticket === latest.current) {
        setError(errorMessage(e, tRef.current));
        await resync(e, signal, ticket);
      }
      return false;
    } finally {
      if (!signal.aborted && ticket === latest.current) setBusy(false);
    }
  }, []);

  const open = useCallback(
    (id: number) => {
      void run(() => importApi.getImport(id, mounted.current.signal));
    },
    [run],
  );

  useEffect(() => {
    if (initialId !== null) open(initialId);
  }, [initialId, open]);

  useEffect(() => {
    if (!live || jobId === null) return;
    const { signal } = mounted.current;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let stopped = false;
    const next = () => {
      timer = setTimeout(async () => {
        try {
          const fresh = await importApi.getImport(jobId, signal);
          if (stopped || signal.aborted) return;
          setJob(fresh);
          setError(null);
          if (!LIVE.has(fresh.status)) return;
        } catch (e) {
          if (stopped || signal.aborted) return;
          setError(errorMessage(e, tRef.current));
          // A refusal (gone, forbidden) will not change by asking again; a 404 means the
          // import was discarded elsewhere, so return to the start like `resync` does.
          if (e instanceof HttpError && e.status >= 400 && e.status < 500) {
            if (e.status === 404) setJob(null);
            return;
          }
        }
        next();
      }, IMPORT_POLL_MS);
    };
    next();
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, [live, jobId]);

  const upload = useCallback(
    (list: string, files: File[]) => run(() => importApi.uploadImport(list, files)),
    [run],
  );
  const saveMapping = useCallback(
    (mapping: ImportMapping) =>
      jobId === null ? Promise.resolve(false) : run(() => importApi.setMapping(jobId, mapping)),
    [run, jobId],
  );
  const apply = useCallback(
    () => (jobId === null ? Promise.resolve(false) : run(() => importApi.applyImport(jobId))),
    [run, jobId],
  );
  const discard = useCallback(
    () =>
      jobId === null
        ? Promise.resolve(false)
        : run(async () => {
            await importApi.discardImport(jobId, status);
            return null;
          }),
    [run, jobId, status],
  );
  const reset = useCallback(() => {
    setJob(null);
    setError(null);
  }, []);

  return { job, error, busy, upload, saveMapping, apply, discard, open, reset };
}
