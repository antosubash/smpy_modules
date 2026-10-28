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
};

/** `Images/Collection` - `/admin/images/{id}`. Tabs come with their own tasks
 *  (map, imports, pipeline, review); only the gallery exists today. */
function Collection({ collection, can_edit, can_manage, can_share, can_publish }: Props) {
  const { t } = useT();
  const gallery = useImages(collection.id);
  const [visibility, setVisible] = useState<Visibility>(collection.visibility);
  const [saving, setSaving] = useState(false);

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
              <UploadButton collectionId={collection.id} onDone={() => void gallery.reload()} />
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
          <Gallery gallery={gallery} />
        </div>
      </PageShell>
    </>
  );
}

Collection.layout = [ImagesLayout];
export default Collection;
