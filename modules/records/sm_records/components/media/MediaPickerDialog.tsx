import { Button } from '@simple-module-py/ui/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@simple-module-py/ui/components/ui/dialog';
import { Input } from '@simple-module-py/ui/components/ui/input';
import { Label } from '@simple-module-py/ui/components/ui/label';
import { useEffect, useState } from 'react';
import { keys, useT } from '../../utils/i18n';

import {
  listMediaFiles,
  type MediaApi,
  type MediaFile,
  type MediaPage,
} from '../../utils/media-api';
import { MediaGrid } from './MediaGrid';
import { MediaUpload } from './MediaUpload';

type ListState =
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'ready'; page: MediaPage };

const SEARCH_ID = 'records-media-search';
const SEARCH_DEBOUNCE_MS = 250;

/** The debounced query that goes to the server — only when the library can
 *  search. Without a search parameter every keystroke filters locally and
 *  nothing is refetched. */
function useServerQuery(api: MediaApi, query: string): string {
  const [debounced, setDebounced] = useState(query);
  useEffect(() => {
    if (!api.search_param) return;
    const timer = window.setTimeout(() => setDebounced(query.trim()), SEARCH_DEBOUNCE_MS);
    return () => window.clearTimeout(timer);
  }, [api.search_param, query]);
  return api.search_param ? debounced : '';
}

/** The dialog's contents. A component of its own because Radix unmounts it
 *  on close: every open starts on page one with an empty search, and a
 *  request still in flight is aborted rather than landing in a closed box. */
function PickerBody({
  api,
  currentId,
  onPick,
}: {
  api: MediaApi;
  currentId: string | null;
  onPick: (file: MediaFile) => void;
}) {
  const { t } = useT();
  const [page, setPage] = useState(1);
  const [query, setQuery] = useState('');
  const [attempt, setAttempt] = useState(0);
  const [list, setList] = useState<ListState>({ status: 'loading' });
  const serverQuery = useServerQuery(api, query);

  // biome-ignore lint/correctness/useExhaustiveDependencies: `attempt` is the Retry button
  useEffect(() => {
    const controller = new AbortController();
    setList({ status: 'loading' });
    listMediaFiles(api, { page, query: serverQuery }, controller.signal).then(
      (result) => setList({ status: 'ready', page: result }),
      (error: unknown) => {
        if (error instanceof DOMException && error.name === 'AbortError') return;
        setList({
          status: 'error',
          message: error instanceof Error ? error.message : String(error),
        });
      },
    );
    return () => controller.abort();
  }, [api, page, serverQuery, attempt]);

  const needle = query.trim().toLowerCase();
  const files =
    list.status !== 'ready'
      ? []
      : api.search_param || !needle
        ? list.page.items
        : list.page.items.filter((file) => file.filename.toLowerCase().includes(needle));
  const pages =
    list.status === 'ready' ? Math.max(1, Math.ceil(list.page.total / list.page.perPage)) : 1;
  // Decided by the files that arrived, not `total`: `file_storage` counts
  // soft-deleted files in `total` (framework #332), so an empty library
  // said "No files on this page match that name" with nothing typed
  // (review 4, ux F9).
  const loaded = list.status === 'ready' ? list.page.items.length : 0;
  const emptyMessage =
    list.status !== 'ready' || files.length > 0
      ? null
      : loaded > 0
        ? t(keys.records.media.no_matches_page)
        : serverQuery
          ? t(keys.records.media.no_matches)
          : page > 1
            ? t(keys.records.media.no_more_files)
            : t(keys.records.media.empty);

  return (
    <>
      <div className="grid gap-3 sm:grid-cols-[1fr_auto] sm:items-end">
        <div className="grid gap-1.5">
          <Label htmlFor={SEARCH_ID}>{t(keys.records.media.search_label)}</Label>
          <Input
            id={SEARCH_ID}
            type="search"
            value={query}
            placeholder={t(keys.records.media.search_placeholder)}
            onChange={(event) => {
              setQuery(event.target.value);
              if (api.search_param) setPage(1);
            }}
          />
        </div>
        <MediaUpload api={api} onUploaded={onPick} />
      </div>
      {!api.search_param && (
        <p className="text-xs text-muted-foreground" data-testid="records-media-search-local">
          {t(keys.records.media.search_page_only)}
        </p>
      )}

      <div className="min-h-0 flex-1 overflow-y-auto" data-testid="records-media-results">
        {list.status === 'loading' && (
          <p role="status" className="py-6 text-center text-sm text-muted-foreground">
            {t(keys.records.media.loading)}
          </p>
        )}
        {list.status === 'error' && (
          <div role="alert" className="grid justify-items-start gap-2 py-4 text-sm">
            <p className="text-destructive">
              {t(keys.records.media.load_failed, {
                message: list.message,
              })}
            </p>
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => setAttempt((n) => n + 1)}
            >
              {t(keys.records.media.retry)}
            </Button>
          </div>
        )}
        {emptyMessage && (
          <p
            className="py-6 text-center text-sm text-muted-foreground"
            data-testid="records-media-empty"
          >
            {emptyMessage}
          </p>
        )}
        {files.length > 0 && (
          <MediaGrid api={api} files={files} currentId={currentId} onPick={onPick} />
        )}
      </div>

      {list.status === 'ready' && pages > 1 && (
        <nav
          className="flex items-center justify-between gap-2 text-sm"
          aria-label={t(keys.records.media.pagination)}
        >
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={page <= 1}
            onClick={() => setPage(page - 1)}
          >
            {t(keys.records.media.previous)}
          </Button>
          <span className="text-muted-foreground" data-testid="records-media-page">
            {t(keys.records.media.page_info, {
              page,
              pages,
            })}
          </span>
          <Button
            type="button"
            variant="outline"
            size="sm"
            disabled={page >= pages}
            onClick={() => setPage(page + 1)}
          >
            {t(keys.records.media.next)}
          </Button>
        </nav>
      )}
    </>
  );
}

/**
 * Choose a file from the media library, or upload one — the `media` field's
 * picker. Radix supplies the modal behaviour the field needs: focus moves
 * into the dialog and is trapped there, and Escape closes it. Picking a file
 * (click, Enter or Space on an item) and a finished upload both hand the file
 * to `onPick` and close.
 *
 * Focus goes back to `returnFocusId` on close. Radix returns it only to a
 * `Dialog.Trigger`, and this dialog is opened by the field's own button
 * rather than a trigger — without this, closing it dropped focus on the page
 * body and a keyboard user started again from the top of the form.
 */
export function MediaPickerDialog({
  api,
  open,
  currentId,
  returnFocusId,
  onOpenChange,
  onPick,
}: {
  api: MediaApi;
  open: boolean;
  currentId: string | null;
  returnFocusId?: string;
  onOpenChange: (open: boolean) => void;
  onPick: (file: MediaFile) => void;
}) {
  const { t } = useT();
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        showCloseButton={false}
        className="flex max-h-[90dvh] flex-col gap-3 p-4 sm:max-w-3xl sm:p-6"
        data-testid="records-media-dialog"
        onCloseAutoFocus={(event) => {
          const target = returnFocusId ? document.getElementById(returnFocusId) : null;
          if (!target) return;
          event.preventDefault();
          target.focus();
        }}
      >
        <DialogHeader>
          <DialogTitle>{t(keys.records.media.dialog_title)}</DialogTitle>
          <DialogDescription>{t(keys.records.media.dialog_description)}</DialogDescription>
        </DialogHeader>
        {open && (
          <PickerBody
            api={api}
            currentId={currentId}
            onPick={(file) => {
              onPick(file);
              onOpenChange(false);
            }}
          />
        )}
        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
            {t(keys.records.media.cancel)}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
