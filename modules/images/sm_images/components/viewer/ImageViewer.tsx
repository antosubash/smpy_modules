import { Button } from '@simple-module-py/ui/components/ui/button';
import { useState } from 'react';

import { keys, useT } from '../../utils/i18n';
import type { ImageItem } from '../../utils/types';

/** The access-checked original. Never put in the DOM until asked for: a
 *  protected original is fetched only by someone who chose to look. */
export function originalUrl(image: ImageItem): string {
  return `/api/images/images/${image.id}/original`;
}

/**
 * The picture: the display copy, and - only when `canViewOriginal` - a toggle
 * that swaps in the original. The server decides `canViewOriginal` (the same
 * rule `/original` answers by); with it false there is no toggle, so a person
 * who cannot see the original is never offered a request that would be refused.
 */
export function ImageViewer({
  image,
  canViewOriginal,
}: {
  image: ImageItem;
  canViewOriginal: boolean;
}) {
  const { t } = useT();
  const [original, setOriginal] = useState(false);
  const [failed, setFailed] = useState(false);

  const src = original ? originalUrl(image) : (image.display_url ?? undefined);

  return (
    <figure className="space-y-3" data-testid="images-viewer">
      {failed ? (
        <p className="rounded-md border p-6 text-center text-sm text-destructive" role="alert">
          {t(keys.images.viewer.original_failed)}
        </p>
      ) : (
        <img
          key={src}
          src={src}
          alt={image.filename}
          className="mx-auto max-h-[75vh] max-w-full rounded-md border bg-muted object-contain"
          data-testid="images-viewer-image"
          data-source={original ? 'original' : 'display'}
          onError={() => original && setFailed(true)}
        />
      )}
      {canViewOriginal && (
        <div className="flex justify-center">
          <Button
            type="button"
            variant="outline"
            data-testid="images-original-toggle"
            aria-pressed={original}
            onClick={() => {
              setFailed(false);
              setOriginal((on) => !on);
            }}
          >
            {original ? t(keys.images.viewer.show_display) : t(keys.images.viewer.show_original)}
          </Button>
        </div>
      )}
    </figure>
  );
}
