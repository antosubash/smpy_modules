import { Button } from '@simple-module-py/ui/components/ui/button';
import { useState } from 'react';
import { toast } from 'sonner';

import { useGroups } from '../../hooks/useGroups';
import { keys, useT } from '../../utils/i18n';
import { GroupCard } from './GroupCard';
import { GroupForm } from './GroupForm';
import { RegroupPanel } from './RegroupPanel';

/** The Groups tab: the collection's groups with role-ordered member thumbnails;
 *  for an editor also create / rename / delete and the filename-pattern regroup.
 *  `onChanged` runs after a change, so the gallery's group filter is fresh. */
export function GroupsTab({
  collectionId,
  canEdit,
  onChanged,
}: {
  collectionId: string;
  canEdit: boolean;
  onChanged?: () => void;
}) {
  const { t } = useT();
  const text = keys.images.groups;
  const groups = useGroups(collectionId);
  const [regrouping, setRegrouping] = useState(false);
  const [creating, setCreating] = useState(false);

  return (
    <div className="space-y-4" data-testid="images-groups">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-muted-foreground">{t(text.description)}</p>
        {canEdit && (
          <div className="flex gap-2">
            {!creating && (
              <Button
                type="button"
                variant="outline"
                data-testid="images-group-new"
                onClick={() => setCreating(true)}
              >
                {t(text.create)}
              </Button>
            )}
            {!regrouping && (
              <Button
                type="button"
                data-testid="images-regroup-open"
                onClick={() => setRegrouping(true)}
              >
                {t(text.regroup.open)}
              </Button>
            )}
          </div>
        )}
      </div>
      {canEdit && creating && (
        <GroupForm
          submitLabel={t(text.create_submit)}
          onSubmit={async (value) => {
            await groups.create(value);
            toast(t(text.created));
            setCreating(false);
            onChanged?.();
          }}
          onCancel={() => setCreating(false)}
        />
      )}
      {canEdit && regrouping && (
        <RegroupPanel
          collectionId={collectionId}
          onApplied={() => {
            void groups.reload();
            onChanged?.();
          }}
          onClose={() => setRegrouping(false)}
        />
      )}
      {groups.error && (
        <p className="text-sm text-destructive" role="alert">
          {t(text.refresh_failed)} {groups.error}
        </p>
      )}
      {groups.loading && groups.items.length === 0 ? (
        <p className="text-sm text-muted-foreground">{t(text.loading)}</p>
      ) : groups.items.length === 0 ? (
        <p className="text-sm text-muted-foreground" data-testid="images-groups-empty">
          {t(text.empty)}
        </p>
      ) : (
        <ul className="space-y-3">
          {groups.items.map((group) => (
            <GroupCard
              key={group.id}
              group={group}
              canEdit={canEdit}
              onEdit={async (g, value) => {
                await groups.edit(g, value);
                toast(t(text.saved));
              }}
              onDelete={async (g) => {
                await groups.remove(g);
                onChanged?.();
              }}
            />
          ))}
        </ul>
      )}
      {groups.hasMore && (
        <Button type="button" variant="outline" disabled={groups.loading} onClick={groups.loadMore}>
          {t(text.load_more)}
        </Button>
      )}
    </div>
  );
}
