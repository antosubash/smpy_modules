/** Thumbnail grid of media assets with copy-URL and delete actions. */

import { Button } from '@simple-module-py/ui/components/ui/button';

import type { MediaAssetRead } from '../../utils/api';
import { formatBytes } from '../../utils/mediaFormat';
import { ConfirmDialog } from '../ConfirmDialog';

interface Props {
  assets: MediaAssetRead[];
  loading: boolean;
  copiedId: number | null;
  onCopy: (asset: MediaAssetRead) => void;
  /** Rejecting surfaces the message inside the confirmation dialog. */
  onDelete: (id: number) => Promise<unknown>;
}

export function MediaGrid({ assets, loading, copiedId, onCopy, onDelete }: Props) {
  if (assets.length === 0 && !loading) {
    return (
      <div className="rounded-lg border border-dashed p-8 text-center text-muted-foreground">
        No assets match the current filter.
      </div>
    );
  }
  return (
    <ul className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 gap-4">
      {assets.map((a) => (
        <li key={a.id} className="overflow-hidden rounded-lg border bg-card shadow-xs">
          <div className="flex aspect-square items-center justify-center overflow-hidden bg-muted">
            {a.content_type.startsWith('image/') ? (
              <img
                src={a.url}
                alt={a.original_filename}
                className="max-h-full max-w-full object-contain"
              />
            ) : (
              <span className="text-xs text-muted-foreground">{a.content_type}</span>
            )}
          </div>
          <div className="p-2 text-xs space-y-1">
            <div className="font-medium truncate" title={a.original_filename}>
              {a.original_filename}
            </div>
            <div className="text-muted-foreground">
              {formatBytes(a.size_bytes)}
              {a.width && a.height ? ` · ${a.width}×${a.height}` : ''}
            </div>
            {a.folder && (
              <div className="truncate text-muted-foreground" title={a.folder}>
                {a.folder}
              </div>
            )}
            <div className="flex gap-2 pt-1 flex-wrap">
              <Button
                variant="link"
                size="sm"
                className="h-auto p-0"
                onClick={() => onCopy(a)}
                title="Useful for the SEO og_image field or external use"
              >
                {copiedId === a.id ? 'Copied!' : 'Copy URL'}
              </Button>
              <ConfirmDialog
                trigger={
                  <Button variant="link" size="sm" className="ml-auto h-auto p-0 text-destructive">
                    Delete
                  </Button>
                }
                title={`Delete ${a.original_filename}?`}
                description="Any page still pointing at this URL will show a broken image. The library cannot tell you which pages those are, so check before deleting."
                confirmLabel="Delete"
                destructive
                onConfirm={() => onDelete(a.id)}
              />
            </div>
          </div>
        </li>
      ))}
    </ul>
  );
}
