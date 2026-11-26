import type { PageWritePayload } from '../utils/api';
import { keys, translate } from '../utils/i18n';
import { savePage } from '../utils/pagesApi';
import { useVersionedWrites } from './useVersionedWrites';

/** Draft and workflow writes share one queue and the last accepted version. */
export function usePageWrites(pageId: number | null, initialVersion: string | null) {
  const writes = useVersionedWrites(pageId, initialVersion);
  const save = (payload: PageWritePayload, overwrite = false) =>
    writes.run((token) => {
      if (pageId === null) throw new Error(translate(keys.pagebuilder.workflow.save_first));
      return savePage(pageId, {
        ...payload,
        ...(overwrite ? {} : { expected_updated_at: token }),
      });
    }, overwrite);

  return { ...writes, save };
}

export type PageWrites = ReturnType<typeof usePageWrites>;
