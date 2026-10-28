import { Head } from '@inertiajs/react';
import { PageShell } from '@simple-module-py/ui/components/PageShell';
import { Button } from '@simple-module-py/ui/components/ui/button';

import { ChipGroup } from '../components/ChipGroup';
import { CollectionCard } from '../components/collections/CollectionCard';
import { CreateCollectionDialog } from '../components/collections/CreateCollectionDialog';
import { ImagesLayout } from '../components/ImagesLayout';
import { useCollections } from '../hooks/useCollections';
import { keys, useT } from '../utils/i18n';
import { COLLECTION_FILTERS, collectionFilterLabel } from '../utils/labels';
import type { Collection, Page } from '../utils/types';

type Props = {
  collections: Page<Collection>;
  can_create: boolean;
  can_publish: boolean;
};

/** `Images/Collections` - `/admin/images/`. The first page comes from the
 *  server; filters and further pages from the API. */
function Collections({ collections, can_create, can_publish }: Props) {
  const { t } = useT();
  const list = useCollections(collections);

  return (
    <>
      <Head title={t(keys.images.collections.page_title)} />
      <PageShell
        title={t(keys.images.collections.page_title)}
        description={t(keys.images.collections.page_subtitle)}
        actions={can_create ? <CreateCollectionDialog canPublish={can_publish} /> : undefined}
      >
        <div className="space-y-4">
          <ChipGroup
            testId="images-collection-filter"
            label={t(keys.images.collections.filter_label)}
            value={list.filter}
            onChange={list.setFilter}
            options={COLLECTION_FILTERS.map((value) => ({
              value,
              label: collectionFilterLabel(t, value),
            }))}
          />
          {list.error && (
            <p className="text-sm text-destructive" role="alert">
              {list.error}
            </p>
          )}
          {list.items.length === 0 && !list.loading ? (
            <div className="rounded-lg border border-dashed p-8 text-center text-muted-foreground">
              {list.filter === 'all'
                ? t(keys.images.collections.empty)
                : t(keys.images.collections.empty_filtered)}
            </div>
          ) : (
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {list.items.map((collection) => (
                <CollectionCard key={collection.id} collection={collection} />
              ))}
            </div>
          )}
          {list.hasMore && (
            <Button type="button" variant="outline" disabled={list.loading} onClick={list.loadMore}>
              {t(keys.images.collections.load_more)}
            </Button>
          )}
        </div>
      </PageShell>
    </>
  );
}

Collections.layout = [ImagesLayout];
export default Collections;
