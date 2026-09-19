import { useT } from '@simple-module-py/i18n';
import { Button } from '@simple-module-py/ui/components/ui/button';
import { Input } from '@simple-module-py/ui/components/ui/input';
import { Label } from '@simple-module-py/ui/components/ui/label';
import { XIcon } from 'lucide-react';

import type { Choice } from './types';

/** `select`/`multiselect`'s `options.choices` — mirrors
 *  `schema/fields.py::_validate_choices`: each choice needs a non-empty
 *  `value` and `label`, and `value`s must be unique within the field. Both
 *  are checked server-side on save; this editor does not duplicate that
 *  check, since an incomplete row mid-edit (a value typed, no label yet) is
 *  a normal state to be in and should not be flagged as an error. */
export function ChoicesEditor({
  fieldKey,
  choices,
  onChange,
  disabled = false,
}: {
  fieldKey: string;
  choices: Choice[];
  onChange: (next: Choice[]) => void;
  disabled?: boolean;
}) {
  const { t } = useT();

  const update = (index: number, patch: Partial<Choice>) => {
    onChange(choices.map((c, i) => (i === index ? { ...c, ...patch } : c)));
  };
  const remove = (index: number) => onChange(choices.filter((_, i) => i !== index));
  const add = () => onChange([...choices, { value: '', label: '' }]);

  return (
    <div className="grid gap-2">
      <Label>{t('records.type_editor.choices', { defaultValue: 'Choices' })}</Label>
      {choices.map((choice, index) => (
        // biome-ignore lint/suspicious/noArrayIndexKey: a choice has no field of its own that could stand in for identity; reordering isn't supported here, only add/remove.
        <div key={`${fieldKey}-choice-${index}`} className="flex items-center gap-2">
          <Input
            aria-label={t('records.type_editor.choice_value', { defaultValue: 'Value' })}
            placeholder={t('records.type_editor.choice_value', { defaultValue: 'Value' })}
            value={choice.value}
            disabled={disabled}
            onChange={(e) => update(index, { value: e.target.value })}
          />
          <Input
            aria-label={t('records.type_editor.choice_label', { defaultValue: 'Label' })}
            placeholder={t('records.type_editor.choice_label', { defaultValue: 'Label' })}
            value={choice.label}
            disabled={disabled}
            onChange={(e) => update(index, { label: e.target.value })}
          />
          <Button
            type="button"
            variant="ghost"
            size="icon"
            disabled={disabled}
            aria-label={t('records.type_editor.remove_choice', { defaultValue: 'Remove choice' })}
            onClick={() => remove(index)}
          >
            <XIcon className="size-4" />
          </Button>
        </div>
      ))}
      <Button type="button" variant="outline" size="sm" disabled={disabled} onClick={add}>
        {t('records.type_editor.add_choice', { defaultValue: 'Add choice' })}
      </Button>
    </div>
  );
}
