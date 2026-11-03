/**
 * The human name of a field type — `longtext` is "Long text". Shared by the
 * type editor's type select and the record list's column chooser.
 */

import { keys, type Translate } from './i18n';

const NAME_KEYS: Record<string, string> = {
  text: keys.records.type_editor.field_type_name.text,
  longtext: keys.records.type_editor.field_type_name.longtext,
  number: keys.records.type_editor.field_type_name.number,
  integer: keys.records.type_editor.field_type_name.integer,
  boolean: keys.records.type_editor.field_type_name.boolean,
  date: keys.records.type_editor.field_type_name.date,
  datetime: keys.records.type_editor.field_type_name.datetime,
  select: keys.records.type_editor.field_type_name.select,
  multiselect: keys.records.type_editor.field_type_name.multiselect,
  email: keys.records.type_editor.field_type_name.email,
  url: keys.records.type_editor.field_type_name.url,
  json: keys.records.type_editor.field_type_name.json,
  media: keys.records.type_editor.field_type_name.media,
  relation: keys.records.type_editor.field_type_name.relation,
};

/** The field-type select used to show the wire value itself — `longtext`,
 *  `multiselect`, `datetime` (R11). These are the names of the closed set in
 *  `schema/types.py`, written for the person choosing one; every one is in
 *  the catalog under `records.type_editor.field_type_name.*`. A type this
 *  build does not know reads as its wire value. */
export function fieldTypeName(t: Translate, type: string): string {
  const key = NAME_KEYS[type];
  return key ? t(key) : type;
}
