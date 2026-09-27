import { TableHead } from '@simple-module-py/ui/components/ui/table';

import type { SortState } from '../utils/listing';

/**
 * One clickable column header for the record list. `label` is passed in
 * already translated by the caller — this component only draws the active
 * indicator and wires the click, it has no strings of its own to translate.
 *
 * The arrow is `aria-hidden`; screen readers get the sort state from
 * `aria-sort` on the header cell instead, which is the ARIA-correct place
 * for it on a `<th>`.
 */
export function SortableHeader({
  field,
  label,
  sort,
  onSort,
}: {
  field: string;
  label: string;
  sort: SortState;
  onSort: (field: string) => void;
}) {
  const dir = sort?.field === field ? sort.dir : null;
  const ariaSort = dir === 'asc' ? 'ascending' : dir === 'desc' ? 'descending' : 'none';

  return (
    <TableHead aria-sort={ariaSort}>
      <button
        type="button"
        onClick={() => onSort(field)}
        className="inline-flex items-center gap-1 font-medium hover:underline"
      >
        {label}
        <span aria-hidden="true" className="inline-block w-3 text-muted-foreground">
          {dir === 'asc' ? '▲' : dir === 'desc' ? '▼' : ''}
        </span>
      </button>
    </TableHead>
  );
}
