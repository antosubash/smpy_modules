import { Button } from '@simple-module-py/ui/components/ui/button';

import { keys, useT } from '../../utils/i18n';
import { ConfirmDialog } from '../ConfirmDialog';

interface Props {
  title: string;
  isPublished: boolean;
  busy: boolean;
  onTrash: () => Promise<unknown>;
}

/** The one control on the article screen that removes the article.
 *
 * Its own component so the page stays under the file-size cap once its copy
 * moved into the locale catalogue; the reasoning behind each level came with
 * it.
 */
export function ArticleDangerZone({ title, isPublished, busy, onTrash }: Props) {
  const { t } = useT();
  const copy = keys.news.editor;

  return (
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
