import { Button } from '@simple-module-py/ui/components/ui/button';

import type { ArticleRead } from '../utils/api';
import { keys, useT } from '../utils/i18n';
import { ConfirmDialog } from './ConfirmDialog';

interface Props {
  article: ArticleRead;
  busy: boolean;
  onTrash: (id: number) => Promise<unknown>;
}

/** The recoverable removal action shared by authors and publishers. */
export function ArticleRowDelete({ article, busy, onTrash }: Props) {
  const { t } = useT();
  const row = keys.news.row;

  return (
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
