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

import {
  deleteMedia,
  listMedia,
  type MediaAssetRead,
  type MediaListResponse,
  uploadMedia,
} from '../utils/api';

interface Props {
  initial: MediaListResponse;
}

interface ListFilters {
  search: string;
  contentType: string;
  folder: string | null; // null = Any; "" = Unfiled; "x" = exact folder.
  minKB: string;
  maxKB: string;
}

type UploadStatus = 'pending' | 'uploading' | 'done' | 'error';

interface UploadItem {
  id: string;
  file: File;
  status: UploadStatus;
  loaded: number;
  total: number;
  error: string | null;
}

const PAGE_LIMIT = 60;

const CONTENT_TYPE_OPTIONS: { label: string; value: string }[] = [
  { label: 'Any type', value: '' },
  { label: 'JPEG', value: 'image/jpeg' },
  { label: 'PNG', value: 'image/png' },
  { label: 'GIF', value: 'image/gif' },
  { label: 'WebP', value: 'image/webp' },
];

function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(2)} MB`;
}

function parseKB(raw: string): number | undefined {
  const trimmed = raw.trim();
  if (!trimmed) return undefined;
  const n = Number(trimmed);
  if (!Number.isFinite(n) || n < 0) return undefined;
  return Math.round(n * 1024);
}

function uploadKey(file: File): string {
  return `${file.name}:${file.size}:${file.lastModified}:${Math.random().toString(36).slice(2, 8)}`;
}

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
      <div className="flex items-center justify-between mb-6 flex-wrap gap-3">
        <h1 className="text-3xl font-bold">Media library</h1>
        <div className="flex gap-2">
          <button
            type="button"
            onClick={() => router.visit('/pagebuilder')}
            className="px-4 py-2 rounded border hover:bg-gray-50 font-medium"
          >
            ← Pages
          </button>
          <label className="px-4 py-2 rounded font-medium cursor-pointer text-white bg-blue-600 hover:bg-blue-700">
            Upload
            <input
              ref={fileInputRef}
              type="file"
              accept="image/*"
              multiple
              className="hidden"
              onChange={onFileInputChange}
            />
          </label>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-[220px_1fr] gap-6">
        <aside className="space-y-4">
          <div>
            <h2 className="text-sm font-semibold text-gray-600 mb-2 uppercase tracking-wide">
              Folders
            </h2>
            <ul className="space-y-1 text-sm">
              <FolderItem
                label="All assets"
                active={filters.folder === null}
                onClick={() => setFilters((f) => ({ ...f, folder: null }))}
              />
              <FolderItem
                label="Unfiled"
                active={filters.folder === ''}
                onClick={() => setFilters((f) => ({ ...f, folder: '' }))}
              />
              {folders.map((name) => (
                <FolderItem
                  key={name}
                  label={name}
                  active={filters.folder === name}
                  onClick={() => setFilters((f) => ({ ...f, folder: name }))}
                />
              ))}
            </ul>
          </div>
          <div>
            <label className="block text-sm font-semibold text-gray-600 mb-1">
              Upload to folder
            </label>
            <input
              type="text"
              value={uploadFolder}
              onChange={(e) => setUploadFolder(e.target.value)}
              list="pagebuilder-folder-suggestions"
              placeholder="e.g. marketing/heros"
              className="w-full px-2 py-1.5 border rounded text-sm"
            />
            <datalist id="pagebuilder-folder-suggestions">
              {folderOptions.map((name) => (
                <option key={name} value={name} />
              ))}
            </datalist>
            <p className="text-xs text-gray-500 mt-1">Leave blank to upload into Unfiled.</p>
          </div>
        </aside>

        <section>
          <div className="flex flex-wrap gap-3 items-end mb-4">
            <div className="flex-1 min-w-[200px]">
              <label className="block text-xs text-gray-500 mb-1">Search</label>
              <input
                type="search"
                value={filters.search}
                onChange={(e) => setFilters((f) => ({ ...f, search: e.target.value }))}
                placeholder="Filename contains…"
                className="w-full px-3 py-2 border rounded text-sm"
              />
            </div>
            <div>
              <label className="block text-xs text-gray-500 mb-1">Type</label>
              <select
                value={filters.contentType}
                onChange={(e) => setFilters((f) => ({ ...f, contentType: e.target.value }))}
                className="px-2 py-2 border rounded text-sm"
              >
                {CONTENT_TYPE_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label className="block text-xs text-gray-500 mb-1">Min KB</label>
              <input
                type="number"
                inputMode="numeric"
                min={0}
                value={filters.minKB}
                onChange={(e) => setFilters((f) => ({ ...f, minKB: e.target.value }))}
                className="w-24 px-2 py-2 border rounded text-sm"
              />
            </div>
            <div>
              <label className="block text-xs text-gray-500 mb-1">Max KB</label>
              <input
                type="number"
                inputMode="numeric"
                min={0}
                value={filters.maxKB}
                onChange={(e) => setFilters((f) => ({ ...f, maxKB: e.target.value }))}
                className="w-24 px-2 py-2 border rounded text-sm"
              />
            </div>
          </div>

          <div className="text-sm text-gray-500 mb-2">
            Browsing <strong>{activeFolderLabel}</strong>
            {loading && <span className="ml-2">Loading…</span>}
          </div>

          {message && (
            <div className="mb-4 text-sm text-gray-700 bg-yellow-50 border border-yellow-200 px-3 py-2 rounded">
              {message}
            </div>
          )}

          <div
            onDragOver={(e) => {
              e.preventDefault();
              setDragActive(true);
            }}
            onDragLeave={(e) => {
              e.preventDefault();
              setDragActive(false);
            }}
            onDrop={onDrop}
            className={`mb-4 border-2 border-dashed rounded-lg p-6 text-center text-sm transition-colors ${
              dragActive
                ? 'border-blue-500 bg-blue-50 text-blue-700'
                : 'border-gray-300 text-gray-500'
            }`}
            data-testid="media-dropzone"
          >
            Drop image files here to upload to <strong>{uploadFolder.trim() || 'Unfiled'}</strong>.
            Multiple files are accepted.
          </div>

          {uploads.length > 0 && (
            <div className="mb-4 space-y-1" data-testid="upload-list">
              {uploads.map((u) => (
                <div
                  key={u.id}
                  className="border rounded p-2 text-xs flex items-center gap-3"
                  data-testid="upload-row"
                >
                  <div className="flex-1 min-w-0">
                    <div className="font-medium truncate" title={u.file.name}>
                      {u.file.name}
                    </div>
                    <div className="h-1.5 bg-gray-100 rounded overflow-hidden mt-1">
                      <div
                        className={`h-full transition-all ${
                          u.status === 'error'
                            ? 'bg-red-500'
                            : u.status === 'done'
                              ? 'bg-green-500'
                              : 'bg-blue-500'
                        }`}
                        style={{
                          width: u.total
                            ? `${Math.min(100, Math.round((u.loaded / u.total) * 100))}%`
                            : '0%',
                        }}
                      />
                    </div>
                    {u.error && <div className="text-red-600 mt-1">{u.error}</div>}
                  </div>
                  <div className="w-16 text-right tabular-nums text-gray-500">
                    {u.status === 'done'
                      ? 'Done'
                      : u.status === 'error'
                        ? 'Failed'
                        : `${Math.round((u.loaded / Math.max(1, u.total)) * 100)}%`}
                  </div>
                  {(u.status === 'done' || u.status === 'error') && (
                    <button
                      type="button"
                      onClick={() => dismissUpload(u.id)}
                      className="text-gray-400 hover:text-gray-700"
                      aria-label="Dismiss"
                    >
                      ×
                    </button>
                  )}
                </div>
              ))}
            </div>
          )}

          {assets.length === 0 && !loading ? (
            <div className="text-gray-500 border border-dashed rounded p-8 text-center">
              No assets match the current filter.
            </div>
          ) : (
            <ul className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
              {assets.map((a) => (
                <li key={a.id} className="border rounded overflow-hidden bg-white">
                  <div className="aspect-square bg-gray-100 flex items-center justify-center overflow-hidden">
                    {a.content_type.startsWith('image/') ? (
                      <img
                        src={a.url}
                        alt={a.original_filename}
                        className="max-h-full max-w-full object-contain"
                      />
                    ) : (
                      <span className="text-xs text-gray-500">{a.content_type}</span>
                    )}
                  </div>
                  <div className="p-2 text-xs space-y-1">
                    <div className="font-medium truncate" title={a.original_filename}>
                      {a.original_filename}
                    </div>
                    <div className="text-gray-500">
                      {formatBytes(a.size_bytes)}
                      {a.width && a.height ? ` · ${a.width}×${a.height}` : ''}
                    </div>
                    {a.folder && (
                      <div className="text-gray-400 truncate" title={a.folder}>
                        {a.folder}
                      </div>
                    )}
                    <div className="flex gap-2 pt-1 flex-wrap">
                      <button
                        type="button"
                        onClick={() => handleCopy(a)}
                        className="text-blue-600 hover:underline"
                        title="Useful for the SEO og_image field or external use"
                      >
                        {copied === a.id ? 'Copied!' : 'Copy URL'}
                      </button>
                      <button
                        type="button"
                        onClick={() => handleDelete(a.id)}
                        className="text-red-600 hover:underline ml-auto"
                      >
                        Delete
                      </button>
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          )}

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

function FolderItem({
  label,
  active,
  onClick,
}: {
  label: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <li>
      <button
        type="button"
        onClick={onClick}
        className={`w-full text-left px-2 py-1 rounded truncate ${
          active ? 'bg-blue-100 text-blue-900 font-medium' : 'hover:bg-gray-100 text-gray-700'
        }`}
        title={label}
      >
        {label}
      </button>
    </li>
  );
}
