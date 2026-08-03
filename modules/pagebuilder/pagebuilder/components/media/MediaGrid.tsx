/** Thumbnail grid of media assets with copy-URL and delete actions. */

import type { MediaAssetRead } from '../../utils/api';
import { formatBytes } from '../../utils/mediaFormat';

interface Props {
  assets: MediaAssetRead[];
  loading: boolean;
  copiedId: number | null;
  onCopy: (asset: MediaAssetRead) => void;
  onDelete: (id: number) => void;
}

export function MediaGrid({ assets, loading, copiedId, onCopy, onDelete }: Props) {
  if (assets.length === 0 && !loading) {
    return (
      <div className="text-gray-500 border border-dashed rounded p-8 text-center">
        No assets match the current filter.
      </div>
    );
  }
  return (
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
                onClick={() => onCopy(a)}
                className="text-blue-600 hover:underline"
                title="Useful for the SEO og_image field or external use"
              >
                {copiedId === a.id ? 'Copied!' : 'Copy URL'}
              </button>
              <button
                type="button"
                onClick={() => onDelete(a.id)}
                className="text-red-600 hover:underline ml-auto"
              >
                Delete
              </button>
            </div>
          </div>
        </li>
      ))}
    </ul>
  );
}
