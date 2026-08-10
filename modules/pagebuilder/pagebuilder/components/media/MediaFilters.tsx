/** Search, content-type, and size filter controls. */

import { Input } from '@simple-module-py/ui/components/ui/input';

import type { ListFilters } from './types';

const CONTENT_TYPE_OPTIONS: { label: string; value: string }[] = [
  { label: 'Any type', value: '' },
  { label: 'JPEG', value: 'image/jpeg' },
  { label: 'PNG', value: 'image/png' },
  { label: 'GIF', value: 'image/gif' },
  { label: 'WebP', value: 'image/webp' },
];

interface Props {
  filters: ListFilters;
  onChange: (update: (previous: ListFilters) => ListFilters) => void;
}

export function MediaFilters({ filters, onChange }: Props) {
  return (
    <div className="flex flex-wrap gap-3 items-end mb-4">
      <div className="flex-1 min-w-[200px]">
        <label htmlFor="media-filter-search" className="mb-1 block text-xs text-muted-foreground">
          Search
        </label>
        <Input
          id="media-filter-search"
          type="search"
          value={filters.search}
          onChange={(e) => onChange((f) => ({ ...f, search: e.target.value }))}
          placeholder="Filename contains…"
          className="w-full"
        />
      </div>
      <div>
        <label htmlFor="media-filter-type" className="mb-1 block text-xs text-muted-foreground">
          Type
        </label>
        <select
          id="media-filter-type"
          value={filters.contentType}
          onChange={(e) => onChange((f) => ({ ...f, contentType: e.target.value }))}
          className="h-9 rounded-md border border-input bg-transparent px-2 text-sm shadow-xs"
        >
          {CONTENT_TYPE_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      </div>
      <div>
        <label htmlFor="media-filter-min-kb" className="mb-1 block text-xs text-muted-foreground">
          Min KB
        </label>
        <Input
          id="media-filter-min-kb"
          type="number"
          inputMode="numeric"
          min={0}
          value={filters.minKB}
          onChange={(e) => onChange((f) => ({ ...f, minKB: e.target.value }))}
          className="w-24"
        />
      </div>
      <div>
        <label htmlFor="media-filter-max-kb" className="mb-1 block text-xs text-muted-foreground">
          Max KB
        </label>
        <Input
          id="media-filter-max-kb"
          type="number"
          inputMode="numeric"
          min={0}
          value={filters.maxKB}
          onChange={(e) => onChange((f) => ({ ...f, maxKB: e.target.value }))}
          className="w-24"
        />
      </div>
    </div>
  );
}
