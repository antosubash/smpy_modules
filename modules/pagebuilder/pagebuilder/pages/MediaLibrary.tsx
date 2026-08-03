import { router, usePage } from '@inertiajs/react';
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
import type { ListFilters, UploadItem } from '../components/media/types';
import {
  deleteMedia,
  listMedia,
  type MediaAssetRead,
  type MediaListResponse,
  uploadMedia,
} from '../utils/api';
import { parseKB, uploadKey } from '../utils/mediaFormat';

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
  const [uploads, setUploads] = useState<UploadItem[]>([]);
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
            // Splice the new asset into the visible list when it matches
            // the active filter (matches "any folder" or the same folder
            // the user is browsing). Otherwise the user will see it as
            // soon as they switch back to that folder.
            const matchesActiveFolder =
              filters.folder === null ||
              (filters.folder === '' && !asset.folder) ||
              filters.folder === asset.folder;
            if (matchesActiveFolder) {
              setAssets((prev) => [asset, ...prev]);
            }
            if (asset.folder && !folders.includes(asset.folder)) {
              setFolders((prev) => Array.from(new Set([...prev, asset.folder!])).sort());
            }
            succeeded += 1;
          } catch (e) {
            setUploads((prev) =>
              prev.map((u) =>
                u.id === item.id
                  ? {
                      ...u,
                      status: 'error',
                      error: e instanceof Error ? e.message : 'Upload failed',
                    }
                  : u,
              ),
            );
          }
        }
        if (succeeded > 0) {
          setMessage(`Uploaded ${succeeded} file${succeeded === 1 ? '' : 's'}.`);
          // Best-effort: also re-sync via Inertia so the SSR props
          // reflect the new state on next reload.
          router.reload({ only: ['initial'] });
        }
      })();
    },
    [filters.folder, folders, uploadFolder],
  );

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

  const dismissUpload = (id: string) => {
    setUploads((prev) => prev.filter((u) => u.id !== id));
  };

  const activeFolderLabel = (() => {
    if (filters.folder === null) return 'All assets';
    if (filters.folder === '') return 'Unfiled';
    return filters.folder;
  })();

  return (
    <div className="max-w-7xl mx-auto p-8">
      <MediaHeader fileInputRef={fileInputRef} onFilesSelected={onFileInputChange} />

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
    </div>
  );
}
