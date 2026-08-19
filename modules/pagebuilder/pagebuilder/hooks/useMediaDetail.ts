import { useCallback, useState } from 'react';
import { toast } from 'sonner';

import {
  deleteAssetIfUnused,
  getAssetDetail,
  type MediaAssetDetail,
  updateAsset,
} from '../utils/mediaApi';

export interface MediaDraft {
  alt_text: string;
  caption: string;
  credit: string;
}

/** Loads one asset with its usage list and saves its description.
 *
 * The usage list is re-read on every save rather than cached: the page that was
 * using this image ten seconds ago may have been edited since, and a stale
 * "not used anywhere" is exactly the wrong thing to show above a delete button.
 */
export function useMediaDetail(assetId: number) {
  const [detail, setDetail] = useState<MediaAssetDetail | null>(null);
  const [draft, setDraft] = useState<MediaDraft | null>(null);
  const [busy, setBusy] = useState(false);
  const [dirty, setDirty] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(
    async (signal?: AbortSignal) => {
      try {
        const response = await getAssetDetail(assetId, signal);
        if (signal?.aborted) return;
        setDetail(response);
        setDraft({
          alt_text: response.asset.alt_text,
          caption: response.asset.caption,
          credit: response.asset.credit,
        });
        setDirty(false);
        setError(null);
      } catch (e) {
        if (signal?.aborted) return;
        setError((e as Error).message);
      }
    },
    [assetId],
  );

  const patch = useCallback((next: Partial<MediaDraft>) => {
    setDraft((current) => (current ? { ...current, ...next } : current));
    setDirty(true);
  }, []);

  const save = useCallback(async () => {
    if (!draft) return;
    setBusy(true);
    setError(null);
    try {
      const updated = await updateAsset(assetId, draft);
      if (updated) setDetail(updated);
      setDirty(false);
      toast.success('Saved');
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }, [assetId, draft]);

  /** Rejects with the server's message when the asset is still in use — the
   *  dialog keeps itself open and shows it, which is the whole point of the
   *  refusal naming the pages. */
  const remove = useCallback(() => deleteAssetIfUnused(assetId), [assetId]);

  return { detail, draft, busy, dirty, error, load, patch, save, remove };
}
