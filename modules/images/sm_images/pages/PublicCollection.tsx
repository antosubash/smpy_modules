import { Head } from '@inertiajs/react';
import { BrandingHead } from '@simple-module-py/ui/components/BrandingHead';
import { useState } from 'react';

import { CollectionMap } from '../components/map/CollectionMap';
import { PublicGallery } from '../components/public/PublicGallery';
import { publicMapUrl, publicPointsUrl } from '../utils/api-public';
import { keys, useT } from '../utils/i18n';
import type { PublicCollectionInfo } from '../utils/types-public';

/** `Images/PublicCollection` - `/images/c/{slug}`, for anyone.
 *
 *  A public collection's gallery and, when any image has a location, its map.
 *  No admin layout: this is a page of the site, not of the console. Everything
 *  it shows comes from the anonymous routes, which re-check on every request
 *  that the collection is still public. */
export default function PublicCollection({ collection }: { collection: PublicCollectionInfo }) {
  const { t } = useT();
  const [open, setOpen] = useState<string | null>(null);

  return (
    <>
      {/* A public page has no admin layout, so without this the configured
          site name and favicon would not apply. */}
      <BrandingHead />
      <Head title={collection.name} />
      <main className="mx-auto max-w-6xl space-y-8 px-4 py-8">
        <header className="space-y-2">
          <h1 className="text-3xl font-semibold">{collection.name}</h1>
          {collection.description && (
            <p className="text-muted-foreground">{collection.description}</p>
          )}
          <p className="text-sm text-muted-foreground">
            {t(keys.images.public.count, { count: collection.image_count })}
          </p>
        </header>
        <section aria-labelledby="images-public-gallery-title" className="space-y-3">
          <h2 id="images-public-gallery-title" className="text-xl font-semibold">
            {t(keys.images.public.gallery)}
          </h2>
          <PublicGallery
            slug={collection.slug}
            name={collection.name}
            openId={open}
            onClosed={() => setOpen(null)}
          />
        </section>
        {collection.located_count > 0 && (
          <section aria-labelledby="images-public-map-title" className="space-y-3">
            <h2 id="images-public-map-title" className="text-xl font-semibold">
              {t(keys.images.public.map)}
            </h2>
            <CollectionMap
              pointsUrl={publicPointsUrl(collection.slug)}
              mapUrl={publicMapUrl(collection.slug)}
              bbox={collection.bbox}
              onSelect={setOpen}
            />
          </section>
        )}
      </main>
    </>
  );
}
