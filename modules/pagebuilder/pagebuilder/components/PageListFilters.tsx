import { FilterPills } from '@simple-module-py/ui/components/FilterPills';
import { Input } from '@simple-module-py/ui/components/ui/input';
import { useEffect, useRef, useState } from 'react';

export interface PageListFilterState {
  search: string;
  status: string;
  offset: number;
  limit: number;
}

const STATUS_OPTIONS = [
  { value: '', label: 'All' },
  { value: 'draft', label: 'Drafts' },
  { value: 'submitted_for_review', label: 'In review' },
  { value: 'published', label: 'Published' },
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
  onChange,
}: {
  filters: PageListFilterState;
  /** Always resets paging: page 3 of the old filter is meaningless. */
  onChange: (next: { search?: string; status?: string }) => void;
}) {
  const [search, setSearch] = useState(filters.search);

  // Keep the box in step when the filter changes from outside it — the back
  // button, or "Clear filters" in the empty state.
  useEffect(() => setSearch(filters.search), [filters.search]);

  // The parent redefines `onChange` every render. Held in a ref so the debounce
  // below can depend on the typed value alone: depending on the callback would
  // restart the timer on every unrelated re-render too.
  const latestOnChange = useRef(onChange);
  useEffect(() => {
    latestOnChange.current = onChange;
  });

  useEffect(() => {
    if (search === filters.search) return;
    const timer = window.setTimeout(() => latestOnChange.current({ search }), SEARCH_DEBOUNCE_MS);
    return () => window.clearTimeout(timer);
  }, [search, filters.search]);

  return (
    <div className="mb-4 flex flex-wrap items-center gap-3">
      <Input
        type="search"
        value={search}
        aria-label="Search pages"
        placeholder="Search title or slug…"
        className="h-9 w-64"
        onChange={(e) => setSearch(e.target.value)}
      />
      <FilterPills
        value={filters.status}
        onChange={(status) => onChange({ status })}
        options={STATUS_OPTIONS}
      />
    </div>
  );
}
