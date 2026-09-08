import { router } from '@inertiajs/react';
import { Button } from '@simple-module-py/ui/components/ui/button';
import { TableCell, TableRow } from '@simple-module-py/ui/components/ui/table';

import type { PageRead } from '../utils/api';
import { keys, useT } from '../utils/i18n';
import { localeLabel, publicPath } from '../utils/locale';
import { ConfirmDialog } from './ConfirmDialog';
import { ScheduledBadge } from './ScheduledBadge';
import { StatusBadge } from './StatusBadge';
import { TranslatePageDialog } from './TranslatePageDialog';

interface Props {
  page: PageRead;
  /** Whether to render the Language cell and the Translate action. Off on a
   *  monolingual site, where a column reading "English" on every row is one
   *  nobody reads twice and there is nothing to translate into. */
  showLocale: boolean;
  /** Every language the site publishes in. */
  locales: string[];
  defaultLocale: string;
  /** Where pages serve publicly, for the View link and the delete warning. */
  publicPrefix: string;
  onDelete: (page: PageRead) => Promise<unknown>;
}

/** One row of the page table.
 *
 * Its own component because the table outgrew the screen's 300-line budget,
 * and because the row is the part that knows how a page's public address is
 * built — which is now a function of its language as well as its slug.
 */
export function PageListRow({
  page,
  showLocale,
  locales,
  defaultLocale,
  publicPrefix,
  onDelete,
}: Props) {
  const { t } = useT();
  const address = publicPath(publicPrefix, page.slug, page.locale, defaultLocale);
  return (
    <TableRow>
      <TableCell className="font-medium">{page.title}</TableCell>
      <TableCell className="font-mono text-sm text-muted-foreground">{page.slug}</TableCell>
      {showLocale && (
        <TableCell className="text-sm text-muted-foreground">{localeLabel(page.locale)}</TableCell>
      )}
      <TableCell>
        <span className="flex flex-wrap items-center gap-1.5">
          <StatusBadge status={page.status} />
          <ScheduledBadge
            status={page.status}
            publishAt={page.publish_at}
            unpublishAt={page.unpublish_at}
          />
        </span>
      </TableCell>
      <TableCell className="text-sm text-muted-foreground">
        {page.updated_at ? new Date(page.updated_at).toLocaleString() : '—'}
      </TableCell>
      <TableCell className="space-x-1 text-right">
        {/* Stays an <a>: the e2e selects it with getByRole('link'). */}
        {page.status === 'published' && (
          <a
            href={address}
            target="_blank"
            rel="noopener noreferrer"
            className="text-sm text-primary hover:underline"
          >
            {t(keys.pagebuilder.row.view)}
          </a>
        )}
        <Button
          variant="link"
          size="sm"
          onClick={() => router.visit(`/pagebuilder/${page.id}/edit`)}
        >
          {t(keys.pagebuilder.row.edit)}
        </Button>
        {/* On the row rather than only inside the editor: "we need this in
            German" is a thought an author has while looking at the list. */}
        {showLocale && (
          <TranslatePageDialog
            page={page}
            locales={locales}
            defaultLocale={defaultLocale}
            publicPrefix={publicPrefix}
          />
        )}
        <ConfirmDialog
          trigger={
            <Button variant="link" size="sm" className="text-destructive">
              {t(keys.pagebuilder.row.delete)}
            </Button>
          }
          // The same gate the board card applies, because it is the same
          // deletion: the row you happen to be looking at must not decide how
          // much friction a live URL going dark gets.
          level={page.status === 'published' ? 'high' : 'low'}
          confirmPhrase={page.status === 'published' ? page.slug : undefined}
          title={t(keys.pagebuilder.row.delete_title, { title: page.title })}
          description={
            page.status === 'published' ? (
              // The address is a <code> span inside the sentence, so the two
              // halves are separate keys rather than one with a placeholder.
              <>
                {t(keys.pagebuilder.row.delete_published_before)} <code>{address}</code>{' '}
                {t(keys.pagebuilder.row.delete_published_after)}
              </>
            ) : (
              t(keys.pagebuilder.row.delete_draft)
            )
          }
          confirmLabel={t(keys.pagebuilder.row.delete)}
          onConfirm={() => onDelete(page)}
        />
      </TableCell>
    </TableRow>
  );
}
