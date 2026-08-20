import { Head, router } from '@inertiajs/react';
import { PageShell } from '@simple-module-py/ui/components/PageShell';
import { Button } from '@simple-module-py/ui/components/ui/button';
import { Skeleton } from '@simple-module-py/ui/components/ui/skeleton';
import { AuthenticatedLayout } from '@simple-module-py/ui/layouts/AuthenticatedLayout';
import { useCallback, useEffect, useState } from 'react';
import { toast } from 'sonner';

import { ConfirmDialog } from '../components/ConfirmDialog';
import type { PageRead } from '../utils/api';
import { listTrash, purgePage, restorePage } from '../utils/pagesApi';

/** Matches `RETENTION_DAYS` in the service. Stated on screen because the
 *  promise — "emptied automatically" — is only trustworthy with a number. */
const RETENTION_DAYS = 30;

/** "in 12 days" / "today" — how long a trashed page has left. */
function daysLeft(deletedAt: string | null): string {
  if (!deletedAt) return '';
  const binned = new Date(deletedAt).getTime();
  if (Number.isNaN(binned)) return '';
  const left = RETENTION_DAYS - Math.floor((Date.now() - binned) / 86_400_000);
  if (left <= 0) return 'due to be removed';
  if (left === 1) return 'removed tomorrow';
  return `removed in ${left} days`;
}

/** Trash — pages deleted but still recoverable.
 *
 * Restore is the primary action and purge is the quiet one, because the whole
 * reason this screen exists is that a deletion turned out to be a mistake. A
 * screen that led with "delete forever" would be a second chance to make the
 * same one.
 */
export default function Trash() {
  const [pages, setPages] = useState<PageRead[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async (signal?: AbortSignal) => {
    try {
      const response = await listTrash();
      if (signal?.aborted) return;
      setPages(response.items);
      setError(null);
    } catch (e) {
      if (signal?.aborted) return;
      setError((e as Error).message);
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  const restore = async (page: PageRead) => {
    setBusy(true);
    try {
      await restorePage(page.id);
      await load();
      toast.success(`“${page.title}” restored`, {
        description: 'It came back as a draft. Publish it when you are ready.',
        action: { label: 'Open', onClick: () => router.visit(`/pagebuilder/${page.id}/edit`) },
      });
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <PageShell
      title="Trash"
      description={`Deleted pages, recoverable for ${RETENTION_DAYS} days. After that they are removed automatically.`}
      actions={
        <Button variant="outline" onClick={() => router.visit('/pagebuilder/')}>
          Back to pages
        </Button>
      }
    >
      <Head title="Trash" />
      {error && <p className="mb-4 text-sm text-destructive">{error}</p>}

      {pages === null ? (
        <div role="status" aria-label="Loading trash" className="space-y-2">
          <Skeleton className="h-16 w-full" />
          <Skeleton className="h-16 w-full" />
        </div>
      ) : pages.length === 0 ? (
        <div className="rounded-lg border border-dashed p-8 text-center">
          <p className="font-medium">Nothing in the trash</p>
          <p className="mt-1 text-sm text-muted-foreground">
            Deleted pages land here and stay recoverable for {RETENTION_DAYS} days.
          </p>
        </div>
      ) : (
        <ul className="space-y-2">
          {pages.map((page) => (
            <li
              key={page.id}
              data-testid="trash-row"
              data-slug={page.slug}
              className="flex items-center gap-3 rounded-lg border bg-card p-3"
            >
              <div className="min-w-0 flex-1">
                <p className="truncate font-medium">{page.title || 'Untitled page'}</p>
                <p className="truncate text-sm text-muted-foreground">
                  /p/{page.slug} · {daysLeft(page.deleted_at)}
                </p>
              </div>

              <Button type="button" size="sm" disabled={busy} onClick={() => void restore(page)}>
                Restore
              </Button>

              <ConfirmDialog
                // High: purge is the one operation the trash cannot undo.
                level="high"
                confirmPhrase={page.slug}
                title={`Delete “${page.title}” forever?`}
                description={
                  <>
                    This removes the page and its revision history for good. It is the one action on
                    this screen that the trash cannot undo.
                  </>
                }
                confirmLabel="Delete forever"
                onConfirm={async () => {
                  await purgePage(page.id);
                  await load();
                  toast.success(`“${page.title}” deleted forever`);
                }}
                trigger={
                  <Button type="button" size="sm" variant="ghost" className="text-destructive">
                    Delete forever
                  </Button>
                }
              />
            </li>
          ))}
        </ul>
      )}
    </PageShell>
  );
}

Trash.layout = (page: React.ReactNode) => <AuthenticatedLayout>{page}</AuthenticatedLayout>;
