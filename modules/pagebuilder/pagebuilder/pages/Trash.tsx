import { Head, router } from '@inertiajs/react';
import { PageShell } from '@simple-module-py/ui/components/PageShell';
import { Button } from '@simple-module-py/ui/components/ui/button';
import { Skeleton } from '@simple-module-py/ui/components/ui/skeleton';
import { AuthenticatedLayout } from '@simple-module-py/ui/layouts/AuthenticatedLayout';
import { useCallback, useEffect, useState } from 'react';
import { toast } from 'sonner';

import { ConfirmDialog } from '../components/ConfirmDialog';
import type { PageRead } from '../utils/api';
import { keys, translate, useT } from '../utils/i18n';
import { listTrash, purgePage, restorePage } from '../utils/pagesApi';

/** Matches `RETENTION_DAYS` in the service. Stated on screen because the
 *  promise — "emptied automatically" — is only trustworthy with a number. */
const RETENTION_DAYS = 30;

/** "in 12 days" / "today" — how long a trashed page has left.
 *
 *  Resolved through `translate` rather than a hook: it is a plain function the
 *  row calls while rendering, so it reads the language in force at that
 *  moment without the caller threading `t` through. */
function daysLeft(deletedAt: string | null): string {
  if (!deletedAt) return '';
  const binned = new Date(deletedAt).getTime();
  if (Number.isNaN(binned)) return '';
  const left = RETENTION_DAYS - Math.floor((Date.now() - binned) / 86_400_000);
  if (left <= 0) return translate(keys.pagebuilder.trash.due);
  if (left === 1) return translate(keys.pagebuilder.trash.tomorrow);
  return translate(keys.pagebuilder.trash.in_days, { count: left });
}

/** Trash — pages deleted but still recoverable.
 *
 * Restore is the primary action and purge is the quiet one, because the whole
 * reason this screen exists is that a deletion turned out to be a mistake. A
 * screen that led with "delete forever" would be a second chance to make the
 * same one.
 */
export default function Trash() {
  const { t } = useT();
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
      toast.success(t(keys.pagebuilder.trash.restored, { title: page.title }), {
        description: t(keys.pagebuilder.trash.restored_description),
        action: {
          label: t(keys.pagebuilder.trash.open),
          onClick: () => router.visit(`/pagebuilder/${page.id}/edit`),
        },
      });
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <PageShell
      title={t(keys.pagebuilder.trash.title)}
      description={t(keys.pagebuilder.trash.description, { days: RETENTION_DAYS })}
      actions={
        <Button variant="outline" onClick={() => router.visit('/pagebuilder/')}>
          {t(keys.pagebuilder.trash.back)}
        </Button>
      }
    >
      <Head title={t(keys.pagebuilder.trash.title)} />
      {error && <p className="mb-4 text-sm text-destructive">{error}</p>}

      {pages === null ? (
        <div role="status" aria-label={t(keys.pagebuilder.trash.loading)} className="space-y-2">
          <Skeleton className="h-16 w-full" />
          <Skeleton className="h-16 w-full" />
        </div>
      ) : pages.length === 0 ? (
        <div className="rounded-lg border border-dashed p-8 text-center">
          <p className="font-medium">{t(keys.pagebuilder.trash.empty_title)}</p>
          <p className="mt-1 text-sm text-muted-foreground">
            {t(keys.pagebuilder.trash.empty_description, { days: RETENTION_DAYS })}
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
                <p className="truncate font-medium">
                  {page.title || t(keys.pagebuilder.trash.untitled)}
                </p>
                <p className="truncate text-sm text-muted-foreground">
                  /p/{page.slug} · {daysLeft(page.deleted_at)}
                </p>
              </div>

              <Button type="button" size="sm" disabled={busy} onClick={() => void restore(page)}>
                {t(keys.pagebuilder.trash.restore)}
              </Button>

              <ConfirmDialog
                // High: purge is the one operation the trash cannot undo.
                level="high"
                confirmPhrase={page.slug}
                title={t(keys.pagebuilder.trash.purge_title, { title: page.title })}
                description={t(keys.pagebuilder.trash.purge_description)}
                confirmLabel={t(keys.pagebuilder.trash.purge)}
                onConfirm={async () => {
                  await purgePage(page.id);
                  await load();
                  toast.success(t(keys.pagebuilder.trash.purged, { title: page.title }));
                }}
                trigger={
                  <Button type="button" size="sm" variant="ghost" className="text-destructive">
                    {t(keys.pagebuilder.trash.purge)}
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
