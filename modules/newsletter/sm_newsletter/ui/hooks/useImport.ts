/**
 * One import job on the Import screen: the upload, the mapping, the apply, and
 * the progress of a queued or running job.
 *
 * While the job is `queued` or `running` it is re-fetched every `IMPORT_POLL_MS`
 * (through a failed fetch too); polling stops with the first answer in any other
 * status. Unmounting aborts the request in flight.
 */

import { useCallback, useEffect, useRef, useState } from 'react';

import { errorMessage } from '../utils/http';
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
  const tRef = useRef(t);
  tRef.current = t;
  const jobId = job?.id ?? null;
  const live = job !== null && LIVE.has(job.status);

  useEffect(() => {
    const abort = new AbortController();
    mounted.current = abort;
    return () => abort.abort();
  }, []);

  /** Runs a call, adopting its job (null clears it); the failure becomes `error`. */
  const run = useCallback(async (call: () => Promise<ImportJob | null>) => {
    const { signal } = mounted.current;
    setBusy(true);
    setError(null);
    try {
      const next = await call();
      if (signal.aborted) return;
      setJob(next);
    } catch (e) {
      if (!signal.aborted) setError(errorMessage(e, tRef.current));
    } finally {
      if (!signal.aborted) setBusy(false);
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
      jobId === null ? Promise.resolve() : run(() => importApi.setMapping(jobId, mapping)),
    [run, jobId],
  );
  const apply = useCallback(
    () => (jobId === null ? Promise.resolve() : run(() => importApi.applyImport(jobId))),
    [run, jobId],
  );
  const discard = useCallback(
    () =>
      jobId === null
        ? Promise.resolve()
        : run(async () => {
            await importApi.discardImport(jobId);
            return null;
          }),
    [run, jobId],
  );
  const reset = useCallback(() => {
    setJob(null);
    setError(null);
  }, []);

  return { job, error, busy, upload, saveMapping, apply, discard, open, reset };
}
