import { router, usePage } from '@inertiajs/react';
import { PageShell } from '@simple-module-py/ui/components/PageShell';
import { AuthenticatedLayout } from '@simple-module-py/ui/layouts/AuthenticatedLayout';
import type React from 'react';
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
  deleteMedia,
  listMedia,
  type MediaAssetRead,
  type MediaListResponse,
  uploadMedia,
} from '../utils/api';
import { parseKB } from '../utils/mediaFormat';

interface Props {
  initial: MediaListResponse;
}

const PAGE_LIMIT = 60;

export default function MediaLibrary() {
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
        setMessage(e instanceof Error ? e.message : 'Failed to load media');
      } finally {
        if (isAppend) setLoadingMore(false);
        else setLoading(false);
      }
    },
    [filters.contentType, filters.folder, filters.maxKB, filters.minKB, query],
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

  const handleDelete = async (id: number) => {
    if (!confirm('Delete this asset? Pages using its URL will break.')) return;
    try {
      await deleteMedia(id);
      setAssets((prev) => prev.filter((a) => a.id !== id));
    } catch (e) {
      setMessage(e instanceof Error ? e.message : 'Delete failed');
    }
  };

  const handleCopy = async (asset: MediaAssetRead) => {
    try {
      await navigator.clipboard.writeText(asset.url);
      setCopied(asset.id);
      setTimeout(() => setCopied((c) => (c === asset.id ? null : c)), 1500);
    } catch {
      setMessage('Copy failed — select the URL manually.');
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
    if (filters.folder === null) return 'All assets';
    if (filters.folder === '') return 'Unfiled';
    return filters.folder;
  })();

  return (
    <PageShell
      title="Media library"
      description="Images available to every page."
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

          <div className="text-sm text-gray-500 mb-2">
            Browsing <strong>{activeFolderLabel}</strong>
            {loading && <span className="ml-2">Loading…</span>}
          </div>

          {message && (
            <div className="mb-4 text-sm text-gray-700 bg-yellow-50 border border-yellow-200 px-3 py-2 rounded">
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
              <button
                type="button"
                disabled={loadingMore}
                onClick={() => void refresh('append', nextCursor)}
                className="px-4 py-2 rounded border hover:bg-gray-50 text-sm disabled:opacity-50"
              >
                {loadingMore ? 'Loading…' : 'Load more'}
              </button>
            </div>
          )}
        </section>
      </div>
    </PageShell>
  );
}

MediaLibrary.layout = (page: React.ReactNode) => <AuthenticatedLayout>{page}</AuthenticatedLayout>;
