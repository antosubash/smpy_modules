import { useEffect, useRef, useState } from 'react';

import { getRegroup } from '../utils/api-groups';
import { ApiError, errorText } from '../utils/api-net';
import type { RegroupJob } from '../utils/types';

export const POLL_MS = 2000;
/** The longest wait between two reads after failures (2 s, 4 s, ... 30 s). */
export const MAX_BACKOFF_MS = 30_000;
/** Consecutive failed reads after which polling stops and says why. */
export const MAX_FAILURES = 10;

export type RegroupPoll = {
  job: RegroupJob | null;
  /** The job no longer exists (404): polling stopped. */
  gone: boolean;
  /** Why polling gave up after `MAX_FAILURES` failed reads in a row. */
  error: string | null;
};

/** A background regroup's progress: read at once, then every `POLL_MS` while it
 *  runs. `onFinished` runs once when polling sees it leave `running` (or find
 *  it gone), so the groups list can refresh. A failed read keeps the last
 *  progress shown and backs off; `MAX_FAILURES` in a row stop it. */
export function useRegroupJob(jobId: string | null, onFinished?: () => void): RegroupPoll {
  const [poll, setPoll] = useState<RegroupPoll>({ job: null, gone: false, error: null });
  const finished = useRef(onFinished);
  finished.current = onFinished;

  useEffect(() => {
    setPoll({ job: null, gone: false, error: null });
    if (!jobId) return;
    let alive = true;
    let timer: number | undefined;
    let failures = 0;
    const tick = async () => {
      let wait = POLL_MS;
      try {
        const next = await getRegroup(jobId);
        if (!alive) return;
        failures = 0;
        setPoll((p) => ({ ...p, job: next }));
        if (next.status !== 'running') {
          finished.current?.();
          return;
        }
      } catch (e) {
        if (!alive) return;
        if (e instanceof ApiError && e.status === 404) {
          setPoll((p) => ({ ...p, gone: true }));
          finished.current?.();
          return;
        }
        failures += 1;
        if (failures >= MAX_FAILURES) {
          setPoll((p) => ({ ...p, error: errorText(e) }));
          return;
        }
        wait = Math.min(POLL_MS * 2 ** (failures - 1), MAX_BACKOFF_MS);
      }
      if (alive) timer = window.setTimeout(() => void tick(), wait);
    };
    void tick();
    return () => {
      alive = false;
      window.clearTimeout(timer);
    };
  }, [jobId]);

  return poll;
}
