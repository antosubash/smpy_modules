import { useEffect, useRef } from 'react';

import { getPipeline } from '../utils/api';
import type { PipelineOverview } from '../utils/types';

/** How often the pipeline's counts are read again while runs are in flight. */
export const PIPELINE_POLL_MS = 3000;

/** Whether any run of the collection is still pending or running. */
export function hasActiveRuns(overview: PipelineOverview | null): boolean {
  if (!overview) return false;
  if (overview.pending > 0) return true;
  return Object.values(overview.status).some((c) => (c.pending ?? 0) + (c.running ?? 0) > 0);
}

/**
 * Re-read the pipeline overview every {@link PIPELINE_POLL_MS} while `active`
 * (runs in flight, or a restart request outstanding), and hand each read to
 * `onRead`. Stops as soon as `active` turns false; one read at a time; the
 * request in flight is aborted on unmount. A failed read is skipped: the next
 * tick tries again.
 */
export function usePipelinePoll(
  collectionId: string,
  active: boolean,
  onRead: (next: PipelineOverview) => void,
): void {
  const handler = useRef(onRead);
  handler.current = onRead;

  useEffect(() => {
    if (!active) return;
    const controller = new AbortController();
    let busy = false;
    const timer = setInterval(() => {
      if (busy) return;
      busy = true;
      getPipeline(collectionId, controller.signal)
        .then((next) => {
          if (!controller.signal.aborted) handler.current(next);
        })
        .catch(() => {})
        .finally(() => {
          busy = false;
        });
    }, PIPELINE_POLL_MS);
    return () => {
      clearInterval(timer);
      controller.abort();
    };
  }, [collectionId, active]);
}
