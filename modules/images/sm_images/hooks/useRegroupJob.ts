import { useEffect, useRef, useState } from 'react';

import { getRegroup } from '../utils/api-groups';
import type { RegroupJob } from '../utils/types';

export const POLL_MS = 2000;

/** A background regroup's progress: read at once, then every `POLL_MS` while it
 *  runs. `onFinished` runs once when polling sees it leave `running`, so the
 *  groups list can refresh. A failed read keeps the last progress shown. */
export function useRegroupJob(jobId: string | null, onFinished?: () => void): RegroupJob | null {
  const [job, setJob] = useState<RegroupJob | null>(null);
  const finished = useRef(onFinished);
  finished.current = onFinished;

  useEffect(() => {
    setJob(null);
    if (!jobId) return;
    let alive = true;
    let timer: number | undefined;
    const tick = async () => {
      try {
        const next = await getRegroup(jobId);
        if (!alive) return;
        setJob(next);
        if (next.status !== 'running') {
          finished.current?.();
          return;
        }
      } catch {
        // keep polling: a missed read is not the end of the job
      }
      if (alive) timer = window.setTimeout(() => void tick(), POLL_MS);
    };
    void tick();
    return () => {
      alive = false;
      window.clearTimeout(timer);
    };
  }, [jobId]);

  return job;
}
