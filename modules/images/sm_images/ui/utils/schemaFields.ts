/**
 * The field editor's model of a prompt's output schema, and the way back.
 *
 * **Lossless or not at all.** The portal's builder kept only a field's name,
 * type, description and required flag, so saving a preset's schema silently
 * dropped its `enum`s, bounds and nesting. Here {@link schemaToFields} answers
 * `null` for any schema the fields cannot express exactly - checked by
 * building it back and comparing - and the editor then edits the JSON itself.
 */

import { keys } from './i18n';
import type { JsonSchema } from './types-prompts';

export type FieldType = 'string' | 'integer' | 'number' | 'boolean' | 'string_list';

export const FIELD_TYPES: FieldType[] = ['string', 'integer', 'number', 'boolean', 'string_list'];

export type SchemaField = {
  name: string;
  type: FieldType;
  description: string;
  required: boolean;
  /** Allowed values; text fields and lists of text only. Empty = any; blank
   *  entries (mid-typing) are ignored. */
  choices: string[];
};

/** Names an object's prototype answers to: refused as field names, so no
 *  schema built here (or read back) can reach `Object.prototype`. */
const RESERVED = new Set(['__proto__', 'constructor', 'prototype']);

/** The catalogue key of what is wrong with a field name, or `null`. */
export function fieldNameError(name: string): string | null {
  return RESERVED.has(name.trim()) ? keys.images.prompts.schema.reserved_name : null;
}

/** The trimmed names more than one field uses: a JSON object keeps one of
 *  each, so saving them would silently drop the others. */
export function duplicateNames(fields: SchemaField[]): Set<string> {
  const seen = new Set<string>();
  const twice = new Set<string>();
  for (const field of fields) {
    const name = field.name.trim();
    if (!name) continue;
    if (seen.has(name)) twice.add(name);
    seen.add(name);
  }
  return twice;
}

export function emptyField(): SchemaField {
  return { name: '', type: 'string', description: '', required: false, choices: [] };
}

function definition(field: SchemaField): JsonSchema {
  const listed = field.choices.map((c) => c.trim()).filter(Boolean);
  const choices = field.type === 'string' || field.type === 'string_list' ? listed : [];
  let out: JsonSchema;
  if (field.type === 'string_list') {
    out = {
      type: 'array',
      items: choices.length ? { type: 'string', enum: choices } : { type: 'string' },
    };
  } else {
    out = { type: field.type, ...(choices.length ? { enum: choices } : {}) };
  }
  const description = field.description.trim();
  return description ? { ...out, description } : out;
}

/** The JSON Schema of `fields`; a field with no name, or a reserved one
 *  ({@link fieldNameError}), is left out. `properties` has no prototype. */
export function buildJsonSchema(fields: SchemaField[]): JsonSchema {
  const properties: Record<string, JsonSchema> = Object.create(null);
  const required: string[] = [];
  for (const field of fields) {
    const name = field.name.trim();
    if (!name || fieldNameError(name)) continue;
    properties[name] = definition(field);
    if (field.required) required.push(name);
  }
  return required.length
    ? { type: 'object', properties, required }
    : { type: 'object', properties };
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function strings(value: unknown): string[] | null {
  return Array.isArray(value) && value.every((v) => typeof v === 'string') ? value : null;
}

function fieldOf(name: string, def: unknown, required: boolean): SchemaField | null {
  if (!isRecord(def)) return null;
  const description = typeof def.description === 'string' ? def.description : '';
  const base = { name, description, required };
  if (def.type === 'array') {
    const items = def.items;
    if (!isRecord(items) || items.type !== 'string') return null;
    return { ...base, type: 'string_list', choices: strings(items.enum) ?? [] };
  }
  if (typeof def.type !== 'string' || !FIELD_TYPES.includes(def.type as FieldType)) return null;
  return { ...base, type: def.type as FieldType, choices: strings(def.enum) ?? [] };
}

/** Canonical JSON (sorted keys), so two schemas compare by meaning, not order. */
function canonical(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonical).join(',')}]`;
  if (isRecord(value)) {
    const entries = Object.keys(value)
      .sort()
      .map((k) => `${JSON.stringify(k)}:${canonical(value[k])}`);
    return `{${entries.join(',')}}`;
  }
  return JSON.stringify(value);
}

/** The fields of `schema`, or `null` when they would not build it back exactly. */
export function schemaToFields(schema: JsonSchema | null | undefined): SchemaField[] | null {
  if (!isRecord(schema) || schema.type !== 'object') return null;
  const properties = schema.properties ?? {};
  const required = schema.required === undefined ? [] : strings(schema.required);
  if (!isRecord(properties) || required === null) return null;
  const fields: SchemaField[] = [];
  for (const [name, def] of Object.entries(properties)) {
    if (fieldNameError(name)) return null;
    const field = fieldOf(name, def, required.includes(name));
    if (field === null) return null;
    fields.push(field);
  }
  return canonical(buildJsonSchema(fields)) === canonical(schema) ? fields : null;
}
