import { Head, Link, router } from '@inertiajs/react';
import { PageShell } from '@simple-module-py/ui/components/PageShell';
import { Button } from '@simple-module-py/ui/components/ui/button';
import { Label } from '@simple-module-py/ui/components/ui/label';
import { useState } from 'react';
import { toast } from 'sonner';

import { ConfirmDialog } from '../components/ConfirmDialog';
import { VisibilitySelect } from '../components/collections/VisibilitySelect';
import { Gallery } from '../components/gallery/Gallery';
import { UploadButton } from '../components/gallery/UploadButton';
import { ImagesLayout } from '../components/ImagesLayout';
import { PipelineTab } from '../components/pipeline/PipelineTab';
import { ShareDialog } from '../components/share/ShareDialog';
import { useImages } from '../hooks/useImages';
import { deleteCollection, setVisibility } from '../utils/api';
import { keys, useT } from '../utils/i18n';
import type { Collection as CollectionRow, Visibility } from '../utils/types';

type Props = {
  collection: CollectionRow;
  can_edit: boolean;
  can_manage: boolean;
  can_share: boolean;
  can_publish: boolean;
  direct_upload_threshold: number;
};

/** `Images/Collection` - `/admin/images/{id}`. Tabs: the gallery and the
 *  pipeline; map, imports and review arrive with their own tasks. */
function Collection({
  collection,
  can_edit,
  can_manage,
  can_share,
  can_publish,
  direct_upload_threshold,
}: Props) {
  const { t } = useT();
  const gallery = useImages(collection.id);
  const [visibility, setVisible] = useState<Visibility>(collection.visibility);
  const [saving, setSaving] = useState(false);
  const [tab, setTab] = useState<'gallery' | 'pipeline'>('gallery');

  const changeVisibility = async (next: Visibility) => {
    setSaving(true);
    try {
      await setVisibility(collection.id, next);
      setVisible(next);
      toast(t(keys.images.visibility.changed));
    } catch (e) {
      toast.error(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  const remove = async () => {
    await deleteCollection(collection.id);
    toast(t(keys.images.collection.deleted));
    router.visit('/admin/images/');
  };

  return (
    <>
      <Head title={collection.name} />
      <PageShell
        title={collection.name}
        description={collection.description ?? undefined}
        back="/admin/images/"
        actions={
          <>
            {can_edit && (
              <UploadButton
                collectionId={collection.id}
                directThreshold={direct_upload_threshold}
                onDone={() => void gallery.reload()}
              />
            )}
            {can_share && <ShareDialog collectionId={collection.id} />}
          </>
        }
      >
        <div className="space-y-6">
          <Link href="/admin/images/" className="text-sm text-primary hover:underline">
            {t(keys.images.common.back_to_collections)}
          </Link>
          {can_manage && (
            <div className="flex flex-wrap items-end gap-4">
              <div className="grid gap-2">
                <Label htmlFor="images-visibility">{t(keys.images.visibility.label)}</Label>
                <VisibilitySelect
                  id="images-visibility"
                  value={visibility}
                  canPublish={can_publish}
                  disabled={saving}
                  onChange={(next) => void changeVisibility(next)}
                />
              </div>
              <ConfirmDialog
                trigger={
                  <Button type="button" variant="outline" data-testid="images-delete-collection">
                    {t(keys.images.collection.delete)}
                  </Button>
                }
                title={t(keys.images.collection.delete_title)}
                description={t(keys.images.collection.delete_body)}
                confirmLabel={t(keys.images.collection.delete_confirm)}
                onConfirm={remove}
              />
            </div>
          )}
          <div
            role="tablist"
            aria-label={t(keys.images.tabs.label)}
            className="flex gap-2 border-b"
          >
            {(['gallery', 'pipeline'] as const).map((name) => (
              <button
                key={name}
                type="button"
                role="tab"
                id={`images-tab-${name}`}
                aria-controls="images-tabpanel"
                aria-selected={tab === name}
                tabIndex={tab === name ? 0 : -1}
                data-testid={`images-tab-${name}`}
                className={`-mb-px border-b-2 px-3 py-2 text-sm ${tab === name ? 'border-primary font-medium' : 'border-transparent text-muted-foreground'}`}
                onClick={() => setTab(name)}
              >
                {t(keys.images.tabs[name])}
              </button>
            ))}
          </div>
          <div role="tabpanel" id="images-tabpanel" aria-labelledby={`images-tab-${tab}`}>
            {tab === 'gallery' ? (
              <Gallery gallery={gallery} />
            ) : (
              <PipelineTab collectionId={collection.id} canManage={can_manage} />
            )}
          </div>
        </div>
      </PageShell>
    </>
  );
}

Collection.layout = [ImagesLayout];
export default Collection;
