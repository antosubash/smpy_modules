import { Head, router, usePage } from '@inertiajs/react';
import { PageShell } from '@simple-module-py/ui/components/PageShell';
import { Button } from '@simple-module-py/ui/components/ui/button';
import { Input } from '@simple-module-py/ui/components/ui/input';
import { Label } from '@simple-module-py/ui/components/ui/label';
import { Skeleton } from '@simple-module-py/ui/components/ui/skeleton';
import { AuthenticatedLayout } from '@simple-module-py/ui/layouts/AuthenticatedLayout';
import { useEffect } from 'react';

import { ConfirmDialog } from '../components/ConfirmDialog';
import { MediaUsageList } from '../components/media/MediaUsageList';
import { useMediaDetail } from '../hooks/useMediaDetail';
import { formatBytes } from '../utils/mediaFormat';

const ALT_ID = 'media-alt-text';
const CAPTION_ID = 'media-caption';
const CREDIT_ID = 'media-credit';

/** One asset: what it shows, who to credit, and which pages depend on it.
 *
 * Alt text sits on the asset rather than on each placement because it describes
 * the picture, not the layout — so editing it here fixes every page using the
 * image at once, which is the thing worth saying on the screen.
 */
export default function MediaDetail() {
  const { asset_id } = usePage<{ props: { asset_id: number } }>().props as unknown as {
    asset_id: number;
  };

  const { detail, draft, busy, dirty, error, load, patch, save, remove } = useMediaDetail(asset_id);

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  if (!detail || !draft) {
    // Once the load has failed the header must stop claiming to be loading —
    // an asset id that does not exist is a permanent answer, not a slow one.
    return (
      <PageShell
        title={error ? 'Asset not found' : 'Asset'}
        description={error ? 'It may have been deleted.' : 'Loading…'}
        actions={
          error ? (
            <Button variant="outline" onClick={() => router.visit('/pagebuilder/media')}>
              Media library
            </Button>
          ) : undefined
        }
      >
        <Head title={error ? 'Asset not found' : 'Asset'} />
        {error ? (
          <p className="text-sm text-destructive">{error}</p>
        ) : (
          <Skeleton className="h-64 w-full" />
        )}
      </PageShell>
    );
  }

  const { asset, used_in, used_in_total } = detail;
  const inUse = used_in_total > 0;
  const dimensions = asset.width && asset.height ? `${asset.width}×${asset.height} · ` : '';

  return (
    <PageShell
      title={asset.original_filename}
      description={`${dimensions}${asset.content_type} · ${formatBytes(asset.size_bytes)}`}
      actions={
        <>
          <Button variant="outline" onClick={() => router.visit('/pagebuilder/media')}>
            Media library
          </Button>
          <Button variant="outline" asChild>
            <a href={asset.url} download>
              Download
            </a>
          </Button>
        </>
      }
    >
      <Head title={asset.original_filename} />
      {error && <p className="mb-4 text-sm text-destructive">{error}</p>}

      <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_22rem]">
        <section className="space-y-3">
          <img
            src={asset.url}
            alt={asset.alt_text}
            className="max-h-[26rem] w-full rounded-lg border bg-muted object-contain"
          />
          <p className="break-all font-mono text-xs text-muted-foreground">{asset.url}</p>

          <MediaUsageList usages={used_in} total={used_in_total} />
        </section>

        <aside className="space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold uppercase tracking-wide">Details</h2>
            <span className="text-xs text-muted-foreground" aria-live="polite">
              {busy ? 'Saving…' : dirty ? 'Unsaved changes' : ''}
            </span>
          </div>

          <div className="grid gap-2">
            <Label htmlFor={ALT_ID}>Alt text</Label>
            <Input
              id={ALT_ID}
              value={draft.alt_text}
              disabled={busy}
              placeholder="What the image shows"
              onChange={(e) => patch({ alt_text: e.target.value })}
            />
            <p className="text-xs text-muted-foreground">
              Describes the picture, not the placement — editing it here updates every page using
              this image at once.
            </p>
          </div>

          <div className="grid gap-2">
            <Label htmlFor={CAPTION_ID}>Caption</Label>
            <Input
              id={CAPTION_ID}
              value={draft.caption}
              disabled={busy}
              placeholder="Optional, shown under the image"
              onChange={(e) => patch({ caption: e.target.value })}
            />
          </div>

          <div className="grid gap-2">
            <Label htmlFor={CREDIT_ID}>Credit</Label>
            <Input
              id={CREDIT_ID}
              value={draft.credit}
              disabled={busy}
              placeholder="Photographer or source"
              onChange={(e) => patch({ credit: e.target.value })}
            />
          </div>

          <Button className="w-full" disabled={busy || !dirty} onClick={() => void save()}>
            Save
          </Button>

          {inUse ? (
            <p className="rounded-md border border-dashed p-3 text-xs text-muted-foreground">
              Delete is blocked while this asset is in use. Detach it from the{' '}
              {used_in_total === 1 ? 'page' : `${used_in_total} pages`} above first — deleting it
              anyway would leave them serving a broken image.
            </p>
          ) : (
            <ConfirmDialog
              // Medium, not low: nothing references it so nothing on the site
              // changes, but there is no trash for media — the file is gone for
              // good. `low` promises reversibility this cannot offer.
              level="medium"
              title={`Delete “${asset.original_filename}”?`}
              description="No page references this asset, so nothing on the site changes. The file itself is removed for good."
              confirmLabel="Delete"
              onConfirm={async () => {
                await remove();
                router.visit('/pagebuilder/media');
              }}
              trigger={
                <Button variant="ghost" className="w-full text-destructive" disabled={busy}>
                  Delete asset
                </Button>
              }
            />
          )}
        </aside>
      </div>
    </PageShell>
  );
}

MediaDetail.layout = (page: React.ReactNode) => <AuthenticatedLayout>{page}</AuthenticatedLayout>;
