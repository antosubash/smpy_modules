import { router, usePage } from '@inertiajs/react';
import { PageShell } from '@simple-module-py/ui/components/PageShell';
import { Button } from '@simple-module-py/ui/components/ui/button';
import { AuthenticatedLayout } from '@simple-module-py/ui/layouts/AuthenticatedLayout';
import {
  type ChangeEvent,
  type DragEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react';

import { MediaFilters } from '../components/media/MediaFilters';
import { MediaFolderSidebar } from '../components/media/MediaFolderSidebar';
import { MediaGrid } from '../components/media/MediaGrid';
import { MediaHeader } from '../components/media/MediaHeader';
import { MediaDropzone, MediaUploadQueue } from '../components/media/MediaUploadQueue';
import type { ListFilters } from '../components/media/types';
import { useMediaUploads } from '../hooks/useMediaUploads';
import {
  deleteAssetIfUnused,
  listMedia,
  type MediaAssetRead,
  type MediaListResponse,
  uploadMedia,
} from '../utils/api';
import { keys, useT } from '../utils/i18n';
import { parseKB } from '../utils/mediaFormat';

interface Props {
  initial: MediaListResponse;
}

const PAGE_LIMIT = 60;

export default function MediaLibrary() {
  const { t } = useT();
  const { initial } = usePage<{ props: Props }>().props as unknown as Props;

  const [assets, setAssets] = useState<MediaAssetRead[]>(initial.items);
  const [nextCursor, setNextCursor] = useState<number | null>(initial.next_cursor);
  const [folders, setFolders] = useState<string[]>(initial.folders);
  const [loading, setLoading] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [copied, setCopied] = useState<number | null>(null);
  const [filters, setFilters] = useState<ListFilters>({
    search: '',
    contentType: '',
    folder: null,
    minKB: '',
    maxKB: '',
  });
  const [uploadFolder, setUploadFolder] = useState<string>('');
  const [dragActive, setDragActive] = useState(false);

  const fileInputRef = useRef<HTMLInputElement | null>(null);

  // Debounced search: state holds what the user is typing, `query`
  // holds what we actually send to the server.
  const [query, setQuery] = useState<string>('');
  useEffect(() => {
    const t = window.setTimeout(() => setQuery(filters.search.trim()), 250);
    return () => window.clearTimeout(t);
  }, [filters.search]);

  const refresh = useCallback(
    async (mode: 'replace' | 'append' = 'replace', cursor?: number | null) => {
      const isAppend = mode === 'append';
      if (isAppend) {
        setLoadingMore(true);
      } else {
        setLoading(true);
      }
      try {
        const response = await listMedia({
          search: query || undefined,
          content_type: filters.contentType || undefined,
          folder: filters.folder === null ? undefined : filters.folder,
          min_size_bytes: parseKB(filters.minKB),
          max_size_bytes: parseKB(filters.maxKB),
          cursor: cursor ?? undefined,
          limit: PAGE_LIMIT,
        });
        setAssets((prev) => (isAppend ? [...prev, ...response.items] : response.items));
        setNextCursor(response.next_cursor);
        setFolders(response.folders);
      } catch (e) {
        setMessage(e instanceof Error ? e.message : t(keys.pagebuilder.media.load_failed));
      } finally {
        if (isAppend) setLoadingMore(false);
        else setLoading(false);
      }
    },
    [filters.contentType, filters.folder, filters.maxKB, filters.minKB, query, t],
  );

  // Reload from the server whenever a filter or the debounced query
  // changes. We deliberately skip the initial mount (the server already
  // gave us page 1 in props) to avoid a flash of duplicate work.
  const didMountRef = useRef(false);
  useEffect(() => {
    if (!didMountRef.current) {
      didMountRef.current = true;
      return;
    }
    void refresh('replace');
  }, [refresh]);

  const folderOptions = useMemo(() => {
    const set = new Set(folders);
    if (uploadFolder.trim()) set.add(uploadFolder.trim());
    return Array.from(set).sort();
  }, [folders, uploadFolder]);

  // The *checked* delete, the same one the asset detail screen uses. The
  // library was calling the unchecked endpoint, which meant the whole
  // "refuses while in use" guarantee could be sidestepped by deleting from
  // here instead of from the detail page.
  //
  // Errors propagate: the confirmation dialog stays open and shows them,
  // which is closer to the failure than the banner at the top of the page —
  // and it is how the 409 naming the dependent pages reaches the person.
  const handleDelete = async (id: number) => {
    await deleteAssetIfUnused(id);
    setAssets((prev) => prev.filter((a) => a.id !== id));
  };

  const handleCopy = async (asset: MediaAssetRead) => {
    try {
      await navigator.clipboard.writeText(asset.url);
      setCopied(asset.id);
      setTimeout(() => setCopied((c) => (c === asset.id ? null : c)), 1500);
    } catch {
      setMessage(t(keys.pagebuilder.media.copy_failed));
    }
  };

  // Splice a freshly uploaded asset into the visible list when it matches the
  // active filter; otherwise it appears when the user switches to that folder.
  const handleUploaded = useCallback(
    (asset: MediaAssetRead) => {
      const matchesActiveFolder =
        filters.folder === null ||
        (filters.folder === '' && !asset.folder) ||
        filters.folder === asset.folder;
      if (matchesActiveFolder) {
        setAssets((prev) => [asset, ...prev]);
      }
      if (asset.folder) {
        setFolders((prev) =>
          prev.includes(asset.folder as string)
            ? prev
            : Array.from(new Set([...prev, asset.folder as string])).sort(),
        );
      }
    },
    [filters.folder],
  );

  const { uploads, startUploads, dismissUpload } = useMediaUploads({
    uploadFolder,
    onUploaded: handleUploaded,
    setMessage,
  });

  const onFileInputChange = (e: ChangeEvent<HTMLInputElement>) => {
    const list = e.target.files ? Array.from(e.target.files) : [];
    if (fileInputRef.current) fileInputRef.current.value = '';
    startUploads(list);
  };

  const onDrop = (e: DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setDragActive(false);
    const files = e.dataTransfer.files ? Array.from(e.dataTransfer.files) : [];
    startUploads(files);
  };

  const activeFolderLabel = (() => {
    if (filters.folder === null) return t(keys.pagebuilder.media.all_assets);
    if (filters.folder === '') return t(keys.pagebuilder.media.unfiled);
    return filters.folder;
  })();

  return (
    <PageShell
      title={t(keys.pagebuilder.media.title)}
      description={t(keys.pagebuilder.media.description)}
      maxWidth="full"
      actions={<MediaHeader fileInputRef={fileInputRef} onFilesSelected={onFileInputChange} />}
    >
      <div className="grid grid-cols-1 md:grid-cols-[220px_1fr] gap-6">
        <MediaFolderSidebar
          folders={folders}
          folderOptions={folderOptions}
          activeFolder={filters.folder}
          onSelectFolder={(folder) => setFilters((f) => ({ ...f, folder }))}
          uploadFolder={uploadFolder}
          onUploadFolderChange={setUploadFolder}
        />

        <section>
          <MediaFilters filters={filters} onChange={setFilters} />

          <div className="mb-2 text-sm text-muted-foreground">
            {t(keys.pagebuilder.media.browsing)} <strong>{activeFolderLabel}</strong>
            {loading && <span className="ml-2">{t(keys.pagebuilder.media.loading)}</span>}
          </div>

          {message && (
            <div className="mb-4 rounded border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive">
              {message}
            </div>
          )}

          <MediaDropzone
            uploadFolder={uploadFolder}
            dragActive={dragActive}
            onDragActiveChange={setDragActive}
            onDrop={onDrop}
          />

          <MediaUploadQueue uploads={uploads} onDismiss={dismissUpload} />

          <MediaGrid
            assets={assets}
            loading={loading}
            copiedId={copied}
            onCopy={handleCopy}
            onDelete={handleDelete}
          />

          {nextCursor !== null && (
            <div className="mt-6 flex justify-center">
              <Button
                type="button"
                variant="outline"
                disabled={loadingMore}
                onClick={() => void refresh('append', nextCursor)}
              >
                {loadingMore
                  ? t(keys.pagebuilder.media.loading)
                  : t(keys.pagebuilder.media.load_more)}
              </Button>
            </div>
          )}
        </section>
      </div>
    </PageShell>
  );
}

MediaLibrary.layout = [AuthenticatedLayout];
