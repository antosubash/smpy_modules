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
import { GroupsTab } from '../components/groups/GroupsTab';
import { ImagesLayout } from '../components/ImagesLayout';
import { ImportsTab } from '../components/imports/ImportsTab';
import { CollectionMap } from '../components/map/CollectionMap';
import { PipelineTab } from '../components/pipeline/PipelineTab';
import { PromptsTab } from '../components/prompts/PromptsTab';
import { RunOnImages } from '../components/prompts/RunOnImages';
import { ShareDialog } from '../components/share/ShareDialog';
import { useImages } from '../hooks/useImages';
import { deleteCollection, setVisibility } from '../utils/api';
import { errorText } from '../utils/api-net';
import { keys, useT } from '../utils/i18n';
import type { Collection as CollectionRow, Visibility } from '../utils/types';

type Props = {
  collection: CollectionRow;
  can_edit: boolean;
  can_manage: boolean;
  can_share: boolean;
  can_publish: boolean;
  direct_upload_threshold: number;
  /** The map's basemap style; empty is a flat background. */
  map_style_url?: string;
};

type Tab = 'gallery' | 'map' | 'groups' | 'pipeline' | 'prompts' | 'imports';

/** `Images/Collection` - `/admin/images/{id}`. Tabs: the gallery, the groups,
 *  the map, the pipeline, the prompts and (for an editor) the imports. Review
 *  is a screen of its own. */
function Collection({
  collection,
  can_edit,
  can_manage,
  can_share,
  can_publish,
  direct_upload_threshold,
  map_style_url = '',
}: Props) {
  const { t } = useT();
  const gallery = useImages(collection.id);
  const [visibility, setVisible] = useState<Visibility>(collection.visibility);
  const [saving, setSaving] = useState(false);
  const [tab, setTab] = useState<Tab>('gallery');
  const [picking, setPicking] = useState(false);
  const [picked, setPicked] = useState<string[]>([]);
  // An editor picks images to run an image prompt on (missing or stale only).
  const pick = can_edit
    ? {
        active: picking,
        setActive: (active: boolean) => {
          setPicking(active);
          if (!active) setPicked([]);
        },
        ids: picked,
        toggle: (id: string) =>
          setPicked((ids) => (ids.includes(id) ? ids.filter((i) => i !== id) : [...ids, id])),
        actions: (
          <RunOnImages
            collectionId={collection.id}
            imageIds={picked}
            onDone={() => setPicked([])}
          />
        ),
      }
    : undefined;
  // The import routes and the pipeline overview (its progress counts cover images
  // still withheld) are an edit on the collection, so those tabs are an editor's.
  const tabs: Tab[] = can_edit
    ? ['gallery', 'map', 'groups', 'pipeline', 'prompts', 'imports']
    : ['gallery', 'map', 'groups', 'prompts'];

  const changeVisibility = async (next: Visibility) => {
    setSaving(true);
    try {
      await setVisibility(collection.id, next);
      setVisible(next);
      toast(t(keys.images.visibility.changed));
    } catch (e) {
      toast.error(errorText(e));
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
            {can_edit && (
              <Button
                type="button"
                variant="outline"
                data-testid="images-open-review"
                onClick={() => router.visit(`/admin/images/${collection.id}/review`)}
              >
                {t(keys.images.review.open)}
              </Button>
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
            {tabs.map((name) => (
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
                onClick={() => {
                  // Images may have arrived (an import, an upload elsewhere) while away.
                  if (name === 'gallery' && tab !== 'gallery') void gallery.reload();
                  setTab(name);
                }}
              >
                {t(keys.images.tabs[name])}
              </button>
            ))}
          </div>
          <div role="tabpanel" id="images-tabpanel" aria-labelledby={`images-tab-${tab}`}>
            {tab === 'gallery' && <Gallery gallery={gallery} pick={pick} />}
            {tab === 'map' && (
              <CollectionMap
                pointsUrl={`/api/images/collections/${collection.id}/points`}
                mapUrl={`/api/images/collections/${collection.id}/map.pmtiles`}
                styleUrl={map_style_url}
                bbox={collection.bbox}
                onSelect={(id) => router.visit(`/admin/images/images/${id}`)}
              />
            )}
            {tab === 'groups' && (
              <GroupsTab
                collectionId={collection.id}
                canEdit={can_edit}
                onChanged={() => void gallery.reload()}
              />
            )}
            {tab === 'pipeline' && (
              <PipelineTab collectionId={collection.id} canManage={can_manage} />
            )}
            {tab === 'prompts' && (
              <PromptsTab collectionId={collection.id} canEdit={can_edit} canManage={can_manage} />
            )}
            {tab === 'imports' && (
              <ImportsTab
                collectionId={collection.id}
                canEdit={can_edit}
                onSettled={() => void gallery.reload()}
              />
            )}
          </div>
        </div>
      </PageShell>
    </>
  );
}

Collection.layout = [ImagesLayout];
export default Collection;
