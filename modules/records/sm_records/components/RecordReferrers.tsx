import { Link } from '@inertiajs/react';
import { useT } from '@simple-module-py/i18n';
import { Badge } from '@simple-module-py/ui/components/ui/badge';
import { Button } from '@simple-module-py/ui/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@simple-module-py/ui/components/ui/card';
import { useState } from 'react';

import { listReferrers } from '../utils/api-history';
import type { ReferrerRead } from '../utils/types';

const PAGE_SIZE = 20;

// See `RecordList.tsx` for why `t` is typed this loosely here.
// biome-ignore lint/suspicious/noExplicitAny: see comment above
type Translate = (...args: any[]) => string;

function onDeleteLabel(t: Translate, onDelete: string): string {
  switch (onDelete) {
    case 'set_null':
      return t('records.referrers.on_delete.set_null', { defaultValue: 'Set null' });
    case 'cascade':
      return t('records.referrers.on_delete.cascade', { defaultValue: 'Cascade' });
    default:
      return t('records.referrers.on_delete.restrict', { defaultValue: 'Restrict' });
  }
}

/** One row of the panel: the referring record, its type, the field that
 *  points here, and what deleting this record would do to it. */
function ReferrerRow({ item }: { item: ReferrerRead }) {
  const { t } = useT();
  return (
    <li
      data-testid="records-referrer-item"
      className="flex flex-wrap items-center justify-between gap-2 rounded-md border p-3 text-sm"
    >
      <div>
        <p>
          <span className="text-muted-foreground">{item.type_label}</span>{' '}
          <Link
            href={`/admin/records/${item.type_key}/${item.uuid}`}
            className="font-medium hover:underline"
          >
            {item.display_title}
          </Link>
        </p>
        <p className="text-muted-foreground">{item.field_label}</p>
      </div>
      <div className="flex items-center gap-2">
        <Badge variant="outline" data-testid={`records-referrer-on-delete-${item.on_delete}`}>
          {onDeleteLabel(t, item.on_delete)}
        </Badge>
        {item.is_deleted && (
          <Badge variant="secondary" data-testid="records-referrer-trashed">
            {t('records.referrers.trashed', { defaultValue: 'Trashed' })}
          </Badge>
        )}
      </div>
    </li>
  );
}

/**
 * "Referenced by" — collapsed by default behind `referrerCount` (the
 * editor's own view prop, the same distinct-referring-record count
 * `total` uses below — design §9), expanding to `GET .../referrers`, paged.
 *
 * `total` counts every distinct referring record, including ones a
 * `restrict` refusal would name but this caller may not view; `hidden` says
 * how many of those `total` fall in that second group, and `items` — paged
 * over the visible set only — never includes them (§10). The panel reads
 * `hidden` directly for its "not visible to you" note rather than inferring
 * it from a gap between `total` and how much has loaded so far.
 */
export function RecordReferrers({
  typeKey,
  uuid,
  referrerCount,
}: {
  typeKey: string;
  uuid: string;
  referrerCount: number;
}) {
  const { t } = useT();
  const [open, setOpen] = useState(false);
  const [items, setItems] = useState<ReferrerRead[]>([]);
  const [total, setTotal] = useState<number | null>(null);
  const [hidden, setHidden] = useState(0);
  const [page, setPage] = useState(0);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);

  const loadPage = async (nextPage: number) => {
    setLoading(true);
    setLoadError(null);
    try {
      const resp = await listReferrers(typeKey, uuid, { page: nextPage, page_size: PAGE_SIZE });
      setItems((prev) => (nextPage === 1 ? resp.items : [...prev, ...resp.items]));
      setTotal(resp.total);
      setHidden(resp.hidden ?? 0);
      setPage(nextPage);
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  };

  const toggle = () => {
    const next = !open;
    setOpen(next);
    if (next && total === null) void loadPage(1);
  };

  // Pagination runs over the *visible* set only (design §10), so once every
  // page is in, `items.length` reaches `total - hidden` exactly — no need to
  // infer anything from a gap between the two.
  const visibleTotal = total === null ? null : total - hidden;
  const hasMore = visibleTotal !== null && items.length < visibleTotal;

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0">
        <CardTitle>
          {t('records.referrers.title', {
            count: referrerCount,
            defaultValue: 'Referenced by {count} record',
            defaultValue_other: 'Referenced by {count} records',
          })}
        </CardTitle>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={toggle}
          data-testid="records-referrers-toggle"
        >
          {open
            ? t('records.referrers.hide', { defaultValue: 'Collapse' })
            : t('records.referrers.show', { defaultValue: 'Expand' })}
        </Button>
      </CardHeader>
      {open && (
        <CardContent className="space-y-3">
          {loadError && (
            <p className="text-sm text-destructive" role="alert">
              {loadError}
            </p>
          )}
          {total === null && !loadError && (
            <p className="text-sm text-muted-foreground">
              {t('records.type_editor.revisions.loading', { defaultValue: 'Loading…' })}
            </p>
          )}
          {total === 0 && (
            <p className="text-sm text-muted-foreground">
              {t('records.referrers.empty', { defaultValue: 'Nothing references this record.' })}
            </p>
          )}
          {items.length > 0 && (
            <ul className="space-y-2" data-testid="records-referrers-list">
              {items.map((item) => (
                <ReferrerRow key={`${item.type_key}:${item.uuid}:${item.field_key}`} item={item} />
              ))}
            </ul>
          )}
          {hidden > 0 && (
            <p
              className="text-sm text-muted-foreground"
              data-testid="records-referrers-hidden-note"
            >
              {t('records.referrers.hidden_note', {
                defaultValue: 'Some referrers are not visible to you.',
              })}
            </p>
          )}
          {hasMore && (
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={loading}
              onClick={() => void loadPage(page + 1)}
              data-testid="records-referrers-load-more"
            >
              {loading
                ? t('records.editor.saving', { defaultValue: 'Saving…' })
                : t('records.referrers.load_more', { defaultValue: 'Load more' })}
            </Button>
          )}
        </CardContent>
      )}
    </Card>
  );
}
