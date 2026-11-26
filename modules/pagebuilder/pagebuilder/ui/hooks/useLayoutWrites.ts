import { router } from '@inertiajs/react';
import type { Data } from '@puckeditor/core';
import { useState } from 'react';

import { type LayoutDetail, restoreLayoutRevision, saveLayout } from '../utils/api';
import { keys, useT } from '../utils/i18n';
import { HttpError } from '../utils/request';
import { useVersionedWrites } from './useVersionedWrites';

/** The layout screen's guarded writes: Save, Restore, and Overwrite after a refusal (#466). */
export function useLayoutWrites(
  layout: LayoutDetail,
  headerData: Data,
  footerData: Data,
  onRestored: (restored: LayoutDetail) => void,
) {
  const { t } = useT();
  const writes = useVersionedWrites(layout.id, layout.updated_at, 'layout');
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  // The restore a conflict refused: Overwrite then repeats it, not a save of this screen.
  const [refusedRestore, setRefusedRestore] = useState<number | null>(null);

  const save = async (overwrite = false) => {
    setBusy(true);
    setMessage(null);
    try {
      await writes.run(
        (token) =>
          saveLayout({
            header_data: headerData as unknown as Record<string, unknown>,
            footer_data: footerData as unknown as Record<string, unknown>,
            ...(overwrite ? {} : { expected_updated_at: token }),
          }),
        overwrite,
      );
      setMessage(t(keys.pagebuilder.layout.saved));
      router.reload({ only: ['revisions'] });
    } catch (e) {
      if (e instanceof HttpError && e.code === 'layout_conflict') setRefusedRestore(null);
      else {
        setMessage(e instanceof Error ? e.message : t(keys.pagebuilder.layout.save_failed));
      }
    } finally {
      setBusy(false);
    }
  };

  // History failures belong to the row dialog; banner overwrite failures appear on screen.
  const restore = async (revisionId: number, overwrite = false) => {
    setBusy(true);
    setMessage(null);
    try {
      const restored = await writes.run(
        (token) => restoreLayoutRevision(revisionId, overwrite ? undefined : token),
        overwrite,
      );
      setRefusedRestore(null);
      onRestored(restored);
      setMessage(t(keys.pagebuilder.layout.revision_restored));
      router.reload({ only: ['revisions'] });
    } catch (e) {
      // Close the dialog so Reload and Overwrite in the banner are reachable.
      if (e instanceof HttpError && e.code === 'layout_conflict') setRefusedRestore(revisionId);
      else {
        if (!overwrite) throw e;
        setMessage(
          e instanceof Error
            ? e.message
            : t(keys.pagebuilder.confirm.failed, { action: t(keys.pagebuilder.layout.restore) }),
        );
      }
    } finally {
      setBusy(false);
    }
  };

  const overwrite = () => (refusedRestore === null ? save(true) : restore(refusedRestore, true));
  return { busy, message, conflict: writes.conflict, save, restore, overwrite };
}
