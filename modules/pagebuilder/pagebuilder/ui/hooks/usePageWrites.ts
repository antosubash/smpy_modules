import { useCallback, useState } from 'react';

import type { PageRead, PageWritePayload } from '../utils/api';
import { keys, translate } from '../utils/i18n';
import { savePage } from '../utils/pagesApi';
import { HttpError } from '../utils/request';
import { useMountedRef } from './useMountedRef';

/** One queue and send-time version for draft and workflow writes. */
export function usePageWrites(pageId: number | null, initialVersion: string | null) {
  const mounted = useMountedRef(pageId ?? undefined);
  // Capture each identity's queue so an old response cannot block a new page.
  const [queue, setQueue] = useState({
    pageId,
    version: initialVersion,
    tail: Promise.resolve<unknown>(undefined),
    blocked: false,
    missing: false,
  });
  const [conflict, setConflict] = useState(false);
  const [missing, setMissing] = useState(false);
  if (queue.pageId !== pageId) {
    setQueue({
      pageId,
      version: initialVersion,
      tail: Promise.resolve(undefined),
      blocked: false,
      missing: false,
    });
    setConflict(false);
    setMissing(false);
  }
  const acceptWrite = useCallback(
    (page: Pick<PageRead, 'updated_at'>) => {
      queue.version = page.updated_at;
    },
    [queue],
  );

  const run = useCallback(
    <T extends Pick<PageRead, 'updated_at'>>(
      action: (token: string | null) => Promise<T>,
      overwrite = false,
    ): Promise<T> => {
      const next = queue.tail.then(async () => {
        if (!mounted.current) throw new Error(translate(keys.pagebuilder.workflow.save_failed));
        if (queue.missing) {
          throw new HttpError(translate(keys.pagebuilder.errors.page_gone), 404, 'page_not_found');
        }
        if (queue.blocked && !overwrite) {
          throw new HttpError(
            translate(keys.pagebuilder.errors.page_conflict),
            409,
            'page_conflict',
          );
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
          } else if (e instanceof HttpError && e.code === 'page_conflict') {
            queue.blocked = true;
            if (mounted.current) setConflict(true);
          }
          throw e;
        }
      });
      queue.tail = next.catch(() => undefined);
      return next;
    },
    [acceptWrite, mounted, queue],
  );

  const save = (payload: PageWritePayload, overwrite = false) =>
    run((token) => {
      if (pageId === null) throw new Error(translate(keys.pagebuilder.workflow.save_first));
      return savePage(pageId, {
        ...payload,
        ...(overwrite ? {} : { expected_updated_at: token }),
      });
    }, overwrite);

  return { conflict, missing, run, save, acceptWrite };
}

export type PageWrites = ReturnType<typeof usePageWrites>;
