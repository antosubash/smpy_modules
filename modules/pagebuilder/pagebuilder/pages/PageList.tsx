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
import { toast } from 'sonner';
import { NewPageDialog } from '../components/NewPageDialog';
import { type BoardStage, PageBoard } from '../components/PageBoard';
import { type PageListFilterState, PageListFilters } from '../components/PageListFilters';
import { PageListRow } from '../components/PageListRow';
import { deletePage, type PageRead } from '../utils/api';
import { keys, useT } from '../utils/i18n';
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
  const { t } = useT();
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
    toast(t(keys.pagebuilder.pages.deleted, { title: page.title }), {
      duration: 10_000,
      description: t(keys.pagebuilder.pages.deleted_description),
      action: {
        label: t(keys.pagebuilder.pages.undo),
        onClick: () => {
          void restorePage(page.id)
            .then(() => {
              reload();
              toast.success(t(keys.pagebuilder.pages.restored, { title: page.title }));
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
    toast(t(keys.pagebuilder.pages.unpublished, { title: page.title }), {
      description: t(keys.pagebuilder.pages.unpublished_description),
    });
  };

  /** Publish from a board card. Reloads rather than patching state: the card
   *  has to leave one column and appear in another, and only the server knows
   *  what else moved with it. */
  const handlePublish = async (page: PageRead) => {
    await publishPage(page.id);
    reload();
    toast.success(t(keys.pagebuilder.pages.published, { title: page.title }));
  };

  return (
    <PageShell
      title={t(keys.pagebuilder.pages.title)}
      description={t(keys.pagebuilder.pages.description)}
      actions={
        <>
          <Button variant="outline" onClick={() => go({ view: boardView ? 'list' : 'board' })}>
            {boardView ? t(keys.pagebuilder.pages.list_view) : t(keys.pagebuilder.pages.board_view)}
          </Button>
          <Button variant="outline" onClick={() => router.visit('/pagebuilder/trash')}>
            {t(keys.pagebuilder.pages.trash)}
          </Button>
          <Button variant="outline" onClick={() => router.visit('/pagebuilder/pending')}>
            {t(keys.pagebuilder.pages.pending_review)}
          </Button>
          <Button variant="outline" onClick={() => router.visit('/pagebuilder/layout')}>
            {t(keys.pagebuilder.pages.site_layout)}
          </Button>
          <Button variant="outline" onClick={() => router.visit('/pagebuilder/media')}>
            {t(keys.pagebuilder.pages.media_library)}
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
              {t(keys.pagebuilder.pages.no_match)}{' '}
              <Button
                type="button"
                variant="link"
                className="h-auto p-0"
                onClick={() => go({ search: '', status: '', locale: '' })}
              >
                {t(keys.pagebuilder.pages.clear_filters)}
              </Button>
            </>
          ) : (
            t(keys.pagebuilder.pages.empty)
          )}
        </div>
      ) : (
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>{t(keys.pagebuilder.pages.column_title)}</TableHead>
              <TableHead>{t(keys.pagebuilder.pages.column_slug)}</TableHead>
              {/* Only on a multilingual site: a column reading "English" on
                  every row is a column nobody reads twice. */}
              {multilingual && <TableHead>{t(keys.pagebuilder.pages.column_language)}</TableHead>}
              <TableHead>{t(keys.pagebuilder.pages.column_status)}</TableHead>
              <TableHead>{t(keys.pagebuilder.pages.column_updated)}</TableHead>
              <TableHead className="text-right">
                {t(keys.pagebuilder.pages.column_actions)}
              </TableHead>
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
            {t(keys.pagebuilder.pages.showing, {
              from: Math.min(offset + 1, pages.total),
              to: Math.min(offset + limit, pages.total),
              total: pages.total,
            })}
          </span>
          <div className="space-x-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={offset === 0}
              onClick={() => go({ offset: Math.max(0, offset - limit) })}
            >
              {t(keys.pagebuilder.pages.previous)}
            </Button>
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={offset + limit >= pages.total}
              onClick={() => go({ offset: offset + limit })}
            >
              {t(keys.pagebuilder.pages.next)}
            </Button>
          </div>
        </div>
      )}
    </PageShell>
  );
}

PageList.layout = [AuthenticatedLayout];
