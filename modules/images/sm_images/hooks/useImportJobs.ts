import { useCallback, useEffect, useRef, useState } from 'react';

import { controlImport, deleteImport, listImports } from '../utils/api-imports';
import type { ImportControl, ImportJob, JobStatus } from '../utils/types';

/** Statuses in which the server is still working on a job. */
const ACTIVE: JobStatus[] = ['uploading', 'pending', 'staging', 'running', 'resetting'];
export const POLL_MS = 2000;
/** A runner silent this long may be replaced by a resume (the server's `STALE_AFTER`). */
const STALL_MS = 5 * 60 * 1000;

export const isActive = (job: ImportJob): boolean => ACTIVE.includes(job.status);

/** An active job whose runner has not beaten its heart for a while. */
export function isStalled(job: ImportJob, now = Date.now()): boolean {
  if (!isActive(job) || job.status === 'uploading') return false;
  return !job.heartbeat_at || now - Date.parse(job.heartbeat_at) > STALL_MS;
}

export type ImportJobs = {
  jobs: ImportJob[];
  loading: boolean;
  error: string | null;
  reload: () => Promise<void>;
  /** Run a control; the answered job replaces the row at once. */
  control: (job: ImportJob, control: ImportControl) => Promise<void>;
  remove: (job: ImportJob) => Promise<void>;
};

/**
 * The collection's import jobs. Polls only while a job is active, and stops
 * the moment none is. `onSettled` runs when polling saw a job leave the active
 * states, so the gallery can show what the import added.
 */
export function useImportJobs(
  collectionId: string,
  enabled: boolean,
  onSettled?: () => void,
  intervalMs = POLL_MS,
): ImportJobs {
  const [jobs, setJobs] = useState<ImportJob[]>([]);
  const [loading, setLoading] = useState(enabled);
  const [error, setError] = useState<string | null>(null);
  const settled = useRef(onSettled);
  settled.current = onSettled;
  const hadActive = useRef(false);
  const ticket = useRef(0);

  const apply = useCallback((next: ImportJob[]) => {
    const active = next.some(isActive);
    if (hadActive.current && !active) settled.current?.();
    hadActive.current = active;
    setJobs(next);
  }, []);

  const reload = useCallback(async () => {
    const mine = ++ticket.current;
    try {
      const { items } = await listImports(collectionId);
      if (mine !== ticket.current) return;
      apply(items);
      setError(null);
    } catch (e) {
      if (mine === ticket.current) setError(e instanceof Error ? e.message : String(e));
    } finally {
      if (mine === ticket.current) setLoading(false);
    }
  }, [collectionId, apply]);

  useEffect(() => {
    if (enabled) void reload();
    return () => {
      ticket.current++;
    };
  }, [enabled, reload]);

  const polling = enabled && jobs.some(isActive);
  useEffect(() => {
    if (!polling) return;
    const timer = window.setInterval(() => void reload(), intervalMs);
    return () => window.clearInterval(timer);
  }, [polling, reload, intervalMs]);

  const control = useCallback(async (job: ImportJob, action: ImportControl) => {
    const answered = await controlImport(job.id, action);
    ticket.current++; // an older list answer must not undo this
    setJobs((all) => all.map((j) => (j.id === answered.id ? answered : j)));
    hadActive.current = hadActive.current || isActive(answered);
  }, []);

  const remove = useCallback(async (job: ImportJob) => {
    await deleteImport(job.id);
    ticket.current++;
    setJobs((all) => all.filter((j) => j.id !== job.id));
  }, []);

  return { jobs, loading, error, reload, control, remove };
}
