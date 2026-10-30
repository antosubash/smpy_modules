import { Button } from '@simple-module-py/ui/components/ui/button';
import { useRef, useState } from 'react';
import { toast } from 'sonner';
import { codeMessage, errorText } from '../../utils/api-net';
import { uploadFile } from '../../utils/direct-upload';
import { keys, useT } from '../../utils/i18n';
import type { UploadResult } from '../../utils/types';

/** Pick files and upload them one at a time, in order, so every refusal names
 *  its own file. A file over `directThreshold` (the server's
 *  `direct_upload_threshold`) goes by direct upload, the rest as one multipart
 *  request. `onDone` runs once the batch has finished. */
export function UploadButton({
  collectionId,
  directThreshold,
  onDone,
}: {
  collectionId: string;
  directThreshold: number;
  onDone: () => void;
}) {
  const { t } = useT();
  const input = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);

  const run = async (files: File[]) => {
    setBusy(true);
    const results: UploadResult[] = [];
    try {
      for (const file of files) results.push(await uploadFile(collectionId, file, directThreshold));
    } catch (e) {
      toast.error(errorText(e));
    } finally {
      setBusy(false);
      if (input.current) input.current.value = '';
    }
    for (const r of results.filter((x) => x.status === 'error')) {
      toast.error(
        t(keys.images.upload.file_failed, {
          name: r.filename ?? '',
          reason: codeMessage(r.code) ?? r.detail ?? '',
        }),
      );
    }
    const count = (status: UploadResult['status']) =>
      results.filter((r) => r.status === status).length;
    toast(
      t(keys.images.upload.summary, {
        created: count('created'),
        duplicates: count('duplicate'),
        failed: count('error'),
      }),
    );
    onDone();
  };

  return (
    <>
      <input
        ref={input}
        type="file"
        accept="image/*"
        multiple
        hidden
        data-testid="images-upload-input"
        onChange={(e) => {
          const files = Array.from(e.target.files ?? []);
          if (files.length) void run(files);
        }}
      />
      <Button
        type="button"
        disabled={busy}
        data-testid="images-upload"
        onClick={() => input.current?.click()}
      >
        {busy ? t(keys.images.upload.uploading) : t(keys.images.upload.button)}
      </Button>
    </>
  );
}
