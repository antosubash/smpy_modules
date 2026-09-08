/** Thumbnail grid of media assets with copy-URL and delete actions. */

import { Button } from '@simple-module-py/ui/components/ui/button';

import type { MediaAssetRead } from '../../utils/api';
import { keys, useT } from '../../utils/i18n';
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
  const { t } = useT();
  if (assets.length === 0 && !loading) {
    return (
      <div className="rounded-lg border border-dashed p-8 text-center text-muted-foreground">
        {t(keys.pagebuilder.grid.empty)}
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
              {/* The detail screen is where alt text, credit and the list of
                  pages depending on this asset live. */}
              <Button variant="link" size="sm" className="h-auto p-0" asChild>
                <a href={`/pagebuilder/media/${a.id}`} data-testid="media-details-link">
                  {t(keys.pagebuilder.grid.details)}
                </a>
              </Button>
              <Button
                variant="link"
                size="sm"
                className="h-auto p-0"
                onClick={() => onCopy(a)}
                title={t(keys.pagebuilder.grid.copy_hint)}
              >
                {copiedId === a.id
                  ? t(keys.pagebuilder.grid.copied)
                  : t(keys.pagebuilder.grid.copy)}
              </Button>
              <ConfirmDialog
                trigger={
                  <Button variant="link" size="sm" className="ml-auto h-auto p-0 text-destructive">
                    {t(keys.pagebuilder.grid.delete)}
                  </Button>
                }
                title={t(keys.pagebuilder.grid.delete_title, { name: a.original_filename })}
                description={t(keys.pagebuilder.grid.delete_description)}
                confirmLabel={t(keys.pagebuilder.grid.delete)}
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
