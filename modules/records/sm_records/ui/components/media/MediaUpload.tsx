import { Button } from '@simple-module-py/ui/components/ui/button';
import { UploadIcon } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { keys, useT } from '../../utils/i18n';
import { formatNumber } from '../../utils/locale';

import {
  type MediaApi,
  type MediaFile,
  type UploadHandle,
  uploadMediaFile,
} from '../../utils/media-api';

type Progress = { name: string; percent: number };

function percentLabel(percent: number, locale: string | undefined): string {
  return formatNumber(percent / 100, locale, { style: 'percent' });
}

/**
 * The picker's Upload button: one file, sent straight to the media library's
 * upload route, with a progress bar while it goes and the library's own
 * refusal (too large, a type it does not take, no permission) shown in place
 * if it fails. A 401 and a dropped connection arrive as the same `ApiError`s
 * every other request in the module raises (`utils/api-net.ts`), so the
 * message is the familiar one and an expired session redirects to sign-in.
 *
 * The native file input is visually hidden and out of the tab order: the
 * button is the control, and clicking it is what opens the file chooser.
 */
export function MediaUpload({
  api,
  onUploaded,
}: {
  api: MediaApi;
  onUploaded: (file: MediaFile) => void;
}) {
  const { t, locale } = useT();
  const input = useRef<HTMLInputElement>(null);
  const handle = useRef<UploadHandle | null>(null);
  const [progress, setProgress] = useState<Progress | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Closing the dialog mid-upload abandons it rather than letting it land a
  // file nobody is waiting for — the abort is the dialog unmounting this.
  useEffect(() => () => handle.current?.abort(), []);

  const start = (file: File) => {
    setError(null);
    setProgress({ name: file.name, percent: 0 });
    const upload = uploadMediaFile(api, file, (percent) =>
      setProgress({ name: file.name, percent }),
    );
    handle.current = upload;
    upload.promise.then(
      (uploaded) => {
        handle.current = null;
        setProgress(null);
        onUploaded(uploaded);
      },
      (failure: unknown) => {
        handle.current = null;
        if (failure instanceof DOMException && failure.name === 'AbortError') return;
        setProgress(null);
        setError(failure instanceof Error ? failure.message : String(failure));
      },
    );
  };

  return (
    <div className="grid gap-2">
      <input
        ref={input}
        type="file"
        className="sr-only"
        tabIndex={-1}
        aria-hidden="true"
        data-testid="records-media-upload-input"
        onChange={(event) => {
          const file = event.target.files?.[0];
          // Reset so choosing the same file again after a failure still fires.
          event.target.value = '';
          if (file) start(file);
        }}
      />
      <Button
        type="button"
        variant="outline"
        className="justify-self-start"
        disabled={progress !== null}
        onClick={() => input.current?.click()}
        data-testid="records-media-upload"
      >
        <UploadIcon aria-hidden="true" />
        {t(keys.records.media.upload)}
      </Button>
      {progress && (
        <div className="grid gap-1" role="status" data-testid="records-media-upload-progress">
          <span className="truncate text-xs text-muted-foreground">
            {t(keys.records.media.uploading, {
              name: progress.name,
              percent: percentLabel(progress.percent, locale),
            })}
          </span>
          <progress
            className="h-2 w-full"
            max={100}
            value={progress.percent}
            aria-label={t(keys.records.media.upload_progress_label)}
          />
        </div>
      )}
      {error && (
        <p
          className="text-sm text-destructive"
          role="alert"
          data-testid="records-media-upload-error"
        >
          {t(keys.records.media.upload_failed, {
            message: error,
          })}
        </p>
      )}
    </div>
  );
}
