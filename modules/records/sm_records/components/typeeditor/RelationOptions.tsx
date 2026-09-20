import { useT } from '@simple-module-py/i18n';
import { Label } from '@simple-module-py/ui/components/ui/label';
import { NativeSelect, NativeSelectOption } from '@simple-module-py/ui/components/ui/native-select';
import { Switch } from '@simple-module-py/ui/components/ui/switch';

import { RELATION_ON_DELETE, type RelationOnDelete, type TargetType } from './types';

// See `FilterBar.tsx` for why `t` is typed this loosely here: typing it
// against `useT()`'s real, key-union-overloaded signature either blows up
// TS with an "excessively deep" instantiation or fails to unify when called.
// biome-ignore lint/suspicious/noExplicitAny: see comment above
type Translate = (...args: any[]) => string;

function onDeleteLabel(t: Translate, choice: RelationOnDelete): string {
  const defaults: Record<RelationOnDelete, string> = {
    restrict: 'Restrict (block the delete)',
    set_null: 'Set null',
    cascade: 'Cascade (delete this record too)',
  };
  return t(`records.type_editor.on_delete.${choice}`, { defaultValue: defaults[choice] });
}

/** `relation`'s `options`: which type it points at, whether one record can
 *  hold several, and what happens to it when the target is deleted
 *  (design §9 — `restrict` is the server's default because a cascading
 *  delete across a user-defined graph destroys content nobody asked to
 *  delete). */
export function RelationOptions({
  index,
  targetType,
  many,
  onDelete,
  targetTypes,
  onChange,
  disabled = false,
}: {
  /** The row's position in the field list — see `FieldOptions`'s own
   *  `index` doc comment (L5): deriving these ids from `field.key` collided
   *  across rows sharing an empty or duplicate key. */
  index: number;
  targetType: string;
  many: boolean;
  onDelete: RelationOnDelete;
  targetTypes: TargetType[];
  onChange: (patch: { targetType?: string; many?: boolean; onDelete?: RelationOnDelete }) => void;
  disabled?: boolean;
}) {
  const { t } = useT();
  const targetId = `field-row-${index}-target-type`;
  const manyId = `field-row-${index}-many`;
  const onDeleteId = `field-row-${index}-on-delete`;

  return (
    <div className="grid gap-3 sm:grid-cols-3">
      <div className="grid gap-1.5">
        <Label htmlFor={targetId}>
          {t('records.type_editor.target_type', { defaultValue: 'Target type' })}
        </Label>
        <NativeSelect
          id={targetId}
          value={targetType}
          disabled={disabled}
          onChange={(e) => onChange({ targetType: e.target.value })}
        >
          <NativeSelectOption value="">
            {t('records.type_editor.target_type_pick', { defaultValue: 'Choose a type…' })}
          </NativeSelectOption>
          {targetTypes.map((tt) => (
            <NativeSelectOption key={tt.key} value={tt.key}>
              {tt.label}
            </NativeSelectOption>
          ))}
        </NativeSelect>
      </div>

      <div className="flex items-center gap-2">
        <Switch
          id={manyId}
          checked={many}
          disabled={disabled}
          onCheckedChange={(checked) => onChange({ many: checked === true })}
        />
        <Label htmlFor={manyId} className="font-normal">
          {t('records.type_editor.many', { defaultValue: 'Many (a list of records)' })}
        </Label>
      </div>

      <div className="grid gap-1.5">
        <Label htmlFor={onDeleteId}>
          {t('records.type_editor.on_delete_label', { defaultValue: 'When the target is deleted' })}
        </Label>
        <NativeSelect
          id={onDeleteId}
          value={onDelete}
          disabled={disabled}
          onChange={(e) => onChange({ onDelete: e.target.value as RelationOnDelete })}
        >
          {RELATION_ON_DELETE.map((choice) => (
            <NativeSelectOption key={choice} value={choice}>
              {onDeleteLabel(t, choice)}
            </NativeSelectOption>
          ))}
        </NativeSelect>
      </div>
    </div>
  );
}
