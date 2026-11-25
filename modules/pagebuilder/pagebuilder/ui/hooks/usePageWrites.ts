import { useCallback, useRef, useState } from 'react';

import type { PageRead, PageWritePayload } from '../utils/api';
import { keys, translate } from '../utils/i18n';
import { savePage } from '../utils/pagesApi';
import { HttpError } from '../utils/request';
import { useMountedRef } from './useMountedRef';

/** One queue and send-time version for every write to the open page. */
export function usePageWrites(pageId: number | null, initialVersion: string | null) {
  const version = useRef(initialVersion);
  const tail = useRef<Promise<unknown>>(Promise.resolve());
  const blocked = useRef(false);
  const mounted = useMountedRef(pageId ?? undefined);
  const [conflict, setConflict] = useState(false);
  const acceptWrite = useCallback((page: Pick<PageRead, 'updated_at'>) => {
    version.current = page.updated_at;
  }, []);

  const run = useCallback(
    <T extends Pick<PageRead, 'updated_at'>>(
      action: (token: string | null) => Promise<T>,
      overwrite = false,
    ): Promise<T> => {
      const next = tail.current.then(async () => {
        if (!mounted.current) throw new Error(translate(keys.pagebuilder.workflow.save_failed));
        if (blocked.current && !overwrite) {
          throw new HttpError(
            translate(keys.pagebuilder.errors.page_conflict),
            409,
            'page_conflict',
          );
        }
        try {
          const result = await action(version.current);
          acceptWrite(result);
          if (overwrite) {
            blocked.current = false;
            if (mounted.current) setConflict(false);
          }
          return result;
        } catch (e) {
          if (e instanceof HttpError && e.code === 'page_conflict') {
            blocked.current = true;
            if (mounted.current) setConflict(true);
          }
          throw e;
        }
      });
      tail.current = next.catch(() => undefined);
      return next;
    },
    [acceptWrite, mounted],
  );

  const save = (payload: PageWritePayload, overwrite = false) =>
    run((token) => {
      if (pageId === null) throw new Error(translate(keys.pagebuilder.workflow.save_first));
      return savePage(pageId, {
        ...payload,
        ...(overwrite ? {} : { expected_updated_at: token }),
      });
    }, overwrite);

  return { conflict, run, save, acceptWrite };
}

export type PageWrites = ReturnType<typeof usePageWrites>;
