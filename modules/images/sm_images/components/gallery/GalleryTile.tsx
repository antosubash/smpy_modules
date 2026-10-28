import { Link } from '@inertiajs/react';
import { useState } from 'react';

import { keys, useT } from '../../utils/i18n';
import type { ImageItem } from '../../utils/types';

/** One thumbnail: the server's versioned `small` rendition, or a placeholder
 *  while the pipeline has not made one (or the route refuses it). */
export function GalleryTile({ image }: { image: ImageItem }) {
  const { t } = useT();
  const [broken, setBroken] = useState(false);
  const showImage = image.thumb_url !== null && !broken;

  return (
    <Link
      href={`/admin/images/images/${image.id}`}
      className="group relative block aspect-square overflow-hidden rounded-md border bg-muted"
      aria-label={t(keys.images.gallery.open, { name: image.filename })}
      data-testid="images-gallery-tile"
      data-image-id={image.id}
    >
      {showImage ? (
        <img
          src={image.thumb_url ?? undefined}
          alt={image.filename}
          loading="lazy"
          className="size-full object-cover transition-transform group-hover:scale-105"
          onError={() => setBroken(true)}
        />
      ) : (
        <span className="flex size-full items-center justify-center p-2 text-center text-xs text-muted-foreground">
          {t(keys.images.gallery.thumb_pending)}
        </span>
      )}
    </Link>
  );
}
