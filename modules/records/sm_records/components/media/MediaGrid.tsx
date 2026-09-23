import { useT } from '@simple-module-py/i18n';
import { FileIcon } from 'lucide-react';
import type React from 'react';

import {
  fileUrl,
  formatBytes,
  isImage,
  type MediaApi,
  type MediaFile,
} from '../../utils/media-api';
import { formatDateTime } from '../../utils/values';

const ITEM_SELECTOR = '[data-media-item]';

/** How many items one visual row holds, read off the rendered grid — so
 *  ArrowUp/ArrowDown move a row at whatever breakpoint the dialog is at. A
 *  layout-less DOM (tests) reports one column, which makes them Left/Right. */
function columnCount(list: HTMLElement): number {
  const template = window.getComputedStyle(list).gridTemplateColumns;
  const count = template ? template.split(' ').filter(Boolean).length : 0;
  return count > 0 ? count : 1;
}

/** Arrow keys, Home and End move focus between the items; Tab still walks
 *  them one by one, and Enter or Space on an item is its own button press. */
function moveFocus(event: React.KeyboardEvent<HTMLUListElement>) {
  const items = Array.from(event.currentTarget.querySelectorAll<HTMLElement>(ITEM_SELECTOR));
  const index = items.indexOf(document.activeElement as HTMLElement);
  if (index < 0) return;
  const cols = columnCount(event.currentTarget);
  const target: Record<string, number> = {
    ArrowRight: index + 1,
    ArrowLeft: index - 1,
    ArrowDown: index + cols,
    ArrowUp: index - cols,
    Home: 0,
    End: items.length - 1,
  };
  if (!(event.key in target)) return;
  event.preventDefault();
  const next = Math.min(items.length - 1, Math.max(0, target[event.key]));
  items[next]?.focus();
}

/**
 * The picker's files, as a grid of buttons: a thumbnail for an image and an
 * icon for anything else, then the name, size and upload date. Each item's
 * accessible name carries all four facts, so a screen reader hears what a
 * sighted user sees; the currently stored file is marked `aria-current`.
 */
export function MediaGrid({
  api,
  files,
  currentId,
  onPick,
}: {
  api: MediaApi;
  files: MediaFile[];
  currentId: string | null;
  onPick: (file: MediaFile) => void;
}) {
  const { t } = useT();
  return (
    <ul
      className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4"
      onKeyDown={moveFocus}
      aria-label={t('records.media.grid_label', { defaultValue: 'Files' })}
      data-testid="records-media-grid"
    >
      {files.map((file) => {
        const current = file.id === currentId;
        const date = file.created_at ? formatDateTime(file.created_at) : '';
        const size = formatBytes(file.size_bytes);
        return (
          <li key={file.id} className="min-w-0">
            <button
              type="button"
              data-media-item=""
              data-testid="records-media-item"
              aria-current={current ? 'true' : undefined}
              aria-label={t('records.media.item_label', {
                defaultValue: '{name}, {type}, {size}, uploaded {date}',
                name: file.filename,
                type: file.content_type,
                size,
                date,
              })}
              onClick={() => onPick(file)}
              className={`flex w-full flex-col overflow-hidden rounded-md border text-left outline-none hover:bg-accent focus-visible:ring-2 focus-visible:ring-ring ${
                current ? 'ring-2 ring-primary' : ''
              }`}
            >
              <span className="flex aspect-square w-full items-center justify-center bg-muted">
                {isImage(file) ? (
                  <img
                    src={fileUrl(api, file.id)}
                    alt=""
                    loading="lazy"
                    className="size-full object-cover"
                  />
                ) : (
                  <FileIcon className="size-8 text-muted-foreground" aria-hidden="true" />
                )}
              </span>
              <span className="grid gap-0.5 p-2" aria-hidden="true">
                <span className="truncate text-xs font-medium" title={file.filename}>
                  {file.filename}
                </span>
                <span className="truncate text-xs text-muted-foreground">
                  {[size, date].filter(Boolean).join(' · ')}
                </span>
                {current && (
                  <span className="text-xs font-medium text-primary">
                    {t('records.media.current', { defaultValue: 'Current file' })}
                  </span>
                )}
              </span>
            </button>
          </li>
        );
      })}
    </ul>
  );
}
