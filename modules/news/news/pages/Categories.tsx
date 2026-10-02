import { Head } from '@inertiajs/react';
import { PageShell } from '@simple-module-py/ui/components/PageShell';
import { Button } from '@simple-module-py/ui/components/ui/button';
import { Input } from '@simple-module-py/ui/components/ui/input';
import { Skeleton } from '@simple-module-py/ui/components/ui/skeleton';
import { AuthenticatedLayout } from '@simple-module-py/ui/layouts/AuthenticatedLayout';
import { useCallback, useEffect, useState } from 'react';

import { CategoryDeleteDialog } from '../components/categories/CategoryDeleteDialog';
import { CategoryRow } from '../components/categories/CategoryRow';
import { TagPanel } from '../components/categories/TagPanel';
import { useTaxonomy } from '../hooks/useTaxonomy';
import { keys, useT } from '../utils/i18n';
import { isManaged } from '../utils/taxonomyApi';

/** Categories and tags — the two taxonomies, side by side.
 *
 * They share a screen because they are the same job (deciding how the archive
 * is grouped) done at two different times: categories are administered, tags
 * accumulate. Splitting them would mean visiting two screens to answer one
 * question about how a topic is filed.
 */
export default function Categories() {
  const { t } = useT();
  const {
    categories,
    tags,
    busy,
    error,
    refresh,
    saveCategory,
    addCategory,
    removeCategory,
    persistOrder,
    addTag,
    mergeTags,
  } = useTaxonomy();

  const [draftName, setDraftName] = useState('');
  const [dragIndex, setDragIndex] = useState<number | null>(null);
  /** Categories mid-drag. Held locally so the list follows the pointer without
   *  a round trip; the order is persisted once, on drop. */
  const [order, setOrder] = useState<number[] | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    void refresh(controller.signal);
    return () => controller.abort();
  }, [refresh]);

  const managed = categories.filter(isManaged);
  /** The managed ids in the order currently on screen.
   *
   * Every index handed to `moveTo` has to come from this array. `managed` is
   * frozen for the whole drag — it only changes once the drop persists and the
   * list refetches — so an index taken from it names where a row *started*,
   * not where it is now. Mixing the two spaces silently drops the row next to
   * the wrong neighbour as soon as a drag reverses over a row it crossed.
   */
  const liveOrder = order ?? managed.map((c) => c.id);
  const shown =
    order === null
      ? categories
      : [
          ...order
            .map((id) => managed.find((c) => c.id === id))
            .filter((c): c is NonNullable<typeof c> => !!c),
          ...categories.filter((c) => !isManaged(c)),
        ];

  const onDrop = useCallback(() => {
    if (order === null) return;
    setDragIndex(null);
    void persistOrder(order);
    setOrder(null);
  }, [order, persistOrder]);

  const moveTo = (from: number, to: number) => {
    if (from === to || from < 0 || to < 0) return;
    const next = [...liveOrder];
    const [moved] = next.splice(from, 1);
    next.splice(to, 0, moved);
    setOrder(next);
    setDragIndex(to);
  };

  return (
    <PageShell
      title={t(keys.news.categories.title)}
      description={t(keys.news.categories.description)}
      actions={
        <form
          className="flex gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            const name = draftName.trim();
            if (!name || busy) return;
            void addCategory(name)
              .then(() => setDraftName(''))
              // Already shown in the banner; keep what was typed so a clash
              // can be corrected rather than retyped.
              .catch(() => {});
          }}
        >
          <Input
            aria-label={t(keys.news.categories.new_label)}
            placeholder={t(keys.news.categories.new_placeholder)}
            value={draftName}
            disabled={busy}
            onChange={(e) => setDraftName(e.target.value)}
          />
          <Button type="submit" disabled={busy || !draftName.trim()}>
            {t(keys.news.categories.add)}
          </Button>
        </form>
      }
    >
      <Head title={t(keys.news.categories.title)} />
      {error && <p className="mb-4 text-sm text-destructive">{error}</p>}

      <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_20rem]">
        {/* No heading of its own: PageShell already renders "Categories" as
            the page h1, and a second one only duplicates the accessible name. */}
        <section className="space-y-3">
          {categories.length === 0 ? (
            <div role="status" aria-label={t(keys.news.categories.loading)} className="space-y-2">
              <Skeleton className="h-14 w-full" />
              <Skeleton className="h-14 w-full" />
              <Skeleton className="h-14 w-full" />
            </div>
          ) : (
            <ul className="space-y-2">
              {shown.map((category) => {
                // Live index, not `managed.findIndex` — see `liveOrder`. Stays
                // -1 for the free-text and system rows, which is what keeps
                // them out of the drag.
                const position = isManaged(category) ? liveOrder.indexOf(category.id) : -1;
                return (
                  <CategoryRow
                    key={category.is_system ? 'system' : `${category.id}:${category.name}`}
                    category={category}
                    busy={busy}
                    dragging={dragIndex === position && position >= 0}
                    onSave={saveCategory}
                    onAdopt={addCategory}
                    onDragStart={() => {
                      setOrder(managed.map((c) => c.id));
                      setDragIndex(position);
                    }}
                    onDragOver={(e) => {
                      e.preventDefault();
                      if (dragIndex !== null && position >= 0) moveTo(dragIndex, position);
                    }}
                    onDrop={onDrop}
                    onDragEnd={onDrop}
                    deleteSlot={
                      <CategoryDeleteDialog
                        category={category}
                        all={categories}
                        onConfirm={(reassignTo) => removeCategory(category.id, reassignTo)}
                        trigger={
                          <Button type="button" size="sm" variant="ghost" disabled={busy}>
                            {t(keys.news.categories.delete)}
                          </Button>
                        }
                      />
                    }
                  />
                );
              })}
            </ul>
          )}

          <p className="pt-2 text-sm text-muted-foreground">{t(keys.news.categories.help)}</p>
        </section>

        <TagPanel tags={tags} busy={busy} onCreate={addTag} onMerge={mergeTags} />
      </div>
    </PageShell>
  );
}

Categories.layout = (page: React.ReactNode) => <AuthenticatedLayout>{page}</AuthenticatedLayout>;
