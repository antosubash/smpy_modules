/**
 * The human name of a field type — `longtext` is "Long text". Shared by the
 * type editor's type select and the record list's column chooser.
 */

import type { Translate } from './translate';

const DEFAULTS: Record<string, string> = {
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

/** The field-type select used to show the wire value itself — `longtext`,
 *  `multiselect`, `datetime` (R11). These are the names of the closed set in
 *  `schema/types.py`, written for the person choosing one; every one is in
 *  the catalog under `records.type_editor.field_type_name.*`. A type this
 *  build does not know reads as its wire value. */
export function fieldTypeName(t: Translate, type: string): string {
  return t(`records.type_editor.field_type_name.${type}`, {
    defaultValue: DEFAULTS[type] ?? type,
  });
}
