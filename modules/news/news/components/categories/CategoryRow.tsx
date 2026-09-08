import { Badge } from '@simple-module-py/ui/components/ui/badge';
import { Button } from '@simple-module-py/ui/components/ui/button';
import { Input } from '@simple-module-py/ui/components/ui/input';
import { useState } from 'react';

import { keys, useT } from '../../utils/i18n';
import type { CategoryRead } from '../../utils/taxonomyApi';
import { isManaged } from '../../utils/taxonomyApi';

interface Props {
  category: CategoryRead;
  busy: boolean;
  dragging: boolean;
  onSave: (id: number, name: string, slug: string) => void;
  /** The delete control, supplied by the page so each row's dialog owns its
   *  own reassignment state instead of one shared across the list. */
  deleteSlot?: React.ReactNode;
  /** Give a free-text category a row so it can be ordered and re-slugged. */
  onAdopt?: (name: string) => void;
  onDragStart: () => void;
  onDragOver: (e: React.DragEvent) => void;
  onDrop: () => void;
  onDragEnd: () => void;
}

/** One category: name, public filter URL, count, and its row actions.
 *
 * Editing is inline rather than in a dialog. Renaming carries every article in
 * the category with it, so seeing the count next to the field while you type is
 * the whole safety story — a dialog would hide exactly that number.
 */
export function CategoryRow({
  category,
  busy,
  dragging,
  onSave,
  deleteSlot,
  onAdopt,
  onDragStart,
  onDragOver,
  onDrop,
  onDragEnd,
}: Props) {
  const { t } = useT();
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(category.name);
  const [slug, setSlug] = useState(category.slug);

  const managed = isManaged(category);
  const countLabel = t(keys.news.categories.count, { count: category.article_count });

  const startEditing = () => {
    setName(category.name);
    setSlug(category.slug);
    setEditing(true);
  };

  const save = () => {
    if (!name.trim()) return;
    onSave(category.id, name.trim(), slug.trim());
    setEditing(false);
  };

  return (
    <li
      // Only a managed row is draggable: a free-text category has no position
      // to write and the system row is pinned to the bottom by definition.
      draggable={managed && !busy}
      onDragStart={managed ? onDragStart : undefined}
      onDragOver={managed ? onDragOver : undefined}
      onDrop={managed ? onDrop : undefined}
      onDragEnd={managed ? onDragEnd : undefined}
      data-testid="category-row"
      data-category={category.name}
      className={`flex items-start gap-3 rounded-lg border bg-card p-3 ${
        dragging ? 'opacity-50' : ''
      } ${category.is_system ? 'border-dashed' : ''}`}
    >
      <span
        aria-hidden
        title={managed ? t(keys.news.categories.drag) : undefined}
        className={`mt-1 select-none text-muted-foreground ${
          managed ? 'cursor-grab' : 'opacity-30'
        }`}
      >
        ⠿
      </span>

      <div className="min-w-0 flex-1">
        {editing ? (
          <div className="grid gap-2 sm:grid-cols-2">
            <Input
              aria-label={t(keys.news.categories.name_label)}
              value={name}
              autoFocus
              disabled={busy}
              onChange={(e) => setName(e.target.value)}
            />
            <Input
              aria-label={t(keys.news.categories.slug_label)}
              value={slug}
              disabled={busy}
              onChange={(e) => setSlug(e.target.value)}
            />
          </div>
        ) : (
          <>
            <p className="truncate font-medium">{category.name}</p>
            <p className="truncate text-sm text-muted-foreground">
              {category.is_system
                ? t(keys.news.categories.system)
                : `/admin/news/?category=${category.slug}`}
            </p>
          </>
        )}
      </div>

      <Badge variant="secondary" className="mt-0.5 shrink-0">
        {countLabel}
      </Badge>

      <div className="flex shrink-0 gap-1">
        {editing ? (
          <>
            <Button type="button" size="sm" disabled={busy || !name.trim()} onClick={save}>
              {t(keys.news.categories.save)}
            </Button>
            <Button
              type="button"
              size="sm"
              variant="ghost"
              disabled={busy}
              onClick={() => setEditing(false)}
            >
              {t(keys.news.categories.cancel)}
            </Button>
          </>
        ) : (
          <>
            {managed && (
              <Button
                type="button"
                size="sm"
                variant="outline"
                disabled={busy}
                onClick={startEditing}
              >
                {t(keys.news.categories.rename)}
              </Button>
            )}
            {/* A free-text category cannot be ordered or re-slugged until it
                has a row, so the one action offered is to give it one. */}
            {!managed && !category.is_system && onAdopt && (
              <Button
                type="button"
                size="sm"
                variant="outline"
                disabled={busy}
                onClick={() => onAdopt(category.name)}
              >
                {t(keys.news.categories.adopt)}
              </Button>
            )}
            {managed && deleteSlot}
          </>
        )}
      </div>
    </li>
  );
}
