import { useT } from '@simple-module-py/i18n';
import { Button } from '@simple-module-py/ui/components/ui/button';
import { useEffect, useRef, useState } from 'react';

import type { ValidationError } from '../../utils/types';
import { FieldRow } from './FieldRow';
import { newFieldUid } from './formHelpers';
import type { EditableField, TargetType } from './types';

const EMPTY_FIELD: Omit<EditableField, 'key' | 'uid'> = {
  type: 'text',
  label: '',
  required: false,
  unique: false,
  indexed: false,
  default: null,
  help: null,
  constraints: {},
  options: {},
};

function move<T>(list: T[], from: number, to: number): T[] {
  const next = [...list];
  const [item] = next.splice(from, 1);
  next.splice(to, 0, item);
  return next;
}

/**
 * The field list editor. Phase 3 lifts the Phase 1 lock (design §16): a
 * populated type's fields are editable here too, `disabled` only reflects
 * whether a save/preview request is in flight. `originalKeys` is the field
 * keys the type had when this page loaded — the immutable-key rule (§8.7)
 * only bites those; a field added in this session can still have its key
 * fixed before the first save ever sends it.
 *
 * Rows are collapsed by default and keyed by `field.uid` (UX review R9/R10).
 * The keying is the fix for the reorder bug: with `key={index}` React kept
 * the DOM node at position *i* and swapped the content through it, so after
 * "Move up" the focused button belonged to the field that had just been
 * displaced and a second press undid the first. Keyed by identity the node
 * travels with its field, and `focusRefs` then puts focus back on the same
 * row's button where the user left it.
 */
export function FieldList({
  fields,
  originalKeys,
  targetTypes,
  disabled,
  errors,
  onChange,
}: {
  fields: EditableField[];
  originalKeys: ReadonlySet<string>;
  targetTypes: TargetType[];
  disabled: boolean;
  errors: ValidationError[];
  onChange: (next: EditableField[]) => void;
}) {
  const { t } = useT();
  // Expanded rows, by `uid`. A field loaded from the server starts
  // collapsed; one added here starts open, because it is empty and being
  // edited is the only reason it exists yet.
  const [expanded, setExpanded] = useState<ReadonlySet<string>>(new Set());
  const focusRefs = useRef(new Map<string, HTMLButtonElement | null>());
  const refocus = useRef<string | null>(null);
  const fieldsRef = useRef(fields);
  fieldsRef.current = fields;

  // A collapsed row must never be where an error goes to hide: when a new
  // set of errors arrives, every row it names opens. Keyed on `errors` alone
  // (fields come off a ref) so this fires once per refusal rather than
  // re-opening on the next keystroke a row the admin has just closed.
  useEffect(() => {
    if (errors.length === 0) return;
    setExpanded((prev) => {
      const next = new Set(prev);
      for (const field of fieldsRef.current) {
        if (errors.some((e) => e.field === field.key)) next.add(field.uid);
      }
      return next;
    });
  }, [errors]);

  // A move re-renders the list with the row in its new position; focus goes
  // back onto the same field's button afterwards, so a second press moves it
  // a second position instead of the neighbour back.
  useEffect(() => {
    const pending = refocus.current;
    if (!pending) return;
    refocus.current = null;
    focusRefs.current.get(pending)?.focus();
  });

  const setRef = (uid: string, direction: 'up' | 'down') => (node: HTMLButtonElement | null) => {
    focusRefs.current.set(`${uid}:${direction}`, node);
  };

  const moveTo = (index: number, to: number, uid: string, direction: 'up' | 'down') => {
    // A row that reaches an end loses its button to `disabled`, so focus
    // lands on the one that can still move rather than nowhere.
    const stillMovable = direction === 'up' ? to > 0 : to < fields.length - 1;
    refocus.current = `${uid}:${stillMovable ? direction : direction === 'up' ? 'down' : 'up'}`;
    onChange(move(fields, index, to));
  };

  const updateAt = (index: number, patch: Partial<EditableField>) =>
    onChange(fields.map((f, i) => (i === index ? { ...f, ...patch } : f)));
  const removeAt = (index: number) => onChange(fields.filter((_, i) => i !== index));
  const addField = () => {
    const uid = newFieldUid();
    setExpanded((prev) => new Set(prev).add(uid));
    onChange([...fields, { key: '', uid, ...EMPTY_FIELD }]);
  };
  const toggle = (uid: string) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      if (!next.delete(uid)) next.add(uid);
      return next;
    });

  return (
    <div className="grid gap-4">
      {fields.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          {t('records.type_editor.no_fields', { defaultValue: 'No fields yet.' })}
        </p>
      ) : (
        <div className="grid gap-2">
          {fields.map((field, index) => (
            <FieldRow
              key={field.uid}
              field={field}
              index={index}
              total={fields.length}
              expanded={expanded.has(field.uid)}
              keyLocked={originalKeys.has(field.key)}
              siblingKeys={fields.filter((_, i) => i !== index).map((f) => f.key)}
              targetTypes={targetTypes}
              disabled={disabled}
              errors={errors}
              moveUpRef={setRef(field.uid, 'up')}
              moveDownRef={setRef(field.uid, 'down')}
              onToggle={() => toggle(field.uid)}
              onChange={(patch) => updateAt(index, patch)}
              onRemove={() => removeAt(index)}
              onMoveUp={() => moveTo(index, index - 1, field.uid, 'up')}
              onMoveDown={() => moveTo(index, index + 1, field.uid, 'down')}
            />
          ))}
        </div>
      )}

      <div>
        <Button type="button" variant="outline" disabled={disabled} onClick={addField}>
          {t('records.type_editor.add_field', { defaultValue: 'Add field' })}
        </Button>
      </div>
    </div>
  );
}
