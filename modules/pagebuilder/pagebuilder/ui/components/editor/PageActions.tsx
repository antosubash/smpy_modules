import { router } from '@inertiajs/react';
import { Button } from '@simple-module-py/ui/components/ui/button';

import type { PageDetail } from '../../utils/api';
import { keys, useT } from '../../utils/i18n';
import { createPage, deletePage, savePage } from '../../utils/pagesApi';
import { ConfirmDialog } from '../ConfirmDialog';

interface Props {
  /** Null for a page that has never been saved — see below. */
  pageId: number | null;
  title: string;
  slug: string;
  status: PageDetail['status'];
  publicPrefix: string;
  onError: (message: string) => void;
  onNotice: (message: string) => void;
}

/** Duplicate, save-as-template and delete — the Page tab's own actions.
 *
 * All three need a saved page, so the whole group hides until there is one: a
 * page that exists only in the editor has no id to copy, flag or bin, and
 * showing three disabled buttons explains nothing about why.
 */
export function PageActions({
  pageId,
  title,
  slug,
  status,
  publicPrefix,
  onError,
  onNotice,
}: Props) {
  const { t } = useT();
  if (pageId === null) return null;

  const published = status === 'published';

  return (
    <>
      <Button
        type="button"
        variant="outline"
        size="sm"
        onClick={() => {
          void createPage({
            title: `${title} copy`,
            slug: `${slug}-copy`,
            copy_from_page_id: pageId,
          })
            .then((copy) => router.visit(`/pagebuilder/${copy.id}/edit`))
            .catch((e: Error) => onError(e.message));
        }}
      >
        {t(keys.pagebuilder.actions.duplicate)}
      </Button>

      <Button
        type="button"
        variant="outline"
        size="sm"
        onClick={() => {
          void savePage(pageId, { is_template: true })
            .then(() => onNotice(t(keys.pagebuilder.actions.templated)))
            .catch((e: Error) => onError(e.message));
        }}
      >
        {t(keys.pagebuilder.actions.save_template)}
      </Button>

      <ConfirmDialog
        // The editor's delete is the same soft delete the board's is — the page
        // goes to the trash — so the level tracks whether it is currently
        // public, not whether it is recoverable.
        level={published ? 'high' : 'low'}
        confirmPhrase={published ? slug : undefined}
        title={t(keys.pagebuilder.row.delete_title, { title })}
        description={
          published ? (
            <>
              {t(keys.pagebuilder.row.delete_published_before)}{' '}
              <code>{`${publicPrefix}/${slug}`}</code>{' '}
              {t(keys.pagebuilder.actions.delete_published_after)}
            </>
          ) : (
            t(keys.pagebuilder.row.delete_draft)
          )
        }
        confirmLabel={t(keys.pagebuilder.actions.delete)}
        onConfirm={async () => {
          await deletePage(pageId);
          router.visit('/pagebuilder/');
        }}
        trigger={
          <Button type="button" variant="ghost" size="sm" className="text-destructive">
            {t(keys.pagebuilder.actions.delete_page)}
          </Button>
        }
      />
    </>
  );
}
