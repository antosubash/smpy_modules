import { Button } from '@simple-module-py/ui/components/ui/button';
import { Input } from '@simple-module-py/ui/components/ui/input';
import { Label } from '@simple-module-py/ui/components/ui/label';
import { NativeSelect, NativeSelectOption } from '@simple-module-py/ui/components/ui/native-select';
import { Search } from 'lucide-react';
import { useEffect, useState } from 'react';
import { STATUSES, statusLabel } from '../utils/format';
import { keys, useT } from '../utils/i18n';
import type { SubjectMode } from '../utils/types';

export interface SubscriptionsFilterValues {
  status: string;
  q: string;
}

interface Props {
  status: string;
  search: string;
  /** Rows on this page, and the most the server sends: equal means the list was cut. */
  rowCount: number;
  rowLimit: number;
  subjectMode?: SubjectMode;
  onChange: (next: SubscriptionsFilterValues) => void;
}

/**
 * The status filter and the search (organisation name or slug; a user's email
 * or id in user mode), plus a notice when the list stops at the row limit.
 */
export function SubscriptionsFilters({
  status,
  search,
  rowCount,
  rowLimit,
  subjectMode = 'tenant',
  onChange,
}: Props) {
  const { t } = useT();
  const c = keys.billing.subscriptions;
  const byUser = subjectMode === 'user';
  const [draft, setDraft] = useState(search);
  useEffect(() => setDraft(search), [search]);

  return (
    <div className="mb-4 space-y-2">
      <form
        className="flex flex-wrap items-end gap-3"
        onSubmit={(event) => {
          event.preventDefault();
          onChange({ status, q: draft.trim() });
        }}
      >
        <div className="space-y-1.5">
          <Label htmlFor="status-filter">{t(c.status)}</Label>
          <NativeSelect
            id="status-filter"
            value={status}
            onChange={(e) => onChange({ status: e.target.value, q: search })}
          >
            <NativeSelectOption value="">{t(c.all)}</NativeSelectOption>
            {STATUSES.map((s) => (
              <NativeSelectOption key={s} value={s}>
                {statusLabel(s)}
              </NativeSelectOption>
            ))}
          </NativeSelect>
        </div>
        <div className="min-w-48 flex-1 space-y-1.5 sm:max-w-xs">
          <Label htmlFor="subscriptions-search">{t(byUser ? c.search_user : c.search)}</Label>
          <div className="flex gap-2">
            <Input
              id="subscriptions-search"
              type="search"
              maxLength={120}
              placeholder={t(byUser ? c.search_placeholder_user : c.search_placeholder)}
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
            />
            <Button type="submit" variant="outline" size="icon" aria-label={t(c.search_submit)}>
              <Search aria-hidden="true" />
            </Button>
          </div>
        </div>
      </form>
      {rowCount >= rowLimit && (
        <p className="text-sm text-muted-foreground" data-testid="subscriptions-limit">
          {t(c.limit_notice, { count: rowLimit })}
        </p>
      )}
    </div>
  );
}
