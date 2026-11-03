import { Button } from '@simple-module-py/ui/components/ui/button';

import type { OutlineEntry } from '../../utils/blockOutline';
import { keys, useT } from '../../utils/i18n';

interface Props {
  entries: OutlineEntry[];
  /** Steps the block at `index` one place up (-1) or down (+1). */
  onMove: (index: number, direction: -1 | 1) => void;
  /** Names the list for screen readers — a page has one, the layout has two. */
  label: string;
  disabled?: boolean;
  /** Shown in place of the list when there is nothing in it yet. */
  emptyHint?: string;
}

/**
 * The blocks of one canvas, in order, reorderable without dragging.
 *
 * Up/down buttons rather than a drag handle: this list exists precisely
 * because there is no room to drag, and buttons are also the only version of
 * reordering that a keyboard or a screen reader can reach.
 */
export function BlockOutline({ entries, onMove, label, disabled, emptyHint }: Props) {
  const { t } = useT();
  if (entries.length === 0) {
    return (
      <p className="rounded-md border border-dashed p-4 text-sm text-muted-foreground">
        {emptyHint ?? t(keys.pagebuilder.outline.empty)}
      </p>
    );
  }

  return (
    <ol data-testid="block-outline" aria-label={label} className="space-y-2">
      {entries.map((entry, index) => (
        <li
          key={entry.id}
          data-block-type={entry.type}
          data-position={index}
          className="flex items-center gap-3 rounded-lg border bg-card p-3"
        >
          <span className="w-5 shrink-0 text-right text-xs tabular-nums text-muted-foreground">
            {index + 1}
          </span>
          <span className="min-w-0 flex-1">
            <span className="block truncate text-sm font-medium">{entry.label}</span>
            {entry.summary && (
              <span className="block truncate text-xs text-muted-foreground">{entry.summary}</span>
            )}
          </span>
          <span className="flex shrink-0 items-center gap-1">
            <Button
              type="button"
              size="icon-sm"
              variant="outline"
              disabled={disabled || index === 0}
              aria-label={t(keys.pagebuilder.outline.move_up, { block: entry.label })}
              onClick={() => onMove(index, -1)}
            >
              ↑
            </Button>
            <Button
              type="button"
              size="icon-sm"
              variant="outline"
              disabled={disabled || index === entries.length - 1}
              aria-label={t(keys.pagebuilder.outline.move_down, { block: entry.label })}
              onClick={() => onMove(index, 1)}
            >
              ↓
            </Button>
          </span>
        </li>
      ))}
    </ol>
  );
}
