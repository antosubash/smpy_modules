import { router, usePage } from '@inertiajs/react';
import { PageShell } from '@simple-module-py/ui/components/PageShell';
import { Button } from '@simple-module-py/ui/components/ui/button';
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from '@simple-module-py/ui/components/ui/table';
import { AuthenticatedLayout } from '@simple-module-py/ui/layouts/AuthenticatedLayout';
import type React from 'react';

import { ConfirmDialog } from '../components/ConfirmDialog';
import { type BoardStage, PageBoard } from '../components/PageBoard';
import { type PageListFilterState, PageListFilters } from '../components/PageListFilters';
import { ScheduledBadge } from '../components/ScheduledBadge';
import { StatusBadge } from '../components/StatusBadge';
import { deletePage, type PageRead } from '../utils/api';
import { publishPage } from '../utils/pagesApi';

interface Props {
  pages: { items: PageRead[]; total: number };
  /** Null in list view — the board query is skipped rather than computed and
   *  thrown away. */
  board: BoardStage[] | null;
  filters: PageListFilterState & { view: string };
}

export default function PageList() {
  const { pages, board, filters } = usePage<{ props: Props }>().props as unknown as Props;
  const { limit, offset } = filters;
  const filtering = filters.search !== '' || filters.status !== '';
  const boardView = filters.view !== 'list' && board !== null;

  /**
   * Re-ask the server for a slice. `preserveState` keeps the component — and
   * so the focus and caret in the search box — alive across the round trip;
   * `replace` keeps one history entry per search rather than one per
   * keystroke, so Back leaves the list instead of retyping it backwards.
   */
  const go = (next: { search?: string; status?: string; offset?: number; view?: string }) => {
    const merged = { ...filters, ...next };
    // Any filter change invalidates the offset: page 3 of the previous filter
    // is not page 3 of this one.
    const nextOffset = next.offset ?? 0;
    router.get(
      '/pagebuilder/',
      { search: merged.search, status: merged.status, offset: nextOffset, view: merged.view },
      {
        only: ['pages', 'board', 'filters'],
        preserveState: true,
        preserveScroll: true,
        replace: true,
      },
    );
  };

  // Deliberately not caught here: ConfirmDialog keeps itself open and shows
  // the message. This used to be a bare try/finally, so a delete refused by
  // the server cleared the busy flag and left the row sitting there — visually
  // identical to a delete that had not been confirmed yet.
  const handleDelete = async (id: number) => {
    await deletePage(id);
    router.reload({ only: ['pages', 'board', 'filters'] });
  };

  /** Publish from a board card. Reloads rather than patching state: the card
   *  has to leave one column and appear in another, and only the server knows
   *  what else moved with it. */
  const handlePublish = async (page: PageRead) => {
    await publishPage(page.id);
    router.reload({ only: ['pages', 'board', 'filters'] });
  };

  return (
    <PageShell
      title="Pages"
      description="Drafts, scheduled drafts, published · public at /p/:slug"
      actions={
        <>
          <Button variant="outline" onClick={() => go({ view: boardView ? 'list' : 'board' })}>
            {boardView ? 'List view' : 'Board view'}
          </Button>
          <Button variant="outline" onClick={() => router.visit('/pagebuilder/pending')}>
            Pending review
          </Button>
          <Button variant="outline" onClick={() => router.visit('/pagebuilder/layout')}>
            Site layout
          </Button>
          <Button variant="outline" onClick={() => router.visit('/pagebuilder/media')}>
            Media library
          </Button>
          <Button onClick={() => router.visit('/pagebuilder/new')}>New page</Button>
        </>
      }
    >
      {/* Hidden only on a genuinely empty site: with no pages at all there is
          nothing to search, and the controls would just be noise above the
          "create your first one" prompt. */}
      {(filtering || pages.total > 0) && <PageListFilters filters={filters} onChange={go} />}

      {boardView ? (
        <PageBoard
          stages={board}
          search={filters.search}
          onDelete={(page) => handleDelete(page.id)}
          onPublish={handlePublish}
        />
      ) : pages.items.length === 0 ? (
        <div className="rounded-lg border border-dashed p-8 text-center text-muted-foreground">
          {filtering ? (
            <>
              No pages match this filter.{' '}
              <Button
                type="button"
                variant="link"
                className="h-auto p-0"
                onClick={() => go({ search: '', status: '' })}
              >
                Clear filters
              </Button>
            </>
          ) : (
            'No pages yet. Click "New page" to create your first one.'
          )}
        </div>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Title</TableHead>
              <TableHead>Slug</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Updated</TableHead>
              <TableHead className="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {pages.items.map((p) => (
              <TableRow key={p.id}>
                <TableCell className="font-medium">{p.title}</TableCell>
                <TableCell className="font-mono text-sm text-muted-foreground">{p.slug}</TableCell>
                <TableCell>
                  <span className="flex flex-wrap items-center gap-1.5">
                    <StatusBadge status={p.status} />
                    <ScheduledBadge
                      status={p.status}
                      publishAt={p.publish_at}
                      unpublishAt={p.unpublish_at}
                    />
                  </span>
                </TableCell>
                <TableCell className="text-sm text-muted-foreground">
                  {p.updated_at ? new Date(p.updated_at).toLocaleString() : '—'}
                </TableCell>
                <TableCell className="space-x-1 text-right">
                  {/* Stays an <a>: the e2e selects it with getByRole('link'). */}
                  {p.status === 'published' && (
                    <a
                      href={`/p/${p.slug}`}
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
                    onClick={() => router.visit(`/pagebuilder/${p.id}/edit`)}
                  >
                    Edit
                  </Button>
                  <ConfirmDialog
                    trigger={
                      <Button variant="link" size="sm" className="text-destructive">
                        Delete
                      </Button>
                    }
                    title={`Delete "${p.title}"?`}
                    description={
                      <>
                        The page and its revision history are removed for good.
                        {p.status === 'published' && (
                          <> It is published, so {`/p/${p.slug}`} starts answering 404.</>
                        )}
                      </>
                    }
                    confirmLabel="Delete"
                    destructive
                    onConfirm={() => handleDelete(p.id)}
                  />
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      )}

      {!boardView && pages.total > limit && (
        <div className="mt-4 flex items-center justify-between text-sm text-muted-foreground">
          <span>
            Showing {Math.min(offset + 1, pages.total)}–{Math.min(offset + limit, pages.total)} of{' '}
            {pages.total}
          </span>
          <div className="space-x-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={offset === 0}
              onClick={() => go({ offset: Math.max(0, offset - limit) })}
            >
              Previous
            </Button>
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={offset + limit >= pages.total}
              onClick={() => go({ offset: offset + limit })}
            >
              Next
            </Button>
          </div>
        </div>
      )}
    </PageShell>
  );
}

PageList.layout = (page: React.ReactNode) => <AuthenticatedLayout>{page}</AuthenticatedLayout>;
