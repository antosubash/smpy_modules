import { Button } from '@simple-module-py/ui/components/ui/button';

import { keys, useT } from '../../utils/i18n';
import { ConfirmDialog } from '../ConfirmDialog';

interface Props {
  title: string;
  isPublished: boolean;
  busy: boolean;
  /** Whether the viewer holds `news.publish`. */
  canPublish: boolean;
  /** Deletes and then leaves the screen — the article it was showing is gone. */
  onDelete: () => Promise<unknown>;
  onTrash: () => Promise<unknown>;
}

/** The one control on the article screen that removes the article.
 *
 * Its own component so the page stays under the file-size cap once its copy
 * moved into the locale catalogue; the reasoning behind each level came with
 * it.
 */
export function ArticleDangerZone({
  title,
  isPublished,
  busy,
  canPublish,
  onDelete,
  onTrash,
}: Props) {
  const { t } = useT();
  const copy = keys.news.editor;

  return canPublish ? (
    <ConfirmDialog
      // Medium, where this used to be low — see ArticleRow for why the
      // same button changed cost when the sidecar went away.
      //
      // Gated on canPublish: the backend requires news.publish for a
      // hard delete, the same pair it requires for purge, because
      // nothing here comes back. An author with news.edit alone gets
      // the recoverable trash below instead.
      level="medium"
      title={t(copy.delete_title, { title })}
      description={t(copy.delete_description)}
      confirmLabel={t(copy.delete_confirm)}
      onConfirm={onDelete}
      trigger={
        <Button variant="ghost" size="sm" className="text-destructive" disabled={busy}>
          {t(copy.delete_trigger)}
        </Button>
      }
    />
  ) : (
    <ConfirmDialog
      // Medium for a published article — trashing takes it off the
      // public site immediately, same as unpublish, even though it is
      // fully reversible. A draft that was never public gets low.
      level={isPublished ? 'medium' : 'low'}
      title={t(copy.trash_title, { title })}
      description={t(copy.trash_description)}
      confirmLabel={t(copy.trash_confirm)}
      onConfirm={onTrash}
      trigger={
        <Button variant="ghost" size="sm" disabled={busy}>
          {t(copy.trash_trigger)}
        </Button>
      }
    />
  );
}
