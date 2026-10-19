import { Button } from '@simple-module-py/ui/components/ui/button';
import { Input } from '@simple-module-py/ui/components/ui/input';
import { Label } from '@simple-module-py/ui/components/ui/label';
import { Textarea } from '@simple-module-py/ui/components/ui/textarea';
import { XIcon } from 'lucide-react';
import { useState } from 'react';
import { keys, useT } from '../../utils/i18n';

import type { Choice } from './types';

/**
 * Parse a pasted list into choices (UX review R9). One per line; a `|` or a
 * `=` separates the stored value from the label shown, and a line without
 * either is both at once — which is what a column copied out of a
 * spreadsheet looks like, and the reason the bulk box exists at all.
 */
export function parseChoiceList(text: string): Choice[] {
  const out: Choice[] = [];
  for (const raw of text.split('\n')) {
    const line = raw.trim();
    if (!line) continue;
    const at = line.search(/[|=]/);
    const value = (at === -1 ? line : line.slice(0, at)).trim();
    const label = (at === -1 ? line : line.slice(at + 1)).trim();
    if (!value) continue;
    out.push({ value, label: label || value });
  }
  return out;
}

/** `select`/`multiselect`'s `options.choices` — mirrors
 *  `schema/fields.py::_validate_choices`: each choice needs a non-empty
 *  `value` and `label`, and `value`s must be unique within the field. Both
 *  are checked server-side on save; this editor does not duplicate that
 *  check, since an incomplete row mid-edit (a value typed, no label yet) is
 *  a normal state to be in and should not be flagged as an error.
 *
 *  A field that already has choices opens collapsed to "N choices" (R9): 50
 *  editable rows inline was most of what made an eight-field type a
 *  7,000-pixel page. */
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
  // Read once, on mount: a field being given its first choice here should
  // not snap shut again the moment the list stops being empty.
  const [open, setOpen] = useState(choices.length === 0);
  const [bulk, setBulk] = useState<string | null>(null);

  const update = (index: number, patch: Partial<Choice>) => {
    onChange(choices.map((c, i) => (i === index ? { ...c, ...patch } : c)));
  };
  const remove = (index: number) => onChange(choices.filter((_, i) => i !== index));
  const add = () => onChange([...choices, { value: '', label: '' }]);
  const applyBulk = () => {
    const parsed = parseChoiceList(bulk ?? '');
    if (parsed.length > 0) onChange([...choices, ...parsed]);
    setBulk(null);
  };

  return (
    <div className="grid gap-2">
      <div className="flex items-center justify-between gap-2">
        <Label>{t(keys.records.type_editor.choices)}</Label>
        <div className="flex items-center gap-1">
          <span className="text-sm text-muted-foreground" data-testid="records-choices-count">
            {t(keys.records.type_editor.choice_count, {
              count: choices.length,
            })}
          </span>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            data-testid="records-choices-toggle"
            aria-expanded={open}
            onClick={() => setOpen((prev) => !prev)}
          >
            {open
              ? t(keys.records.type_editor.choices_hide)
              : t(keys.records.type_editor.choices_show)}
          </Button>
        </div>
      </div>

      {open && (
        <>
          {choices.map((choice, index) => (
            // biome-ignore lint/suspicious/noArrayIndexKey: a choice has no field of its own that could stand in for identity; reordering isn't supported here, only add/remove.
            <div key={`${fieldKey}-choice-${index}`} className="flex items-center gap-2">
              <Input
                aria-label={t(keys.records.type_editor.choice_value)}
                placeholder={t(keys.records.type_editor.choice_value)}
                value={choice.value}
                disabled={disabled}
                onChange={(e) => update(index, { value: e.target.value })}
              />
              <Input
                aria-label={t(keys.records.type_editor.choice_label)}
                placeholder={t(keys.records.type_editor.choice_label)}
                value={choice.label}
                disabled={disabled}
                onChange={(e) => update(index, { label: e.target.value })}
              />
              <Button
                type="button"
                variant="ghost"
                size="icon"
                disabled={disabled}
                aria-label={t(keys.records.type_editor.remove_choice)}
                onClick={() => remove(index)}
              >
                <XIcon className="size-4" />
              </Button>
            </div>
          ))}

          {bulk !== null && (
            <div className="grid gap-2">
              <Textarea
                rows={5}
                value={bulk}
                disabled={disabled}
                data-testid="records-choices-bulk"
                aria-label={t(keys.records.type_editor.choices_paste_label)}
                placeholder={t(keys.records.type_editor.choices_paste_placeholder)}
                onChange={(e) => setBulk(e.target.value)}
              />
              <p className="text-xs text-muted-foreground">
                {t(keys.records.type_editor.choices_paste_help)}
              </p>
              <div className="flex gap-2">
                <Button type="button" size="sm" disabled={disabled} onClick={applyBulk}>
                  {t(keys.records.type_editor.choices_paste_add)}
                </Button>
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  disabled={disabled}
                  onClick={() => setBulk(null)}
                >
                  {t(keys.records.editor.cancel)}
                </Button>
              </div>
            </div>
          )}

          <div className="flex gap-2">
            <Button type="button" variant="outline" size="sm" disabled={disabled} onClick={add}>
              {t(keys.records.type_editor.add_choice)}
            </Button>
            {bulk === null && (
              <Button
                type="button"
                variant="outline"
                size="sm"
                disabled={disabled}
                data-testid="records-choices-paste"
                onClick={() => setBulk('')}
              >
                {t(keys.records.type_editor.choices_paste)}
              </Button>
            )}
          </div>
        </>
      )}
    </div>
  );
}
