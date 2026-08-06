import { StatusBadge } from '@simple-module-py/pagebuilder/pagebuilder/components/StatusBadge';
import { Button } from '@simple-module-py/ui/components/ui/button';
import { Input } from '@simple-module-py/ui/components/ui/input';
import { useState } from 'react';

import type { ArticleRead } from '../utils/api';

/** `2026-02-01T00:00:00` -> `2026-02-01`, which is what <input type=date> wants. */
function toDateInput(iso: string | null): string {
  return iso ? iso.slice(0, 10) : '';
}

export function ArticleRow({
  article,
  busy,
  suggestionsId,
  onSave,
  onDetach,
}: {
  article: ArticleRead;
  busy: boolean;
  /** id of a <datalist> of existing category names, offered while typing. */
  suggestionsId?: string;
  onSave: (id: number, category: string, publishedAt: string | null) => void;
  onDetach: (id: number) => void;
}) {
  const [category, setCategory] = useState(article.category);
  const [date, setDate] = useState(toDateInput(article.published_at));

  const dirty = category !== article.category || date !== toDateInput(article.published_at);

  return (
    <tr className="border-b last:border-b-0">
      <td className="py-2 pr-4">
        <a href={`/pagebuilder/${article.page_id}`} className="font-medium hover:underline">
          {article.title}
        </a>
        <div className="text-xs text-muted-foreground">{article.url}</div>
      </td>
      <td className="py-2 pr-4">
        <StatusBadge status={article.page_status} />
      </td>
      <td className="py-2 pr-4">
        <Input
          aria-label={`Category for ${article.title}`}
          value={category}
          disabled={busy}
          list={suggestionsId}
          onChange={(e) => setCategory(e.target.value)}
          className="w-40"
        />
      </td>
      <td className="py-2 pr-4">
        <Input
          type="date"
          aria-label={`Date for ${article.title}`}
          value={date}
          disabled={busy}
          onChange={(e) => setDate(e.target.value)}
          className="w-40"
        />
      </td>
      <td className="py-2 text-right whitespace-nowrap">
        <Button
          type="button"
          size="sm"
          // Enabled only when something changed, so the row never fires a
          // no-op PUT that bumps updated_at for nothing.
          disabled={busy || !dirty}
          onClick={() => onSave(article.id, category, date ? `${date}T00:00:00Z` : null)}
        >
          Save
        </Button>
        <Button
          type="button"
          size="sm"
          variant="ghost"
          disabled={busy}
          onClick={() => onDetach(article.id)}
        >
          Detach
        </Button>
      </td>
    </tr>
  );
}
