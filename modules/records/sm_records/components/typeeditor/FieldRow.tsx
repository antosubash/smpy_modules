import { useT } from '@simple-module-py/i18n';
import { Button } from '@simple-module-py/ui/components/ui/button';
import { Checkbox } from '@simple-module-py/ui/components/ui/checkbox';
import { Input } from '@simple-module-py/ui/components/ui/input';
import { Label } from '@simple-module-py/ui/components/ui/label';
import { NativeSelect, NativeSelectOption } from '@simple-module-py/ui/components/ui/native-select';
import { ArrowDownIcon, ArrowUpIcon, XIcon } from 'lucide-react';

import type { ValidationError } from '../../utils/types';
import { fieldMessage } from './errors';
import { FieldOptions } from './FieldOptions';
import { indexable, indexedForced, keyValid, normaliseOnToggle, uniqueAllowed } from './rules';
import { type EditableField, FIELD_TYPES, type TargetType } from './types';

// See `FilterBar.tsx` for why `t` is typed this loosely here: typing it
// against `useT()`'s real, key-union-overloaded signature either blows up
// TS with an "excessively deep" instantiation or fails to unify when called.
// biome-ignore lint/suspicious/noExplicitAny: see comment above
type Translate = (...args: any[]) => string;

function keyErrorMessage(
  t: Translate,
  code: 'required' | 'reserved' | 'pattern' | 'duplicate',
  key: string,
): string {
  const defaults = {
    required: 'A key is required.',
    reserved: '"{key}" is reserved by the module: it names a column every record already has.',
    pattern:
      'Must start with a lowercase letter, and contain only lowercase letters, numbers and underscores.',
    duplicate: 'Another field already uses this key.',
  };
  return t(`records.type_editor.key_error.${code}`, { key, defaultValue: defaults[code] });
}

/** One row of the field list editor: the field's own inputs (key/type/label,
 *  required/unique/indexed, help) plus its type-specific `FieldOptions`.
 *  `keyLocked` covers the immutable-key rule (design §8.7) for a field that
 *  already existed when the type was loaded — a field added in this same
 *  editing session has never been saved, so its key is still free to fix. */
export function FieldRow({
  field,
  index,
  total,
  keyLocked,
  siblingKeys,
  targetTypes,
  disabled,
  errors,
  onChange,
  onRemove,
  onMoveUp,
  onMoveDown,
}: {
  field: EditableField;
  index: number;
  total: number;
  keyLocked: boolean;
  siblingKeys: string[];
  targetTypes: TargetType[];
  disabled: boolean;
  errors: ValidationError[];
  onChange: (patch: Partial<EditableField>) => void;
  onRemove: () => void;
  onMoveUp: () => void;
  onMoveDown: () => void;
}) {
  const { t } = useT();
  const idBase = `field-row-${index}`;
  const keyError = field.key ? keyValid(field.key, siblingKeys) : null;
  const serverKeyError = fieldMessage(errors, field.key);

  /** Every field change funnels through here so `unique`/`indexed` are
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

  const handleTypeChange = (nextType: string) => {
    applyPatch({ type: nextType, options: {}, constraints: {}, default: null });
  };

  return (
    <div
      className="grid gap-3 rounded-lg border p-4"
      data-testid="records-field-row"
      data-field-index={index}
    >
      <div className="grid gap-3 sm:grid-cols-[1fr_1fr_1fr_auto]">
        <div className="grid gap-1.5">
          <Label htmlFor={`${idBase}-key`}>
            {t('records.type_editor.field_key', { defaultValue: 'Key' })}
          </Label>
          <Input
            id={`${idBase}-key`}
            value={field.key}
            disabled={disabled || keyLocked}
            readOnly={keyLocked}
            onChange={(e) => onChange({ key: e.target.value })}
            aria-invalid={!!keyError || !!serverKeyError}
          />
          {keyLocked && (
            <p className="text-xs text-muted-foreground">
              {t('records.type_editor.field_key_locked', {
                defaultValue: "Can't be changed after the field is created.",
              })}
            </p>
          )}
          {keyError && (
            <p className="text-sm text-destructive">{keyErrorMessage(t, keyError, field.key)}</p>
          )}
          {!keyError && serverKeyError && (
            <p className="text-sm text-destructive">{serverKeyError}</p>
          )}
        </div>

        <div className="grid gap-1.5">
          <Label htmlFor={`${idBase}-type`}>
            {t('records.type_editor.field_type', { defaultValue: 'Type' })}
          </Label>
          <NativeSelect
            id={`${idBase}-type`}
            value={field.type}
            disabled={disabled}
            onChange={(e) => handleTypeChange(e.target.value)}
          >
            {FIELD_TYPES.map((ft) => (
              <NativeSelectOption key={ft} value={ft}>
                {ft}
              </NativeSelectOption>
            ))}
          </NativeSelect>
        </div>

        <div className="grid gap-1.5">
          <Label htmlFor={`${idBase}-label`}>
            {t('records.types.label', { defaultValue: 'Label' })}
          </Label>
          <Input
            id={`${idBase}-label`}
            value={field.label}
            disabled={disabled}
            onChange={(e) => onChange({ label: e.target.value })}
          />
        </div>

        <div className="flex items-end gap-1">
          <Button
            type="button"
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

      <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
        <div className="flex items-center gap-2">
          <Checkbox
            id={`${idBase}-required`}
            checked={field.required}
            disabled={disabled}
            onCheckedChange={(checked) => applyPatch({ required: checked === true })}
          />
          <Label htmlFor={`${idBase}-required`} className="font-normal">
            {t('records.type_editor.field_required', { defaultValue: 'Required' })}
          </Label>
        </div>
        <div className="flex items-center gap-2">
          <Checkbox
            id={`${idBase}-unique`}
            checked={field.unique}
            disabled={disabled || !uniqueAllowed(field)}
            onCheckedChange={(checked) => applyPatch({ unique: checked === true })}
          />
          <Label htmlFor={`${idBase}-unique`} className="font-normal">
            {t('records.type_editor.field_unique', { defaultValue: 'Unique' })}
          </Label>
        </div>
        <div className="flex items-center gap-2">
          <Checkbox
            id={`${idBase}-indexed`}
            checked={field.indexed}
            // Same treatment `unique` gets above: when the server normalises
            // the flag on (a `unique` field, or any `relation` — see
            // `rules.ts::indexedForced`) the box is checked and locked,
            // rather than accepting a click that snaps straight back.
            disabled={disabled || !indexable(field.type) || indexedForced(field)}
            onCheckedChange={(checked) => applyPatch({ indexed: checked === true })}
          />
          <Label htmlFor={`${idBase}-indexed`} className="font-normal">
            {t('records.type_editor.field_indexed', { defaultValue: 'Indexed' })}
          </Label>
        </div>
        <p className="w-full text-xs text-muted-foreground sm:w-auto">
          {t('records.type_editor.field_indexed_hint', {
            defaultValue:
              'The single most consequential choice on this screen: filterable and sortable, at the cost of a write per save.',
          })}
        </p>
      </div>

      <div className="grid gap-1.5">
        <Label htmlFor={`${idBase}-help`}>
          {t('records.type_editor.field_help', { defaultValue: 'Help text' })}
        </Label>
        <Input
          id={`${idBase}-help`}
          value={field.help ?? ''}
          disabled={disabled}
          onChange={(e) => onChange({ help: e.target.value || null })}
        />
      </div>

      <FieldOptions
        field={field}
        index={index}
        targetTypes={targetTypes}
        disabled={disabled}
        onChange={applyPatch}
      />
    </div>
  );
}
