import { router } from '@inertiajs/react';
import { Button } from '@simple-module-py/ui/components/ui/button';
import { TableCell, TableRow } from '@simple-module-py/ui/components/ui/table';

import type { PageRead } from '../utils/api';
import { localeLabel, publicPath } from '../utils/locale';
import { ConfirmDialog } from './ConfirmDialog';
import { ScheduledBadge } from './ScheduledBadge';
import { StatusBadge } from './StatusBadge';

interface Props {
  page: PageRead;
  /** Whether to render the Language cell. Off on a monolingual site, where a
   *  column reading "English" on every row is one nobody reads twice. */
  showLocale: boolean;
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
export function PageListRow({ page, showLocale, defaultLocale, publicPrefix, onDelete }: Props) {
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
            View
          </a>
        )}
        <Button
          variant="link"
          size="sm"
          onClick={() => router.visit(`/pagebuilder/${page.id}/edit`)}
        >
          Edit
        </Button>
        <ConfirmDialog
          trigger={
            <Button variant="link" size="sm" className="text-destructive">
              Delete
            </Button>
          }
          // The same gate the board card applies, because it is the same
          // deletion: the row you happen to be looking at must not decide how
          // much friction a live URL going dark gets.
          level={page.status === 'published' ? 'high' : 'low'}
          confirmPhrase={page.status === 'published' ? page.slug : undefined}
          title={`Delete "${page.title}"?`}
          description={
            page.status === 'published' ? (
              <>
                This page is published. <code>{address}</code> starts answering 404 the moment you
                confirm. It goes to the trash for 30 days, and after that it is gone.
              </>
            ) : (
              <>
                It was never published, so nothing on the site changes. It goes to the trash for 30
                days.
              </>
            )
          }
          confirmLabel="Delete"
          onConfirm={() => onDelete(page)}
        />
      </TableCell>
    </TableRow>
  );
}
