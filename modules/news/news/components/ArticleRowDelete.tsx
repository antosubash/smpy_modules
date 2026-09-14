import { Button } from '@simple-module-py/ui/components/ui/button';

import type { ArticleRead } from '../utils/api';
import { keys, useT } from '../utils/i18n';
import { ConfirmDialog } from './ConfirmDialog';

interface Props {
  article: ArticleRead;
  busy: boolean;
  /** Whether the viewer holds `news.publish`. */
  canPublish: boolean;
  onDelete: (id: number) => Promise<unknown>;
  onTrash: (id: number) => Promise<unknown>;
}

/** The destructive door on an article row — which one depends on the viewer.
 *
 * Its own component because `ArticleRow` sits against the file-size cap and
 * this is the one self-contained piece of it; the reasoning that used to sit
 * inline came with it.
 */
export function ArticleRowDelete({ article, busy, canPublish, onDelete, onTrash }: Props) {
  const { t } = useT();
  const row = keys.news.row;

  return canPublish ? (
    <ConfirmDialog
      // Medium, where this used to be low. "Detach" removed news' metadata
      // and left the document standing in pagebuilder, so it cost nothing
      // that could not be re-attached. There is no second document now —
      // the body is this row — so the same button destroys the article.
      //
      // Gated on `canPublish`: the backend requires `news.publish` here,
      // the same pair `purge` carries, because a hard delete is the one
      // action with no way back. An author with `news.edit` alone gets
      // the recoverable door below instead.
      level="medium"
      title={t(row.delete_title, { title: article.title })}
      description={t(row.delete_description)}
      confirmLabel={t(row.delete_confirm)}
      onConfirm={() => onDelete(article.id)}
      trigger={
        <Button type="button" size="sm" variant="ghost" disabled={busy}>
          {t(row.delete_confirm)}
        </Button>
      }
    />
  ) : (
    <ConfirmDialog
      // Medium for a published article — trashing takes it off the
      // public site immediately, same as unpublish, even though it is
      // fully reversible. Low would undersell that. A draft that was
      // never public fits "low" on the same scale, so it gets it.
      level={article.status === 'published' ? 'medium' : 'low'}
      title={t(row.trash_title, { title: article.title })}
      description={t(row.trash_description)}
      confirmLabel={t(row.trash_confirm)}
      onConfirm={async () => onTrash(article.id)}
      trigger={
        <Button type="button" size="sm" variant="ghost" disabled={busy}>
          {t(row.trash_confirm)}
        </Button>
      }
    />
  );
}
