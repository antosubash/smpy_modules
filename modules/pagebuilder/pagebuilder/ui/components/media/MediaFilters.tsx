/** Search, content-type, and size filter controls. */

import { Input } from '@simple-module-py/ui/components/ui/input';

import { keys, useT } from '../../utils/i18n';
import type { ListFilters } from './types';

// Only the first entry is prose; the format names are format names in every
// language, and a catalogue entry for "PNG" is an invitation to mistranslate
// it. Labels are catalogue keys, resolved where the select renders.
const CONTENT_TYPE_OPTIONS: { label: string; value: string }[] = [
  { label: keys.pagebuilder.media_filters.type_any, value: '' },
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
  const { t } = useT();
  return (
    <div className="flex flex-wrap gap-3 items-end mb-4">
      <div className="flex-1 min-w-[200px]">
        <label htmlFor="media-filter-search" className="mb-1 block text-xs text-muted-foreground">
          {t(keys.pagebuilder.media_filters.search)}
        </label>
        <Input
          id="media-filter-search"
          type="search"
          value={filters.search}
          onChange={(e) => onChange((f) => ({ ...f, search: e.target.value }))}
          placeholder={t(keys.pagebuilder.media_filters.search_placeholder)}
          className="w-full"
        />
      </div>
      <div>
        <label htmlFor="media-filter-type" className="mb-1 block text-xs text-muted-foreground">
          {t(keys.pagebuilder.media_filters.type)}
        </label>
        <select
          id="media-filter-type"
          value={filters.contentType}
          onChange={(e) => onChange((f) => ({ ...f, contentType: e.target.value }))}
          className="h-9 rounded-md border border-input bg-transparent px-2 text-sm shadow-xs"
        >
          {CONTENT_TYPE_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {t(o.label)}
            </option>
          ))}
        </select>
      </div>
      <div>
        <label htmlFor="media-filter-min-kb" className="mb-1 block text-xs text-muted-foreground">
          {t(keys.pagebuilder.media_filters.min_kb)}
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
          {t(keys.pagebuilder.media_filters.max_kb)}
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
