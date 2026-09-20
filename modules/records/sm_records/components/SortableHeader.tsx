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
  className,
  ariaLabel,
}: {
  field: string;
  label: string;
  sort: SortState;
  onSort: (field: string) => void;
  className?: string;
  /** Overrides the button's accessible name — for the rare field whose own
   *  label collides with another column's (e.g. a field named "Title" next
   *  to the display-title column), so `getByRole('button', {name})` and a
   *  screen reader can still tell the two apart (UX-12). */
  ariaLabel?: string;
}) {
  const dir = sort?.field === field ? sort.dir : null;
  const ariaSort = dir === 'asc' ? 'ascending' : dir === 'desc' ? 'descending' : 'none';

  return (
    <TableHead className={className} aria-sort={ariaSort}>
      <button
        type="button"
        onClick={() => onSort(field)}
        aria-label={ariaLabel}
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
