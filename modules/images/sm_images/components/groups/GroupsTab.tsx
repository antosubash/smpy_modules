import { Button } from '@simple-module-py/ui/components/ui/button';
import { useState } from 'react';

import { useGroups } from '../../hooks/useGroups';
import { keys, useT } from '../../utils/i18n';
import { GroupCard } from './GroupCard';
import { RegroupPanel } from './RegroupPanel';

/** The Groups tab: the collection's groups with role-ordered member thumbnails,
 *  and (for an editor) the filename-pattern regroup. `onChanged` runs after a
 *  regroup, so the gallery's group filter and chips are fresh. */
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

  return (
    <div className="space-y-4" data-testid="images-groups">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p className="text-sm text-muted-foreground">{t(text.description)}</p>
        {canEdit && !regrouping && (
          <Button
            type="button"
            data-testid="images-regroup-open"
            onClick={() => setRegrouping(true)}
          >
            {t(text.regroup.open)}
          </Button>
        )}
      </div>
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
