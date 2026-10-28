import { Link } from '@inertiajs/react';
import { Badge } from '@simple-module-py/ui/components/ui/badge';

import { keys, useT } from '../../utils/i18n';
import { visibilityLabel } from '../../utils/labels';
import type { Collection } from '../../utils/types';

export function CollectionCard({ collection }: { collection: Collection }) {
  const { t } = useT();
  return (
    <Link
      href={`/admin/images/${collection.id}`}
      className="block rounded-lg border p-4 transition-colors hover:bg-accent/50"
      data-testid="images-collection-card"
      data-collection-id={collection.id}
    >
      <div className="flex items-start justify-between gap-2">
        <h2 className="font-medium break-words">{collection.name}</h2>
        <Badge variant="secondary">{visibilityLabel(t, collection.visibility)}</Badge>
      </div>
      {collection.description && (
        <p className="mt-1 line-clamp-2 text-sm text-muted-foreground">{collection.description}</p>
      )}
      <p className="mt-3 text-sm text-muted-foreground">
        {t(keys.images.collections.image_count, { count: collection.image_count })}
        {collection.is_owner ? ` · ${t(keys.images.collections.owner)}` : ''}
      </p>
    </Link>
  );
}
