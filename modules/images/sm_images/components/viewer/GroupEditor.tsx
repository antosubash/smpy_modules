import { Button } from '@simple-module-py/ui/components/ui/button';
import { Input } from '@simple-module-py/ui/components/ui/input';
import { Label } from '@simple-module-py/ui/components/ui/label';
import { useState } from 'react';
import { toast } from 'sonner';

import { assignImage, listGroups } from '../../utils/api-groups';
import { errorText } from '../../utils/api-net';
import { keys, useT } from '../../utils/i18n';
import type { GroupItem, ImageItem } from '../../utils/types';

const NONE = '';
const CUSTOM = '\u0000custom';
const GROUP_PAGE = 100;

/** Who's group an image is in, and its role there. An editor can change both:
 *  the group from the collection's first 100, the role from the collection's
 *  `group_roles` or as free text. Groups load when the editor opens. */
export function GroupEditor({
  image,
  collectionId,
  roles,
  canEdit,
  onSaved,
}: {
  image: ImageItem;
  collectionId: string;
  roles: string[];
  canEdit: boolean;
  onSaved: (image: ImageItem) => void;
}) {
  const { t } = useT();
  const text = keys.images.viewer.group;
  const [open, setOpen] = useState(false);
  const [groups, setGroups] = useState<GroupItem[] | null>(null);
  const [groupId, setGroupId] = useState(image.group_id ?? NONE);
  const listed = image.group_role === null || roles.includes(image.group_role);
  const [pick, setPick] = useState(listed ? (image.group_role ?? NONE) : CUSTOM);
  const [custom, setCustom] = useState(listed ? '' : (image.group_role ?? ''));
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const opened = async () => {
    setOpen(true);
    setError(null);
    try {
      setGroups((await listGroups(collectionId, null, GROUP_PAGE)).items);
    } catch (e) {
      setError(errorText(e));
    }
  };

  const role = pick === CUSTOM ? custom.trim() : pick;

  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      const change: { group_id: string | null; group_role?: string | null } = {
        group_id: groupId || null,
      };
      if (groupId) change.group_role = role || null;
      const saved = await assignImage(image.id, change);
      toast(t(text.saved));
      setOpen(false);
      const chosen = groups?.find((g) => g.id === groupId);
      onSaved({ ...saved, group_key: chosen?.key ?? null });
    } catch (e) {
      setError(errorText(e));
    } finally {
      setBusy(false);
    }
  };

  const label = groups?.find((g) => g.id === image.group_id);
  const shown = label?.name ?? label?.key ?? image.group_key ?? image.group_id;
  return (
    <section aria-labelledby="images-group-title" data-testid="images-image-group">
      <h2 id="images-group-title" className="mb-2 text-lg font-semibold">
        {t(text.title)}
      </h2>
      <p className="text-sm" data-testid="images-image-group-current">
        {shown ? `${shown}${image.group_role ? ` · ${image.group_role}` : ''}` : t(text.none)}
      </p>
      {canEdit && !open && (
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="mt-2"
          data-testid="images-group-change"
          onClick={() => void opened()}
        >
          {t(text.edit)}
        </Button>
      )}
      {canEdit && open && (
        <div className="mt-2 grid gap-3" data-testid="images-group-editor">
          <div className="grid gap-1">
            <Label htmlFor="images-image-group-select">{t(text.group)}</Label>
            <select
              id="images-image-group-select"
              className="h-9 rounded-md border bg-background px-2 text-sm"
              value={groupId}
              disabled={groups === null}
              onChange={(e) => setGroupId(e.target.value)}
            >
              <option value={NONE}>{groups === null ? t(text.loading) : t(text.none)}</option>
              {(groups ?? []).map((g) => (
                <option key={g.id} value={g.id}>
                  {g.name ?? g.key}
                </option>
              ))}
            </select>
          </div>
          {groupId && (
            <div className="grid gap-1">
              <Label htmlFor="images-image-role-select">{t(text.role)}</Label>
              <select
                id="images-image-role-select"
                className="h-9 rounded-md border bg-background px-2 text-sm"
                value={pick}
                onChange={(e) => setPick(e.target.value)}
              >
                <option value={NONE}>{t(text.role_none)}</option>
                {roles.map((r) => (
                  <option key={r} value={r}>
                    {r}
                  </option>
                ))}
                <option value={CUSTOM}>{t(text.role_custom)}</option>
              </select>
              {pick === CUSTOM && (
                <Input
                  aria-label={t(text.role)}
                  value={custom}
                  maxLength={50}
                  data-testid="images-role-custom"
                  onChange={(e) => setCustom(e.target.value)}
                />
              )}
            </div>
          )}
          {error && (
            <p className="text-sm text-destructive" role="alert" data-testid="images-group-error">
              {error}
            </p>
          )}
          <div className="flex gap-2">
            <Button
              type="button"
              disabled={busy}
              data-testid="images-group-save"
              onClick={() => void save()}
            >
              {t(text.save)}
            </Button>
            <Button type="button" variant="ghost" onClick={() => setOpen(false)}>
              {t(text.cancel)}
            </Button>
          </div>
        </div>
      )}
    </section>
  );
}
