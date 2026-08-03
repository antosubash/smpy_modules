/**
 * Custom Puck field that opens a modal grid of uploaded media assets.
 * Selecting an asset emits its URL via `onChange` and stashes the full
 * `MediaAssetRead` in the picked-asset cache so the Image block's
 * `resolveData` can back-fill sibling props without a second fetch.
 * A manually typed URL is also accepted; `resolveData` then falls back
 * to a fresh list lookup.
 */

import { useEffect, useState } from 'react';

import { listMedia, type MediaAssetRead, rememberPickedAsset } from '../../utils/api';

interface MediaPickerProps {
  value: string;
  onChange: (value: string) => void;
  readOnly?: boolean;
}

export function MediaPicker({ value, onChange, readOnly }: MediaPickerProps) {
  const [open, setOpen] = useState(false);

  return (
    <div className="space-y-2">
      <input
        type="text"
        value={value || ''}
        onChange={(e) => onChange(e.target.value)}
        readOnly={readOnly}
        placeholder="Pick from library or paste a URL"
        className="w-full px-2 py-1.5 border rounded text-sm"
      />
      <div className="flex gap-2">
        <button
          type="button"
          disabled={readOnly}
          onClick={() => setOpen(true)}
          className="px-3 py-1.5 text-sm rounded bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50"
        >
          Browse media…
        </button>
        {value && (
          <button
            type="button"
            disabled={readOnly}
            onClick={() => onChange('')}
            className="px-3 py-1.5 text-sm rounded border hover:bg-gray-50 disabled:opacity-50"
          >
            Clear
          </button>
        )}
      </div>
      {value && (
        <img src={value} alt="" className="max-h-24 rounded border bg-gray-50 object-contain" />
      )}
      {open && (
        <MediaPickerModal
          onPick={(asset) => {
            rememberPickedAsset(asset);
            onChange(asset.url);
            setOpen(false);
          }}
          onClose={() => setOpen(false)}
        />
      )}
    </div>
  );
}

function MediaPickerModal({
  onPick,
  onClose,
}: {
  onPick: (asset: MediaAssetRead) => void;
  onClose: () => void;
}) {
  const [assets, setAssets] = useState<MediaAssetRead[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    listMedia()
      .then((r) => {
        if (!cancelled) setAssets(r.items);
      })
      .catch((e) => {
        if (!cancelled) setError(e instanceof Error ? e.message : 'Failed to load media');
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Close on Escape so keyboard-only users aren't trapped.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Media library picker"
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4"
      onClick={onClose}
    >
      <div
        className="bg-white rounded-lg shadow-xl w-full max-w-4xl max-h-[80vh] flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b p-4">
          <h2 className="text-lg font-semibold">Pick an image</h2>
          <button
            type="button"
            onClick={onClose}
            className="text-gray-500 hover:text-gray-800 text-xl leading-none"
            aria-label="Close picker"
          >
            ×
          </button>
        </div>
        <div className="flex-1 overflow-auto p-4">
          {error && <div className="text-red-600 text-sm">{error}</div>}
          {!error && assets === null && <div className="text-gray-500 text-sm">Loading…</div>}
          {assets && assets.length === 0 && (
            <div className="text-gray-500 text-sm">
              No uploads yet. Upload images from the Media library page.
            </div>
          )}
          {assets && assets.length > 0 && (
            <ul className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-3">
              {assets.map((a) => (
                <li key={a.id}>
                  <button
                    type="button"
                    onClick={() => onPick(a)}
                    className="w-full text-left border rounded overflow-hidden hover:ring-2 hover:ring-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500"
                  >
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
                    <div className="p-2 text-xs space-y-0.5">
                      <div className="font-medium truncate" title={a.original_filename}>
                        {a.original_filename}
                      </div>
                      <div className="text-gray-500">
                        {a.width && a.height ? `${a.width}×${a.height}` : '—'}
                      </div>
                    </div>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}
