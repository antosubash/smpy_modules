import { Button } from '@simple-module-py/ui/components/ui/button';
import { Input } from '@simple-module-py/ui/components/ui/input';
import { useState } from 'react';

import { keys, useT } from '../../utils/i18n';
import type { TagRead } from '../../utils/taxonomyApi';
import { ConfirmDialog } from '../ConfirmDialog';

interface Props {
  tag: TagRead;
  busy: boolean;
  /** Resolves to whether the rename was written; a refused one stays editable. */
  onRename: (id: number, name: string) => Promise<boolean>;
  /** Rejecting keeps the confirmation open with the failure in it. */
  onDelete: (id: number) => Promise<unknown>;
}

/** Rename or delete the one selected tag.
 *
 * The category row's rules, applied to a chip: the rename is inline with the
 * usage count beside it, and closes only once the server has written it, so a
 * name another tag already holds (a 409 — that is a merge, not a rename) is
 * still there to correct.
 *
 * Deleting detaches the tag from its articles rather than refusing while any
 * use it. That is the category screen's promise too — removing a grouping never
 * takes an article with it — and a tag, unlike a category, is not an article's
 * only grouping, so there is nothing to reassign them to. The dialog says how
 * many articles lose the label before it does it.
 */
export function TagActions({ tag, busy, onRename, onDelete }: Props) {
  const { t } = useT();
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(tag.name);
  const count = tag.article_count;

  const startEditing = () => {
    setName(tag.name);
    setEditing(true);
  };

  const save = async () => {
    const trimmed = name.trim();
    if (!trimmed) return;
    if (trimmed === tag.name || (await onRename(tag.id, trimmed))) setEditing(false);
  };

  return (
    <div
      data-testid="tag-actions"
      className="flex flex-wrap items-center justify-between gap-2 rounded-md border bg-muted/40 p-2 text-sm"
    >
      {editing ? (
        <form
          className="flex w-full gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            void save();
          }}
        >
          <Input
            className="min-w-0"
            aria-label={t(keys.news.tags.name_label)}
            value={name}
            autoFocus
            disabled={busy}
            onChange={(e) => setName(e.target.value)}
          />
          <Button type="submit" size="sm" disabled={busy || !name.trim()}>
            {t(keys.news.tags.save)}
          </Button>
          <Button
            type="button"
            size="sm"
            variant="ghost"
            disabled={busy}
            onClick={() => setEditing(false)}
          >
            {t(keys.news.tags.cancel)}
          </Button>
        </form>
      ) : (
        <>
          <span className="min-w-0 break-words">
            {t(keys.news.tags.selected_summary, { name: tag.name, count })}
          </span>
          <div className="flex shrink-0 gap-1">
            <Button
              type="button"
              size="sm"
              variant="outline"
              disabled={busy}
              onClick={startEditing}
            >
              {t(keys.news.tags.rename)}
            </Button>
            <ConfirmDialog
              level={count === 0 ? 'low' : 'medium'}
              title={t(keys.news.tags.delete_title, { name: tag.name })}
              description={
                count === 0
                  ? t(keys.news.tags.delete_unused)
                  : t(keys.news.tags.delete_detaching, { count })
              }
              confirmLabel={t(keys.news.tags.delete_confirm)}
              onConfirm={() => onDelete(tag.id)}
              trigger={
                <Button type="button" size="sm" variant="ghost" disabled={busy}>
                  {t(keys.news.tags.delete)}
                </Button>
              }
            />
          </div>
        </>
      )}
    </div>
  );
}
