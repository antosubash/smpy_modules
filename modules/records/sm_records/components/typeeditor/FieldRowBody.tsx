import { useT } from '@simple-module-py/i18n';
import { Checkbox } from '@simple-module-py/ui/components/ui/checkbox';
import { Input } from '@simple-module-py/ui/components/ui/input';
import { Label } from '@simple-module-py/ui/components/ui/label';
import { NativeSelect, NativeSelectOption } from '@simple-module-py/ui/components/ui/native-select';

import type { ValidationError } from '../../utils/types';
import { fieldMessage } from './errors';
import { FieldOptions } from './FieldOptions';
import {
  indexable,
  indexedForced,
  type KeyError,
  keyValid,
  MAX_KEY_LEN,
  MAX_LABEL_LEN,
  uniqueAllowed,
} from './rules';
import { type EditableField, FIELD_TYPES, type FieldTypeName, type TargetType } from './types';

// See `FilterBar.tsx` for why `t` is typed this loosely here: typing it
// against `useT()`'s real, key-union-overloaded signature either blows up
// TS with an "excessively deep" instantiation or fails to unify when called.
// biome-ignore lint/suspicious/noExplicitAny: see comment above
type Translate = (...args: any[]) => string;

function keyErrorMessage(t: Translate, code: KeyError, key: string): string {
  const defaults = {
    required: 'A key is required.',
    reserved: '"{key}" is reserved by the module: it names a column every record already has.',
    pattern:
      'Must start with a lowercase letter, and contain only lowercase letters, numbers and underscores.',
    too_long: 'Must be at most {max} characters.',
    duplicate: 'Another field already uses this key.',
  };
  return t(`records.type_editor.key_error.${code}`, {
    key,
    max: MAX_KEY_LEN,
    defaultValue: defaults[code],
  });
}

/** The field-type select used to show the wire value itself — `longtext`,
 *  `multiselect`, `datetime` (R11). These are the names of the closed set in
 *  `schema/types.py`, written for the person choosing one. A `t()` call per
 *  type rather than a module-scope map, so the strings stay reachable by the
 *  untranslated-string check — a config object is exactly its blind spot. */
function fieldTypeName(t: Translate, type: FieldTypeName): string {
  const defaults: Record<FieldTypeName, string> = {
    text: 'Text',
    longtext: 'Long text',
    number: 'Number',
    integer: 'Whole number',
    boolean: 'Yes / no',
    date: 'Date',
    datetime: 'Date and time',
    select: 'Choice',
    multiselect: 'Several choices',
    email: 'Email address',
    url: 'URL',
    json: 'JSON',
    media: 'Media',
    relation: 'Link to a record',
  };
  return t(`records.type_editor.field_type_name.${type}`, { defaultValue: defaults[type] });
}

/**
 * Everything a field row shows once it is expanded (UX review R9): the
 * constraint detail an admin edits perhaps a tenth as often as they read the
 * schema's shape, which `FieldRowSummary` keeps on screen instead.
 *
 * Split out of `FieldRow` for the 300-line cap, along the seam the collapse
 * already draws: the summary is what the row *is*, this is what it can be
 * changed into.
 */
export function FieldRowBody({
  field,
  index,
  keyLocked,
  siblingKeys,
  targetTypes,
  disabled,
  errors,
  onChange,
  onPatch,
}: {
  field: EditableField;
  index: number;
  keyLocked: boolean;
  siblingKeys: string[];
  targetTypes: TargetType[];
  disabled: boolean;
  errors: ValidationError[];
  /** A raw patch, applied as given (the key and label inputs — neither can
   *  change what `normaliseOnToggle` derives). */
  onChange: (patch: Partial<EditableField>) => void;
  /** A patch re-normalised through `rules.ts::normaliseOnToggle` first. */
  onPatch: (patch: Partial<EditableField>) => void;
}) {
  const { t } = useT();
  const idBase = `field-row-${index}`;
  const keyError = field.key ? keyValid(field.key, siblingKeys) : null;
  const serverKeyError = fieldMessage(errors, field.key);

  return (
    <div id={`${idBase}-body`} className="grid gap-3">
      <div className="grid gap-3 sm:grid-cols-3">
        <div className="grid gap-1.5">
          <Label htmlFor={`${idBase}-key`}>
            {t('records.type_editor.field_key', { defaultValue: 'Key' })}
          </Label>
          <Input
            id={`${idBase}-key`}
            value={field.key}
            maxLength={MAX_KEY_LEN}
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
            onChange={(e) =>
              onPatch({ type: e.target.value, options: {}, constraints: {}, default: null })
            }
          >
            {FIELD_TYPES.map((ft) => (
              <NativeSelectOption key={ft} value={ft}>
                {fieldTypeName(t, ft)}
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
            maxLength={MAX_LABEL_LEN}
            disabled={disabled}
            onChange={(e) => onChange({ label: e.target.value })}
          />
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-x-6 gap-y-2">
        <div className="flex items-center gap-2">
          <Checkbox
            id={`${idBase}-required`}
            checked={field.required}
            disabled={disabled}
            onCheckedChange={(checked) => onPatch({ required: checked === true })}
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
            onCheckedChange={(checked) => onPatch({ unique: checked === true })}
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
            aria-describedby={`${idBase}-indexed-hint`}
            onCheckedChange={(checked) => onPatch({ indexed: checked === true })}
          />
          <Label htmlFor={`${idBase}-indexed`} className="font-normal">
            {t('records.type_editor.field_indexed', { defaultValue: 'Indexed' })}
          </Label>
        </div>
      </div>

      {/* U6: the hint the header once carried was moved off this checkbox
          entirely (R23) and lost its referent in the process — this is that
          consequence, back where the decision is actually made, one field
          at a time. `utils/listing.ts::listColumns` is what makes the last
          clause literally true: only an indexed field can be a list column,
          and only the first four of those show. */}
      <p id={`${idBase}-indexed-hint`} className="-mt-1 text-xs text-muted-foreground">
        {t('records.type_editor.field_indexed_row_hint', {
          defaultValue:
            "Indexed fields can be filtered, sorted and shown as list columns; the first four indexed fields are the list's columns.",
        })}
      </p>

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
        onChange={onPatch}
      />
    </div>
  );
}
