import { useCallback, useState } from 'react';

import { keys, translate } from '../utils/i18n';
import { HttpError } from '../utils/request';
import { useMountedRef } from './useMountedRef';

/** One queue and send-time version for an editor's writes. */
export function useVersionedWrites(
  rowId: number | null,
  initialVersion: string | null,
  kind: 'page' | 'layout' = 'page',
) {
  const conflictCode = kind === 'layout' ? 'layout_conflict' : 'page_conflict';
  const conflictKey = keys.pagebuilder.errors[conflictCode];
  const mounted = useMountedRef(rowId ?? undefined);
  // Capture each identity's queue so an old response cannot block a new row.
  const [queue, setQueue] = useState({
    rowId,
    version: initialVersion,
    tail: Promise.resolve<unknown>(undefined),
    blocked: false,
    missing: false,
  });
  const [conflict, setConflict] = useState(false);
  const [missing, setMissing] = useState(false);
  if (queue.rowId !== rowId) {
    setQueue({
      rowId,
      version: initialVersion,
      tail: Promise.resolve(undefined),
      blocked: false,
      missing: false,
    });
    setConflict(false);
    setMissing(false);
  }
  const acceptWrite = useCallback(
    (row: { updated_at: string | null }) => {
      queue.version = row.updated_at;
    },
    [queue],
  );

  const run = useCallback(
    <T extends { updated_at: string | null }>(
      action: (token: string | null) => Promise<T>,
      overwrite = false,
    ): Promise<T> => {
      const next = queue.tail.then(async () => {
        if (!mounted.current) throw new Error(translate(keys.pagebuilder.workflow.save_failed));
        if (queue.missing) {
          throw new HttpError(translate(keys.pagebuilder.errors.page_gone), 404, 'page_not_found');
        }
        if (queue.blocked && !overwrite) {
          throw new HttpError(translate(conflictKey), 409, conflictCode);
        }
        try {
          const result = await action(queue.version);
          acceptWrite(result);
          if (overwrite) {
            queue.blocked = false;
            if (mounted.current) setConflict(false);
          }
          return result;
        } catch (e) {
          if (e instanceof HttpError && e.status === 404 && e.code === 'page_not_found') {
            queue.missing = true;
            queue.blocked = false;
            if (mounted.current) {
              setMissing(true);
              setConflict(false);
            }
          } else if (e instanceof HttpError && e.code === conflictCode) {
            queue.blocked = true;
            if (mounted.current) setConflict(true);
          }
          throw e;
        }
      });
      queue.tail = next.catch(() => undefined);
      return next;
    },
    [acceptWrite, conflictCode, conflictKey, mounted, queue],
  );

  return { conflict, missing, run, acceptWrite };
}
