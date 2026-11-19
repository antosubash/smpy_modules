/** Resolve a block's catalogue keys to text, through nested fields.
 *
 *  Pagebuilder's `localizeConfig` resolves a block's *static* fields when the editor mounts Puck.
 *  The fields a block builds in `resolveFields` (the calendar and category selects, filled once the
 *  anonymous route answers) are made after that, so events resolves them itself, with the same
 *  reach: every `label`, every `options[].label`, and into `arrayFields` and `objectFields`.
 *
 *  `mapValues` and `localizeField` are parity copies of pagebuilder's `localizeConfig.ts`
 *  (`scripts/tests/parity_families.py`): pagebuilder exporting them is #423, and until then the two
 *  stay identical. A label that is already text (a calendar's name) is not a key, and the
 *  translator hands an unknown key back as it came. A pure deep copy. */

import type { Translate } from '../utils/i18n';

interface LabelledOption {
  label?: string;
}

interface LabelledField {
  label?: string;
  options?: LabelledOption[];
  arrayFields?: Record<string, LabelledField>;
  objectFields?: Record<string, LabelledField>;
}

function mapValues<V, R>(
  source: Record<string, V> | undefined,
  fn: (value: V) => R,
): Record<string, R> | undefined {
  if (!source) return source;
  const out: Record<string, R> = {};
  for (const [name, value] of Object.entries(source)) out[name] = fn(value);
  return out;
}

function localizeField(field: LabelledField, t: Translate): LabelledField {
  // A `custom` field has no label of its own — it renders its own
  // `FieldLabel`, and translates there.
  const next: LabelledField = { ...field };
  if (field.label) next.label = t(field.label);
  if (field.options) {
    next.options = field.options.map((option) =>
      option.label ? { ...option, label: t(option.label) } : option,
    );
  }
  // An `array` or `object` field carries a second level of labels, which the
  // editor shows once a row is expanded. Missing them left half of every
  // repeater's chrome untranslated.
  if (field.arrayFields) {
    next.arrayFields = mapValues(field.arrayFields, (inner) => localizeField(inner, t));
  }
  if (field.objectFields) {
    next.objectFields = mapValues(field.objectFields, (inner) => localizeField(inner, t));
  }
  return next;
}

export function localizeFields<F extends object>(fields: F, t: Translate): F {
  return mapValues(fields as Record<string, LabelledField>, (field) =>
    localizeField(field, t),
  ) as unknown as F;
}
