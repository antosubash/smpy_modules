import { router, usePage } from '@inertiajs/react';
import { PageShell } from '@simple-module-py/ui/components/PageShell';
import { Button } from '@simple-module-py/ui/components/ui/button';
import {
  Table,
  TableBody,
  TableHead,
  TableHeader,
  TableRow,
} from '@simple-module-py/ui/components/ui/table';
import { AuthenticatedLayout } from '@simple-module-py/ui/layouts/AuthenticatedLayout';
import type React from 'react';
import { toast } from 'sonner';
import { NewPageDialog } from '../components/NewPageDialog';
import { type BoardStage, PageBoard } from '../components/PageBoard';
import { type PageListFilterState, PageListFilters } from '../components/PageListFilters';
import { PageListRow } from '../components/PageListRow';
import { deletePage, type PageRead } from '../utils/api';
import { publishPage, restorePage, unpublishPage } from '../utils/pagesApi';

/** Where pages serve publicly. Mirrors `PagebuilderSettings.public_route_prefix`. */
const PUBLIC_PREFIX = '/p';

interface Props {
  pages: { items: PageRead[]; total: number };
  /** Null in list view — the board query is skipped rather than computed and
   *  thrown away. */
  board: BoardStage[] | null;
  filters: PageListFilterState & { view: string };
  /** Every language the site publishes in, and the one that serves at the
   *  unprefixed public URL. Absent on a host that predates the setting. */
  locales?: string[];
  default_locale?: string;
}

export default function PageList() {
  const props = usePage<{ props: Props }>().props as unknown as Props;
  const { pages, board, filters } = props;
  const locales = props.locales ?? [];
  const defaultLocale = props.default_locale ?? 'en';
  const multilingual = locales.length > 1;
  const { limit, offset } = filters;
  const filtering = filters.search !== '' || filters.status !== '' || filters.locale !== '';
  const boardView = filters.view !== 'list' && board !== null;

  /**
   * Re-ask the server for a slice. `preserveState` keeps the component — and
   * so the focus and caret in the search box — alive across the round trip;
   * `replace` keeps one history entry per search rather than one per
   * keystroke, so Back leaves the list instead of retyping it backwards.
   */
  const go = (next: {
    search?: string;
    status?: string;
    locale?: string;
    offset?: number;
    view?: string;
  }) => {
    // Built field by field, not `{ ...filters, ...next }`: a merged object
    // would carry a stale `offset` a reader must know to ignore. Any filter
    // change invalidates the offset — page 3 of the previous filter is not
    // page 3 of this one — so it defaults to 0, not to the current one.
    // `view` is the exception that proves it: the board/list choice is not a
    // filter, so it carries forward rather than resetting.
    router.get(
      '/pagebuilder/',
      {
        search: next.search ?? filters.search,
        status: next.status ?? filters.status,
        locale: next.locale ?? filters.locale,
        offset: next.offset ?? 0,
        view: next.view ?? filters.view,
      },
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
  const reload = () => router.reload({ only: ['pages', 'board', 'filters'] });

  /** Delete, then offer the way back.
   *
   * The toast is the reason the confirmations can stay as light as they do: a
   * deletion is recoverable for 30 days, and the ten seconds after the click is
   * when someone actually notices they hit the wrong row.
   */
  const handleDelete = async (page: PageRead) => {
    await deletePage(page.id);
    reload();
    toast(`“${page.title}” deleted`, {
      duration: 10_000,
      description: 'It is in the trash for 30 days.',
      action: {
        label: 'Undo',
        onClick: () => {
          void restorePage(page.id)
            .then(() => {
              reload();
              toast.success(`“${page.title}” restored as a draft`);
            })
            .catch((e: Error) => toast.error(e.message));
        },
      },
    });
  };

  /** Take a published page offline. The content stays; only its status moves. */
  const handleUnpublish = async (page: PageRead) => {
    await unpublishPage(page.id);
    reload();
    toast(`“${page.title}” is offline`, {
      description: 'It is a draft again. Publish it to put it back.',
    });
  };

  /** Publish from a board card. Reloads rather than patching state: the card
   *  has to leave one column and appear in another, and only the server knows
   *  what else moved with it. */
  const handlePublish = async (page: PageRead) => {
    await publishPage(page.id);
    reload();
    toast.success(`“${page.title}” published`);
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
          <Button variant="outline" onClick={() => router.visit('/pagebuilder/trash')}>
            Trash
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
          <NewPageDialog locales={locales} defaultLocale={defaultLocale} />
        </>
      }
    >
      {/* Hidden only on a genuinely empty site: with no pages at all there is
          nothing to search, and the controls would just be noise above the
          "create your first one" prompt. */}
      {(filtering || pages.total > 0) && (
        <PageListFilters filters={filters} locales={locales} onChange={go} />
      )}

      {boardView ? (
        <PageBoard
          stages={board}
          search={filters.search}
          defaultLocale={defaultLocale}
          newPageSlot={<NewPageDialog locales={locales} defaultLocale={defaultLocale} />}
          onDelete={handleDelete}
          onPublish={handlePublish}
          onUnpublish={handleUnpublish}
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
                onClick={() => go({ search: '', status: '', locale: '' })}
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
              {/* Only on a multilingual site: a column reading "English" on
                  every row is a column nobody reads twice. */}
              {multilingual && <TableHead>Language</TableHead>}
              <TableHead>Status</TableHead>
              <TableHead>Updated</TableHead>
              <TableHead className="text-right">Actions</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {pages.items.map((p) => (
              <PageListRow
                key={p.id}
                page={p}
                showLocale={multilingual}
                locales={locales}
                defaultLocale={defaultLocale}
                publicPrefix={PUBLIC_PREFIX}
                onDelete={handleDelete}
              />
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
