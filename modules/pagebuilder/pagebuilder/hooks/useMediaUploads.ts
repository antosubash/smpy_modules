/** Upload queue orchestration for the media library. */

import { router } from '@inertiajs/react';
import { useCallback, useState } from 'react';
import { toast } from 'sonner';

import type { UploadItem } from '../components/media/types';
import { type MediaAssetRead, uploadMedia } from '../utils/api';
import { keys, translate } from '../utils/i18n';
import { uploadKey } from '../utils/mediaFormat';

interface Params {
  /** Folder new uploads are filed into; blank means Unfiled. */
  uploadFolder: string;
  /** Called once per successful upload so the page can splice it into view. */
  onUploaded: (asset: MediaAssetRead) => void;
  setMessage: (message: string | null) => void;
}

export interface MediaUploads {
  uploads: UploadItem[];
  startUploads: (files: File[]) => void;
  dismissUpload: (id: string) => void;
}

export function useMediaUploads({ uploadFolder, onUploaded, setMessage }: Params): MediaUploads {
  const [uploads, setUploads] = useState<UploadItem[]>([]);

  const startUploads = useCallback(
    (files: File[]) => {
      if (files.length === 0) return;
      const folderForBatch = uploadFolder.trim();
      const items: UploadItem[] = files.map((file) => ({
        id: uploadKey(file),
        file,
        status: 'pending',
        loaded: 0,
        total: file.size,
        error: null,
      }));
      setUploads((prev) => [...prev, ...items]);
      setMessage(null);

      // Upload sequentially to avoid swamping the server with a 50-file
      // drop; the per-file progress bar is what makes this feel fast.
      void (async () => {
        let succeeded = 0;
        const failures: { name: string; message: string }[] = [];
        for (const item of items) {
          setUploads((prev) =>
            prev.map((u) => (u.id === item.id ? { ...u, status: 'uploading' } : u)),
          );
          try {
            const asset = await uploadMedia(item.file, {
              folder: folderForBatch || null,
              onProgress: (loaded, total) => {
                setUploads((prev) =>
                  prev.map((u) =>
                    u.id === item.id ? { ...u, loaded, total: total || u.total } : u,
                  ),
                );
              },
            });
            setUploads((prev) =>
              prev.map((u) => (u.id === item.id ? { ...u, status: 'done', loaded: u.total } : u)),
            );
            onUploaded(asset);
            succeeded += 1;
          } catch (e) {
            const message =
              e instanceof Error ? e.message : translate(keys.pagebuilder.bundle.upload_failed);
            failures.push({ name: item.file.name, message });
            setUploads((prev) =>
              prev.map((u) => (u.id === item.id ? { ...u, status: 'error', error: message } : u)),
            );
          }
        }
        // One toast per batch: a 50-file drop of the wrong type is one problem.
        if (failures.length === 1) {
          toast.error(
            translate(keys.pagebuilder.errors.upload_toast_single, {
              name: failures[0].name,
              message: failures[0].message,
            }),
          );
        } else if (failures.length > 1) {
          toast.error(
            translate(keys.pagebuilder.errors.upload_toast_batch, { count: failures.length }),
          );
        }
        if (succeeded > 0) {
          setMessage(`Uploaded ${succeeded} file${succeeded === 1 ? '' : 's'}.`);
          // Best-effort: also re-sync via Inertia so the SSR props
          // reflect the new state on next reload.
          router.reload({ only: ['initial'] });
        }
      })();
    },
    [uploadFolder, onUploaded, setMessage],
  );

  const dismissUpload = (id: string) => {
    setUploads((prev) => prev.filter((u) => u.id !== id));
  };

  return { uploads, startUploads, dismissUpload };
}
