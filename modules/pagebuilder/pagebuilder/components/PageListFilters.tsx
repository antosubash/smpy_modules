import { FilterPills } from '@simple-module-py/ui/components/FilterPills';
import { Input } from '@simple-module-py/ui/components/ui/input';
import { useEffect, useRef, useState } from 'react';

import { keys, useT } from '../utils/i18n';
import { localeLabel } from '../utils/locale';

export interface PageListFilterState {
  search: string;
  status: string;
  /** Empty means every language, which is the list's default: an editor
   *  looking for a page should not have to guess which translation of it
   *  they are after. */
  locale: string;
  offset: number;
  limit: number;
}

// Labels are catalogue keys, resolved where the pills render — a module-scope
// constant has no hook to call.
const STATUS_OPTIONS = [
  { value: '', label: keys.pagebuilder.filters.status_all },
  { value: 'draft', label: keys.pagebuilder.filters.status_draft },
  { value: 'submitted_for_review', label: keys.pagebuilder.filters.status_review },
  { value: 'published', label: keys.pagebuilder.filters.status_published },
];

const SEARCH_DEBOUNCE_MS = 250;

/**
 * Search box + status pills for the page list.
 *
 * Both write to the query string rather than to component state, so a
 * filtered list is a URL — reloadable, linkable, and steppable with the
 * browser's back button.
 */
export function PageListFilters({
  filters,
  locales = [],
  onChange,
}: {
  filters: PageListFilterState;
  /** Every language the site publishes in. One or none hides the pills — a
   *  filter that cannot narrow anything is furniture. */
  locales?: string[];
  /** Always resets paging: page 3 of the old filter is meaningless. */
  onChange: (next: { search: string; status: string; locale: string }) => void;
}) {
  const { t } = useT();
  const [search, setSearch] = useState(filters.search);

  // The last values this component sent (or accepted from outside). Two jobs:
  // the echo of our own request coming back through props must not clobber
  // newer typing (typing " tag" onto a just-searched "beta" used to lose the
  // trailing keystrokes when the "beta" response landed), and the debounce
  // must send the status we last picked, not a server echo a still-in-flight
  // pill click hasn't updated yet.
  const sent = useRef({
    search: filters.search,
    status: filters.status,
    locale: filters.locale,
  });

  // Keep the box in step when the filter changes from outside it — the back
  // button, or "Clear filters" in the empty state. Our own echo matches
  // `sent` and is skipped.
  useEffect(() => {
    if (filters.search !== sent.current.search) {
      sent.current.search = filters.search;
      setSearch(filters.search);
    }
  }, [filters.search]);
  useEffect(() => {
    if (filters.status !== sent.current.status) {
      sent.current.status = filters.status;
    }
  }, [filters.status]);
  useEffect(() => {
    if (filters.locale !== sent.current.locale) {
      sent.current.locale = filters.locale;
    }
  }, [filters.locale]);

  // The parent redefines `onChange` every render. Held in a ref so the debounce
  // below can depend on the typed value alone: depending on the callback would
  // restart the timer on every unrelated re-render too.
  const latestOnChange = useRef(onChange);
  useEffect(() => {
    latestOnChange.current = onChange;
  });

  useEffect(() => {
    if (search === sent.current.search) return;
    const timer = window.setTimeout(() => {
      // Re-checked at fire time: a pill click may have flushed this exact
      // text already, making the pending request a duplicate.
      if (search === sent.current.search) return;
      sent.current.search = search;
      latestOnChange.current({
        search,
        status: sent.current.status,
        locale: sent.current.locale,
      });
    }, SEARCH_DEBOUNCE_MS);
    return () => window.clearTimeout(timer);
  }, [search]);

  return (
    <div className="mb-4 flex flex-wrap items-center gap-3">
      <Input
        type="search"
        value={search}
        aria-label={t(keys.pagebuilder.filters.search_label)}
        placeholder={t(keys.pagebuilder.filters.search_placeholder)}
        className="h-9 w-64"
        onChange={(e) => setSearch(e.target.value)}
      />
      <FilterPills
        value={filters.status}
        onChange={(status) => {
          // Send the live box text with the pill: the server-echoed
          // `filters.search` may not include text typed inside the debounce
          // window, and sending the stale value would drop it.
          sent.current = { search, status, locale: sent.current.locale };
          onChange({ search, status, locale: sent.current.locale });
        }}
        options={STATUS_OPTIONS.map((option) => ({ ...option, label: t(option.label) }))}
      />
      {locales.length > 1 && (
        <FilterPills
          value={filters.locale}
          onChange={(locale) => {
            sent.current = { search, status: sent.current.status, locale };
            onChange({ search, status: sent.current.status, locale });
          }}
          options={[
            { value: '', label: t(keys.pagebuilder.filters.locale_all) },
            ...locales.map((tag) => ({ value: tag, label: localeLabel(tag) })),
          ]}
        />
      )}
    </div>
  );
}
