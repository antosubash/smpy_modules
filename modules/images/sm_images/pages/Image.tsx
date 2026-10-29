import { Head, router } from '@inertiajs/react';
import { PageShell } from '@simple-module-py/ui/components/PageShell';
import { Button } from '@simple-module-py/ui/components/ui/button';
import { toast } from 'sonner';

import { ConfirmDialog } from '../components/ConfirmDialog';
import { ImagesLayout } from '../components/ImagesLayout';
import { ImageMeta } from '../components/viewer/ImageMeta';
import { ImageViewer } from '../components/viewer/ImageViewer';
import { deleteImage } from '../utils/api';
import { keys, useT } from '../utils/i18n';
import type { Collection, ImageItem } from '../utils/types';

type Props = {
  image: ImageItem;
  collection: Collection;
  can_view_original: boolean;
  /** The display copy is withheld until anonymisation settles. */
  display_pending?: boolean;
  can_edit: boolean;
  can_manage: boolean;
};

/** `Images/Image` - `/admin/images/images/{id}`. `can_view_original` is the
 *  server's answer, computed with the serving route's own rule. */
function Image({ image, collection, can_view_original, display_pending, can_manage }: Props) {
  const { t } = useT();
  const back = `/admin/images/${collection.id}`;

  const remove = async () => {
    await deleteImage(image.id);
    toast(t(keys.images.viewer.deleted));
    router.visit(back);
  };

  return (
    <>
      <Head title={image.filename} />
      <PageShell
        title={image.filename}
        description={collection.name}
        back={back}
        actions={
          <>
            <Button type="button" variant="outline" onClick={() => router.visit(back)}>
              {t(keys.images.viewer.back)}
            </Button>
            {can_manage && (
              <ConfirmDialog
                trigger={
                  <Button type="button" variant="outline" data-testid="images-delete-image">
                    {t(keys.images.viewer.delete)}
                  </Button>
                }
                title={t(keys.images.viewer.delete_title)}
                description={t(keys.images.viewer.delete_body)}
                confirmLabel={t(keys.images.viewer.delete_confirm)}
                onConfirm={remove}
              />
            )}
          </>
        }
      >
        <div className="grid gap-8 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
          <ImageViewer
            key={image.id}
            image={image}
            canViewOriginal={can_view_original}
            displayPending={display_pending}
          />
          <ImageMeta image={image} />
        </div>
      </PageShell>
    </>
  );
}

Image.layout = [ImagesLayout];
export default Image;
