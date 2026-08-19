import { Button } from '@simple-module-py/ui/components/ui/button';
import { Input } from '@simple-module-py/ui/components/ui/input';
import { useState } from 'react';

import type { TagRead } from '../../utils/taxonomyApi';

const TAG_INPUT_ID = 'news-tag-find-or-create';
/** At or below this many uses a tag is faded — it is probably a stray spelling
 *  rather than a label anyone is navigating by. */
const RARE_USE_THRESHOLD = 1;

interface Props {
  tags: TagRead[];
  busy: boolean;
  onCreate: (name: string) => Promise<unknown>;
  /** Fold `sourceId` into `targetId`. The source row is removed. */
  onMerge: (targetId: number, sourceId: number) => Promise<unknown>;
}

/** Tags: create by typing, tidy up by merging.
 *
 * There is no rename-in-place here on purpose. Tags are made while writing, so
 * the failure mode is duplicates rather than bad names — "urban" and "Urban
 * trees" both existing is the thing worth fixing, and merge is what fixes it.
 *
 * Selection is capped at two. A merge has a direction (the second selection is
 * folded into the first), and an n-way merge would make that direction
 * impossible to show.
 */
export function TagPanel({ tags, busy, onCreate, onMerge }: Props) {
  const [draft, setDraft] = useState('');
  const [selected, setSelected] = useState<number[]>([]);

  const filtered = draft.trim()
    ? tags.filter((t) => t.name.toLowerCase().includes(draft.trim().toLowerCase()))
    : tags;
  const exact = tags.some((t) => t.name.toLowerCase() === draft.trim().toLowerCase());

  const toggle = (id: number) => {
    setSelected((current) =>
      current.includes(id)
        ? current.filter((x) => x !== id)
        : // Keep the most recent two: selecting a third should move the
          // selection along rather than silently refuse the click.
          [...current, id].slice(-2),
    );
  };

  const merge = async () => {
    const [target, source] = selected;
    try {
      await onMerge(target, source);
      setSelected([]);
    } catch {
      // Surfaced in the page's banner. The selection stays so the merge can be
      // retried without re-picking both chips.
    }
  };

  const targetName = tags.find((t) => t.id === selected[0])?.name;
  const sourceName = tags.find((t) => t.id === selected[1])?.name;

  return (
    <section aria-labelledby="news-tags-heading" className="space-y-3">
      <div>
        <h2 id="news-tags-heading" className="text-sm font-semibold uppercase tracking-wide">
          Tags
        </h2>
        <p className="text-sm text-muted-foreground">
          Freeform, and made while writing. Select two to merge them.
        </p>
      </div>

      <form
        className="flex gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          const name = draft.trim();
          if (!name || busy || exact) return;
          void onCreate(name)
            .then(() => setDraft(''))
            // Surfaced in the page's banner; keep the draft so it can be fixed.
            .catch(() => {});
        }}
      >
        <Input
          id={TAG_INPUT_ID}
          aria-label="Find or create a tag"
          placeholder="Find or create a tag"
          value={draft}
          disabled={busy}
          onChange={(e) => setDraft(e.target.value)}
        />
        <Button type="submit" variant="outline" disabled={busy || !draft.trim() || exact}>
          Create
        </Button>
      </form>

      {selected.length === 2 && (
        <div className="flex items-center justify-between gap-2 rounded-md border bg-muted/40 p-2 text-sm">
          <span>
            Merge <strong>{sourceName}</strong> into <strong>{targetName}</strong>
          </span>
          <Button type="button" size="sm" disabled={busy} onClick={() => void merge()}>
            Merge
          </Button>
        </div>
      )}

      {filtered.length === 0 ? (
        <p className="rounded-md border border-dashed p-4 text-sm text-muted-foreground">
          {draft.trim()
            ? `No tag matches "${draft.trim()}". Create it above.`
            : 'No tags yet. They appear here as writers add them to articles.'}
        </p>
      ) : (
        <ul className="flex flex-wrap gap-2">
          {filtered.map((tag) => {
            const isSelected = selected.includes(tag.id);
            const rare = tag.article_count <= RARE_USE_THRESHOLD;
            return (
              <li key={tag.id}>
                <button
                  type="button"
                  disabled={busy}
                  aria-pressed={isSelected}
                  data-testid="tag-chip"
                  onClick={() => toggle(tag.id)}
                  className={`rounded-full border px-3 py-1 text-sm transition ${
                    isSelected ? 'border-primary bg-primary/10' : 'bg-card hover:bg-muted'
                  } ${rare && !isSelected ? 'opacity-50' : ''}`}
                >
                  {tag.name} <span className="text-muted-foreground">{tag.article_count}</span>
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}
