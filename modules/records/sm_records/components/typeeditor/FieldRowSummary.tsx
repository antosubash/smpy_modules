import { useT } from '@simple-module-py/i18n';
import { Badge } from '@simple-module-py/ui/components/ui/badge';
import { Button } from '@simple-module-py/ui/components/ui/button';
import { ArrowDownIcon, ArrowUpIcon, ChevronDownIcon, ChevronRightIcon, XIcon } from 'lucide-react';
import type { Ref } from 'react';

import type { EditableField } from './types';

/**
 * The one line a field row collapses to (UX review R9): its key, its type,
 * its flags as badges, and the controls that act on the row as a whole.
 *
 * Move and remove live here rather than in the expanded body on purpose —
 * reordering and deleting are things you do while *reading* the schema, and
 * needing to open a row first would put the 7,000-pixel page back.
 */
export function FieldRowSummary({
  field,
  index,
  total,
  expanded,
  disabled,
  invalid,
  moveUpRef,
  moveDownRef,
  onToggle,
  onRemove,
  onMoveUp,
  onMoveDown,
}: {
  field: EditableField;
  index: number;
  total: number;
  expanded: boolean;
  disabled: boolean;
  /** Whether the row holds an error — shown on the summary so a collapsed
   *  row never hides the reason a save was refused. */
  invalid: boolean;
  moveUpRef: Ref<HTMLButtonElement>;
  moveDownRef: Ref<HTMLButtonElement>;
  onToggle: () => void;
  onRemove: () => void;
  onMoveUp: () => void;
  onMoveDown: () => void;
}) {
  const { t } = useT();
  const unnamed = t('records.type_editor.field_unnamed', { defaultValue: 'New field' });
  const Chevron = expanded ? ChevronDownIcon : ChevronRightIcon;

  return (
    <div className="flex items-center gap-2">
      <button
        type="button"
        className="flex min-w-0 flex-1 items-center gap-2 rounded-md px-1 py-1 text-left hover:bg-muted/60"
        aria-expanded={expanded}
        aria-controls={`field-row-${index}-body`}
        data-testid="records-field-toggle"
        onClick={onToggle}
      >
        <Chevron className="size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
        <span className="truncate font-mono text-sm font-medium" data-testid="records-field-key">
          {field.key || unnamed}
        </span>
        <span className="shrink-0 text-sm text-muted-foreground">{field.type}</span>
        {field.required && (
          <Badge variant="secondary" className="shrink-0 font-normal">
            {t('records.type_editor.field_required', { defaultValue: 'Required' })}
          </Badge>
        )}
        {field.unique && (
          <Badge variant="secondary" className="shrink-0 font-normal">
            {t('records.type_editor.field_unique', { defaultValue: 'Unique' })}
          </Badge>
        )}
        {field.indexed && (
          <Badge variant="secondary" className="shrink-0 font-normal">
            {t('records.type_editor.field_indexed', { defaultValue: 'Indexed' })}
          </Badge>
        )}
        {invalid && (
          <Badge variant="destructive" className="shrink-0 font-normal">
            {t('records.type_editor.field_has_error', { defaultValue: 'Needs attention' })}
          </Badge>
        )}
      </button>

      <div className="flex shrink-0 items-center gap-1">
        <Button
          type="button"
          ref={moveUpRef}
          variant="ghost"
          size="icon"
          disabled={disabled || index === 0}
          aria-label={t('records.type_editor.move_up', { defaultValue: 'Move up' })}
          onClick={onMoveUp}
        >
          <ArrowUpIcon className="size-4" />
        </Button>
        <Button
          type="button"
          ref={moveDownRef}
          variant="ghost"
          size="icon"
          disabled={disabled || index === total - 1}
          aria-label={t('records.type_editor.move_down', { defaultValue: 'Move down' })}
          onClick={onMoveDown}
        >
          <ArrowDownIcon className="size-4" />
        </Button>
        <Button
          type="button"
          variant="ghost"
          size="icon"
          disabled={disabled}
          aria-label={t('records.type_editor.remove_field', { defaultValue: 'Remove field' })}
          onClick={onRemove}
        >
          <XIcon className="size-4" />
        </Button>
      </div>
    </div>
  );
}
