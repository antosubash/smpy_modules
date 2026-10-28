import { Button } from '@simple-module-py/ui/components/ui/button';

import type { Gallery as GalleryState } from '../../hooks/useImages';
import { keys, useT } from '../../utils/i18n';
import { GALLERY_FILTERS, galleryFilterLabel } from '../../utils/labels';
import { ChipGroup } from '../ChipGroup';
import { GalleryTile } from './GalleryTile';

/** The cursor grid of `small` renditions with its filter chips. State lives in
 *  `useImages`; this only draws it. */
export function Gallery({ gallery }: { gallery: GalleryState }) {
  const { t } = useT();
  const { items, total, filter, loading, error } = gallery;

  return (
    <section className="space-y-4" aria-labelledby="images-gallery-title">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h2 id="images-gallery-title" className="text-lg font-semibold">
          {t(keys.images.gallery.title)}
          {total !== null && (
            <span className="ml-2 text-sm font-normal text-muted-foreground">
              {t(keys.images.gallery.total, { count: total })}
            </span>
          )}
        </h2>
        <ChipGroup
          testId="images-gallery-filter"
          label={t(keys.images.gallery.filter_label)}
          value={filter}
          onChange={gallery.setFilter}
          options={GALLERY_FILTERS.map((value) => ({
            value,
            label: galleryFilterLabel(t, value),
          }))}
        />
      </div>
      {error && (
        <p className="text-sm text-destructive" role="alert">
          {error}
        </p>
      )}
      {items.length === 0 && !loading ? (
        <div className="rounded-lg border border-dashed p-8 text-center text-muted-foreground">
          {filter === 'all' ? t(keys.images.gallery.empty) : t(keys.images.gallery.no_match)}
        </div>
      ) : (
        <div
          className="grid grid-cols-2 gap-3 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6"
          data-testid="images-gallery"
        >
          {items.map((image) => (
            <GalleryTile key={image.id} image={image} />
          ))}
        </div>
      )}
      {gallery.hasMore && (
        <Button
          type="button"
          variant="outline"
          disabled={loading}
          data-testid="images-gallery-more"
          onClick={gallery.loadMore}
        >
          {t(keys.images.gallery.load_more)}
        </Button>
      )}
    </section>
  );
}
