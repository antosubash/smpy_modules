import { Link } from '@inertiajs/react';
import { useState } from 'react';

import { keys, useT } from '../../utils/i18n';
import type { ImageItem } from '../../utils/types';

/** A member's thumbnail with its role under it. */
export function MemberThumb({ image }: { image: ImageItem }) {
  const { t } = useT();
  const [broken, setBroken] = useState(false);
  const show = image.thumb_url !== null && !broken;

  return (
    <li className="w-20" data-testid="images-group-member" data-role={image.group_role ?? ''}>
      <Link
        href={`/admin/images/images/${image.id}`}
        aria-label={t(keys.images.groups.open, { name: image.filename })}
        className="block aspect-square overflow-hidden rounded-md border bg-muted"
      >
        {show && (
          <img
            src={image.thumb_url ?? undefined}
            alt={image.filename}
            loading="lazy"
            className="size-full object-cover"
            onError={() => setBroken(true)}
          />
        )}
      </Link>
      <p className="truncate text-center text-xs text-muted-foreground">
        {image.group_role ?? t(keys.images.groups.no_role)}
      </p>
    </li>
  );
}
