/**
 * The wire shape of a type's `public_submissions` config (#101) and the pure
 * helpers the type editor builds on it. Mirrors
 * `sm_records/contracts/public_submissions.py` and
 * `sm_records/public_submissions/spec.py`.
 */

import type { FieldDef } from './types';

export type SubmissionKind = 'form' | 'subscription';

export type PublicSubmissionsConfig = {
  kind: SubmissionKind;
  enabled: boolean;
  public_fields: string[];
  notify_to: string[];
  consent: { required: boolean; text: Record<string, string> };
  double_opt_in: boolean;
  retention_days: number;
  pending_purge_days: number;
};

/** The server's defaults, key for key in its own dump order — so a config
 *  that has just come back from a save compares equal to an unedited draft. */
export function defaultConfig(kind: SubmissionKind): PublicSubmissionsConfig {
  return {
    kind,
    enabled: false,
    public_fields: [],
    notify_to: [],
    consent: { required: false, text: {} },
    double_opt_in: true,
    retention_days: 365,
    pending_purge_days: 30,
  };
}

/** `public_submissions.spec.SUBMITTABLE_TYPES`: what a visitor can fill in. */
export const SUBMITTABLE_TYPES: ReadonlySet<string> = new Set([
  'text',
  'longtext',
  'email',
  'url',
  'number',
  'integer',
  'boolean',
  'date',
  'datetime',
  'select',
  'multiselect',
]);

/** Whether a field is one the server injects and writes (`sm_*`). */
export function isSystemField(field: Pick<FieldDef, 'system'>): boolean {
  return field.system === 'readonly' || field.system === 'internal';
}

/** The fields an admin edits — everything but the system ones. */
export function editableFields<T extends Pick<FieldDef, 'system'>>(fields: T[]): T[] {
  return fields.filter((field) => !isSystemField(field));
}

/** A payload with its `internal` system values (`sm_nonce`) left out — for
 *  showing a revision's snapshot. The stored history is not touched. */
export function withoutInternal(
  data: Record<string, unknown>,
  fields: Pick<FieldDef, 'key' | 'system'>[],
): Record<string, unknown> {
  const hidden = new Set(fields.filter((f) => f.system === 'internal').map((f) => f.key));
  if (hidden.size === 0) return data;
  return Object.fromEntries(Object.entries(data).filter(([key]) => !hidden.has(key)));
}

/** Required ordinary fields with no default that a visitor is not given —
 *  the server refuses to enable a form that leaves one out (design §3.3). */
export function missingRequired(fields: FieldDef[], publicFields: string[]): string[] {
  return editableFields(fields)
    .filter((f) => f.required && (f.default === null || f.default === undefined))
    .filter((f) => !publicFields.includes(f.key))
    .map((f) => f.key);
}

/** Parse the recipients textarea: one address per line or comma. */
export function parseRecipients(text: string): string[] {
  return text
    .split(/[\n,]/)
    .map((part) => part.trim())
    .filter(Boolean);
}

function presetField(
  key: string,
  type: string,
  label: string,
  extra: Partial<FieldDef> = {},
): FieldDef {
  return {
    key,
    type,
    label,
    required: false,
    unique: false,
    indexed: false,
    default: null,
    help: null,
    constraints: {},
    options: {},
    ...extra,
  };
}

const choices = (...values: string[]) => ({
  choices: values.map((value) => ({ value, label: value })),
});

export type Preset = {
  fields: FieldDef[];
  config: PublicSubmissionsConfig;
  displayField: string;
  showInMenu: boolean;
};

/** *New type → From a preset* (design §3.2): plain fields the admin can change
 *  afterwards, plus a config that names them. */
export const PRESETS: Record<SubmissionKind, Preset> = {
  form: {
    fields: [
      presetField('name', 'text', 'Name', { required: true, constraints: { max_length: 200 } }),
      presetField('email', 'email', 'Email', { required: true, indexed: true }),
      presetField('enquiry', 'select', 'Enquiry', { options: choices('general', 'support') }),
      presetField('message', 'longtext', 'Message', {
        required: true,
        constraints: { max_length: 5000 },
      }),
      presetField('triage', 'select', 'Triage', {
        indexed: true,
        default: 'new',
        options: choices('new', 'in_progress', 'done'),
      }),
    ],
    config: {
      ...defaultConfig('form'),
      public_fields: ['name', 'email', 'enquiry', 'message'],
    },
    displayField: 'name',
    showInMenu: true,
  },
  subscription: {
    fields: [],
    config: defaultConfig('subscription'),
    displayField: '',
    showInMenu: true,
  },
};
