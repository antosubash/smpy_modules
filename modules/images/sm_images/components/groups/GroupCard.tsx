import { Button } from '@simple-module-py/ui/components/ui/button';
import { useState } from 'react';

import { keys, useT } from '../../utils/i18n';
import type { GroupItem } from '../../utils/types';
import { ConfirmDialog } from '../ConfirmDialog';
import { GroupForm } from './GroupForm';
import { MemberThumb } from './MemberThumb';

/** One group: its name (or key), how many images it holds and the first few
 *  members as thumbnails, already in the collection's role order. An editor can
 *  rename it and delete it. */
export function GroupCard({
  group,
  canEdit,
  onEdit,
  onDelete,
}: {
  group: GroupItem;
  canEdit: boolean;
  onEdit: (group: GroupItem, value: { key: string; name: string | null }) => Promise<unknown>;
  onDelete: (group: GroupItem) => Promise<void>;
}) {
  const { t } = useT();
  const text = keys.images.groups;
  const [editing, setEditing] = useState(false);
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
        {canEdit && !editing && (
          <div className="flex gap-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              data-testid="images-group-edit"
              onClick={() => setEditing(true)}
            >
              {t(text.edit)}
            </Button>
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
          </div>
        )}
      </div>
      {editing && (
        <GroupForm
          initial={group}
          submitLabel={t(text.edit_save)}
          onSubmit={async (value) => {
            await onEdit(group, value);
            setEditing(false);
          }}
          onCancel={() => setEditing(false)}
        />
      )}
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
