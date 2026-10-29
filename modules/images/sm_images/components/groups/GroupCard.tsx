import { Button } from '@simple-module-py/ui/components/ui/button';

import { keys, useT } from '../../utils/i18n';
import type { GroupItem } from '../../utils/types';
import { ConfirmDialog } from '../ConfirmDialog';
import { MemberThumb } from './MemberThumb';

/** One group: its name (or key), how many images it holds and the first few
 *  members as thumbnails, already in the collection's role order. */
export function GroupCard({
  group,
  canEdit,
  onDelete,
}: {
  group: GroupItem;
  canEdit: boolean;
  onDelete: (group: GroupItem) => Promise<void>;
}) {
  const { t } = useT();
  const text = keys.images.groups;
  const hidden = group.image_count - group.members.length;

  return (
    <li
      className="space-y-2 rounded-md border p-3"
      data-testid="images-group"
      data-group-id={group.id}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div>
          <p className="font-medium">{group.name ?? group.key}</p>
          <p className="text-xs text-muted-foreground">
            {group.name ? `${group.key} · ` : ''}
            {t(text.image_count, { count: group.image_count })}
          </p>
        </div>
        {canEdit && (
          <ConfirmDialog
            trigger={
              <Button type="button" variant="outline" size="sm" data-testid="images-group-delete">
                {t(text.delete)}
              </Button>
            }
            title={t(text.delete_title)}
            description={t(text.delete_body)}
            confirmLabel={t(text.delete_confirm)}
            onConfirm={() => onDelete(group)}
          />
        )}
      </div>
      {group.members.length === 0 ? (
        <p className="text-sm text-muted-foreground">{t(text.no_members)}</p>
      ) : (
        <ul className="flex flex-wrap gap-2">
          {group.members.map((image) => (
            <MemberThumb key={image.id} image={image} />
          ))}
          {hidden > 0 && (
            <li className="flex size-20 items-center justify-center text-xs text-muted-foreground">
              {t(text.more_members, { count: hidden })}
            </li>
          )}
        </ul>
      )}
    </li>
  );
}
