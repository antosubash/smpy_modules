/** Search, content-type, and size filter controls. */

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
        <label className="block text-xs text-gray-500 mb-1">Search</label>
        <input
          type="search"
          value={filters.search}
          onChange={(e) => onChange((f) => ({ ...f, search: e.target.value }))}
          placeholder="Filename contains…"
          className="w-full px-3 py-2 border rounded text-sm"
        />
      </div>
      <div>
        <label className="block text-xs text-gray-500 mb-1">Type</label>
        <select
          value={filters.contentType}
          onChange={(e) => onChange((f) => ({ ...f, contentType: e.target.value }))}
          className="px-2 py-2 border rounded text-sm"
        >
          {CONTENT_TYPE_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      </div>
      <div>
        <label className="block text-xs text-gray-500 mb-1">Min KB</label>
        <input
          type="number"
          inputMode="numeric"
          min={0}
          value={filters.minKB}
          onChange={(e) => onChange((f) => ({ ...f, minKB: e.target.value }))}
          className="w-24 px-2 py-2 border rounded text-sm"
        />
      </div>
      <div>
        <label className="block text-xs text-gray-500 mb-1">Max KB</label>
        <input
          type="number"
          inputMode="numeric"
          min={0}
          value={filters.maxKB}
          onChange={(e) => onChange((f) => ({ ...f, maxKB: e.target.value }))}
          className="w-24 px-2 py-2 border rounded text-sm"
        />
      </div>
    </div>
  );
}
