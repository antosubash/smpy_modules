import { StatusBadge } from '@simple-module-py/pagebuilder/pagebuilder/components/StatusBadge';
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@simple-module-py/ui/components/ui/alert-dialog';
import { Button } from '@simple-module-py/ui/components/ui/button';
import { Input } from '@simple-module-py/ui/components/ui/input';
import { TableCell, TableRow } from '@simple-module-py/ui/components/ui/table';
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
    <TableRow>
      <TableCell>
        <a href={`/pagebuilder/${article.page_id}/edit`} className="font-medium hover:underline">
          {article.title}
        </a>
        <div className="text-xs text-muted-foreground">{article.url}</div>
      </TableCell>
      <TableCell>
        <StatusBadge status={article.page_status} />
      </TableCell>
      <TableCell>
        <Input
          aria-label={`Category for ${article.title}`}
          value={category}
          disabled={busy}
          list={suggestionsId}
          onChange={(e) => setCategory(e.target.value)}
          className="w-40"
        />
      </TableCell>
      <TableCell>
        <Input
          type="date"
          aria-label={`Date for ${article.title}`}
          value={date}
          disabled={busy}
          onChange={(e) => setDate(e.target.value)}
          className="w-40"
        />
      </TableCell>
      <TableCell className="text-right whitespace-nowrap">
        {article.page_status === 'published' && (
          <a
            href={article.url}
            target="_blank"
            rel="noopener noreferrer"
            className="mr-2 text-sm text-primary hover:underline"
          >
            View
          </a>
        )}
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
        <AlertDialog>
          <AlertDialogTrigger asChild>
            <Button type="button" size="sm" variant="ghost" disabled={busy}>
              Detach
            </Button>
          </AlertDialogTrigger>
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>Detach "{article.title}"?</AlertDialogTitle>
              <AlertDialogDescription>
                The page and its body stay. Only the category and date attached to it are removed,
                and it stops appearing in news feeds.
              </AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel>Cancel</AlertDialogCancel>
              <AlertDialogAction onClick={() => onDetach(article.id)}>Detach</AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>
      </TableCell>
    </TableRow>
  );
}
