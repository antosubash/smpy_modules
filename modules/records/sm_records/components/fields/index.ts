/**
 * The field-type registry: one component per entry of the closed field-type
 * set of design §6.1, behind a map.
 *
 * Mirrors `pagebuilder/components/blockRegistry.ts`. The lookup is *total* —
 * `getFieldComponent` never returns `undefined` — because the `type` string
 * it is given comes out of a Record Type row in the database, and a host can
 * be serving a bundle older than the module that wrote that row. An unknown
 * type renders read-only through `UnknownField` instead of taking the whole
 * editor down with it.
 */

import { BooleanField } from './BooleanField';
import { MultiSelectField, SelectField } from './ChoiceFields';
import { DateField, DateTimeField } from './DateFields';
import type { FieldComponent } from './FieldShell';
import { MediaField } from './MediaField';
import { IntegerField, NumberField } from './NumericFields';
import { RelationField } from './RelationField';
import { JsonValueField, UnknownField } from './StructuredFields';
import { EmailField, LongTextField, TextField, UrlField } from './TextFields';

export type { FieldComponent, FieldComponentProps } from './FieldShell';
export { FieldShell, fieldInputId } from './FieldShell';
export { UnknownField } from './StructuredFields';

export const FIELD_COMPONENTS: Record<string, FieldComponent> = {
  text: TextField,
  longtext: LongTextField,
  number: NumberField,
  integer: IntegerField,
  boolean: BooleanField,
  date: DateField,
  datetime: DateTimeField,
  select: SelectField,
  multiselect: MultiSelectField,
  email: EmailField,
  url: UrlField,
  json: JsonValueField,
  media: MediaField,
  relation: RelationField,
};

export function getFieldComponent(type: string): FieldComponent {
  // `hasOwn`, not `?? UnknownField`: a plain object literal inherits
  // `constructor`, `toString` and friends, and a lookup of one of those names
  // would hand back an inherited function that is not a component at all.
  return Object.hasOwn(FIELD_COMPONENTS, type) ? FIELD_COMPONENTS[type] : UnknownField;
}
