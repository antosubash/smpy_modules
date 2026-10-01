import type { Ref } from 'react';

import type { ValidationError } from '../../utils/types';
import { fieldMessage } from './errors';
import { FieldRowBody } from './FieldRowBody';
import { FieldRowSummary } from './FieldRowSummary';
import { normaliseOnToggle } from './rules';
import type { EditableField, TargetType } from './types';

/** One row of the field list editor. Collapsed (UX review R9) it is the
 *  one-line summary `FieldRowSummary` renders; expanded it also carries
 *  `FieldRowBody` — the field's own inputs and its type-specific
 *  `FieldOptions`. `keyLocked` covers the immutable-key rule (design §8.7)
 *  for a field that already existed when the type was loaded — a field added
 *  in this same editing session has never been saved, so its key is still
 *  free to fix. */
export function FieldRow({
  field,
  index,
  total,
  expanded,
  keyLocked,
  siblingKeys,
  targetTypes,
  disabled,
  errors,
  moveUpRef,
  moveDownRef,
  onToggle,
  onChange,
  onRemove,
  onMoveUp,
  onMoveDown,
}: {
  field: EditableField;
  index: number;
  total: number;
  expanded: boolean;
  keyLocked: boolean;
  siblingKeys: string[];
  targetTypes: TargetType[];
  disabled: boolean;
  errors: ValidationError[];
  moveUpRef: Ref<HTMLButtonElement>;
  moveDownRef: Ref<HTMLButtonElement>;
  onToggle: () => void;
  onChange: (patch: Partial<EditableField>) => void;
  onRemove: () => void;
  onMoveUp: () => void;
  onMoveDown: () => void;
}) {
  /** Every flag change funnels through here so `unique`/`indexed` are
   *  re-derived against whatever `type`/`options.many` end up being —
   *  see `rules.ts::normaliseOnToggle`. */
  const applyPatch = (patch: Partial<EditableField>) => {
    const merged: EditableField = { ...field, ...patch };
    const normalised = normaliseOnToggle({
      type: merged.type,
      options: merged.options,
      required: merged.required,
      unique: merged.unique,
      indexed: merged.indexed,
    });
    onChange({ ...patch, ...normalised });
  };

  return (
    <div
      className="grid gap-3 rounded-lg border p-3"
      data-testid="records-field-row"
      data-field-index={index}
      data-field-expanded={expanded ? 'true' : 'false'}
    >
      <FieldRowSummary
        field={field}
        index={index}
        total={total}
        expanded={expanded}
        disabled={disabled}
        invalid={!!fieldMessage(errors, field.key)}
        moveUpRef={moveUpRef}
        moveDownRef={moveDownRef}
        onToggle={onToggle}
        onRemove={onRemove}
        onMoveUp={onMoveUp}
        onMoveDown={onMoveDown}
      />
      {expanded && (
        <FieldRowBody
          field={field}
          index={index}
          keyLocked={keyLocked}
          siblingKeys={siblingKeys}
          targetTypes={targetTypes}
          disabled={disabled}
          errors={errors}
          onChange={onChange}
          onPatch={applyPatch}
        />
      )}
    </div>
  );
}
