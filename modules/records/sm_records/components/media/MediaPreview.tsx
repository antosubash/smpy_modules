import { useT } from '@simple-module-py/i18n';
import { FileIcon, ImageOffIcon } from 'lucide-react';
import { useState } from 'react';

import { useMediaFile } from '../../hooks/useMediaFile';
import {
  fileUrl,
  forgetMediaFile,
  formatBytes,
  isImage,
  type MediaApi,
  type MediaFile,
} from '../../utils/media-api';
import { formatDateTime } from '../../utils/values';

export type MediaPreviewVariant = 'field' | 'cell';

/** An `<img>` of the file, falling back to the file icon if the download
 *  does not load — a backend that 500s on one object should cost that one
 *  thumbnail its picture, not the chip its name. The cached metadata is
 *  dropped too: the likeliest cause is a file deleted since it was looked
 *  up, and the next render should find that out ("File missing"). */
function Thumbnail({
  api,
  file,
  className,
  alt,
}: {
  api: MediaApi;
  file: MediaFile;
  className: string;
  alt: string;
}) {
  const [broken, setBroken] = useState(false);
  if (!isImage(file) || broken) {
    return (
      <span
        className={`${className} flex shrink-0 items-center justify-center bg-muted text-muted-foreground`}
        data-testid="records-media-icon"
      >
        {broken ? <ImageOffIcon aria-hidden="true" /> : <FileIcon aria-hidden="true" />}
      </span>
    );
  }
  return (
    <img
      src={fileUrl(api, file.id)}
      alt={alt}
      loading="lazy"
      className={`${className} shrink-0 object-cover`}
      data-testid="records-media-thumbnail"
      onError={() => {
        forgetMediaFile(api, file.id);
        setBroken(true);
      }}
    />
  );
}

/** How a list cell shows a long value: one line, clipped with an ellipsis
 *  inside the column's `max-w-48`, the whole value in the `title`. The
 *  table's cells are `whitespace-nowrap`, which beat `break-all`, so a long
 *  URL or a missing file's id ran on under the next column (review 4, ux
 *  F7). The editor's chip (`field`) still wraps: it has the room. */
export const CELL_CLIP = 'block truncate';

/** A value saved before the picker existed — a plain `http(s)` URL — as a
 *  link, whether or not the host has a media library to ask about ids.
 *  `full` is the editor's; a cell clips it (the `title` has it all). */
export function MediaUrlLink({ url, full }: { url: string; full: boolean }) {
  return (
    <a
      href={url}
      target="_blank"
      rel="noopener noreferrer"
      className={`${full ? 'break-all' : CELL_CLIP} text-sm underline`}
      title={url}
      data-testid="records-media-url"
    >
      {url}
    </a>
  );
}

/** Size · type · upload date — the facts the chip and the picker grid show. */
export function MediaFacts({ file }: { file: MediaFile }) {
  return (
    <span className="text-xs text-muted-foreground">
      {[
        formatBytes(file.size_bytes),
        file.content_type,
        file.created_at && formatDateTime(file.created_at),
      ]
        .filter(Boolean)
        .join(' · ')}
    </span>
  );
}

/**
 * A stored `media` value, shown as what it names: a thumbnail for an image, a
 * file icon and name otherwise, a link for a legacy URL, and "File missing"
 * for an id the library no longer has — with the id still visible, because it
 * is still the stored value and nothing here changes it.
 *
 * `field` is the editor's chip (name, size, type, date beside a 6rem
 * thumbnail); `cell` is the list's 2.5rem thumbnail, or an icon and the name.
 */
export function MediaPreview({
  api,
  value,
  variant,
}: {
  api: MediaApi;
  value: string;
  variant: MediaPreviewVariant;
}) {
  const { t } = useT();
  const state = useMediaFile(api, value);
  const field = variant === 'field';

  switch (state.status) {
    case 'empty':
      return null;
    case 'url':
      return <MediaUrlLink url={state.url} full={field} />;
    case 'loading':
      return (
        <span
          role="status"
          className="inline-flex items-center gap-2"
          data-testid="records-media-loading"
        >
          <span
            className={`${field ? 'size-24' : 'size-10'} animate-pulse rounded bg-muted`}
            aria-hidden="true"
          />
          <span className="sr-only">
            {t('records.media.loading_file', { defaultValue: 'Loading file details…' })}
          </span>
        </span>
      );
    case 'missing':
      return (
        <span className="grid min-w-0 gap-0.5" data-testid="records-media-missing">
          <span className="text-sm font-medium text-destructive">
            {t('records.media.file_missing', { defaultValue: 'File missing' })}
          </span>
          <code
            className={`${field ? 'break-all' : CELL_CLIP} text-xs text-muted-foreground`}
            title={value}
          >
            {value}
          </code>
          {field && (
            <span className="text-xs text-muted-foreground">
              {t('records.media.file_missing_help', {
                defaultValue:
                  'This file is no longer in the media library. The record keeps its id until you choose another file or remove it.',
              })}
            </span>
          )}
        </span>
      );
    case 'error':
      return (
        <span className="grid min-w-0 gap-0.5" data-testid="records-media-error">
          <code className={`${field ? 'break-all' : CELL_CLIP} text-xs`} title={value}>
            {value}
          </code>
          <span className="text-xs text-muted-foreground" title={state.message}>
            {t('records.media.details_failed', {
              defaultValue: "Couldn't load this file's details.",
            })}
          </span>
        </span>
      );
    case 'ready': {
      const { file } = state;
      if (!field) {
        return (
          <span className="inline-flex min-w-0 items-center gap-2" title={file.filename}>
            <Thumbnail api={api} file={file} className="size-10 rounded" alt={file.filename} />
            {!isImage(file) && <span className="truncate">{file.filename}</span>}
          </span>
        );
      }
      return (
        <span className="flex min-w-0 items-start gap-3" data-testid="records-media-chip">
          <Thumbnail api={api} file={file} className="size-24 rounded border" alt={file.filename} />
          <span className="grid min-w-0 gap-0.5">
            <a
              href={fileUrl(api, file.id)}
              target="_blank"
              rel="noopener noreferrer"
              className="break-all text-sm font-medium hover:underline"
            >
              {file.filename}
            </a>
            <MediaFacts file={file} />
          </span>
        </span>
      );
    }
  }
}
