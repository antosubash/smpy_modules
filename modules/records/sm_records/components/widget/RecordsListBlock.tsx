/**
 * `RecordsList` Puck block: the records module's "natural integration" into
 * pagebuilder, deferred by the design doc (§16) with `news`'s
 * `puck-blocks.ts` named as the seam to copy — see this package's own
 * `puck-blocks.ts` for the registration side of that copy.
 *
 * Field wiring is admin-only (`resolveFields`/`resolveData` call the
 * session-gated `GET /api/records/types`) and runs only inside the Puck
 * *editor* — `<Render>` on the public page never calls either, so nothing
 * here reaches an anonymous visitor's session-less request. See
 * `components/widget/types.ts`'s header and `RecordsListRender.tsx`'s for
 * the full shape of that split.
 */

import type { ComponentConfig, CustomField, SelectField } from '@puckeditor/core';
import { listTypes } from '../../utils/api';
import { DEFAULT_PUBLIC_PREFIX } from '../../utils/public-api';
import { choicesOf } from '../../utils/values';
import { FieldsPicker, type FieldsPickerField } from './FieldsPicker';
import { RecordsListRender, type RecordsListRenderProps } from './RecordsListRender';
import type { FieldMetaEntry, RecordsListProps } from './types';

type BlockFields = NonNullable<ComponentConfig<RecordsListProps>['fields']>;

const LAYOUT_OPTIONS = [
  { label: 'List', value: 'list' },
  { label: 'Cards', value: 'cards' },
  { label: 'Table', value: 'table' },
];

/** A `Fields<T>` entry for a prop with no editor UI of its own —
 *  `fieldMeta`/`typeIsPublic` below are written only by `resolveData`.
 *  `visible: false` drops it from the sidebar; the empty fragment — not
 *  `null` — is `NewsFeedRender`'s own trick for the same reason: Puck's
 *  `render` must return an element. */
function hiddenField<Value>(): CustomField<Value> {
  return { type: 'custom', visible: false, render: () => <></> };
}

// `satisfies`, not a type annotation: an annotation would widen each entry
// to the `Field<T>` union immediately, and `resolveFields` below needs the
// concrete literal type of `.fields` (a `CustomField`) to spread it safely —
// spreading a widened union would mix in members (`TextField`, …) that don't
// have a `render` to spread from.
const BASE_FIELDS = {
  typeKey: {
    type: 'select',
    label: 'Record type',
    options: [{ label: '— choose —', value: '' }],
  },
  fields: {
    type: 'custom',
    label: 'Fields to show (beyond the title)',
    render: FieldsPicker,
  },
  filter: {
    type: 'text',
    label: 'Filter (e.g. status:eq:paid — one term, indexed fields only)',
  },
  sort: {
    type: 'text',
    label: 'Sort (e.g. -published_at for newest first)',
  },
  locale: {
    type: 'text',
    label: 'Locale (blank = default content locale)',
  },
  limit: { type: 'number', label: 'How many', min: 1, max: 50 },
  layout: { type: 'select', label: 'Layout', options: LAYOUT_OPTIONS },
  title: { type: 'text', label: 'Heading' },
  emptyText: { type: 'text', label: 'Text shown when there are no records' },
  linkTemplate: {
    type: 'text',
    label: 'Link template ({slug} or {uuid}; blank = no link)',
  },
  apiPrefix: {
    type: 'text',
    label:
      'Public API prefix (advanced — only change if the Records settings screen shows a different one)',
  },
  fieldMeta: hiddenField<FieldMetaEntry[]>(),
  typeIsPublic: hiddenField<boolean | null>(),
} satisfies BlockFields;

/** Every admin-visible type. Not filtered to `is_public` ones: an author
 *  picking a type that isn't (yet) public is exactly the case the "not
 *  public" hint (`RecordsListRender.tsx`) exists to catch, and a filtered
 *  list could never trigger it — the select instead label-annotates each
 *  non-public entry below. */
async function loadTypes() {
  try {
    return (await listTypes()).items;
  } catch {
    // Not logged in, or a network blip mid-edit — same "don't break the
    // editor" rule `blocks/Image.tsx`'s `resolveData` follows.
    return [];
  }
}

export const RecordsListBlock: ComponentConfig<RecordsListProps> = {
  label: 'Records list (live, from a Record Type)',
  fields: BASE_FIELDS,
  defaultProps: {
    typeKey: '',
    // A relation renders as its stored `type:uuid` — the public API never
    // expands (design §10) — which is worth saying once, here, rather than
    // only in this file's comments: an author choosing a relation field in
    // "Fields to show" sees raw identifiers, not a linked title.
    fields: [],
    fieldMeta: [],
    typeIsPublic: null,
    filter: '',
    sort: '',
    locale: '',
    limit: 10,
    layout: 'list',
    title: '',
    emptyText: '',
    linkTemplate: '',
    apiPrefix: DEFAULT_PUBLIC_PREFIX,
  },
  resolveFields: async (data) => {
    const types = await loadTypes();
    const typeOptions = [
      { label: '— choose —', value: '' },
      ...types.map((rtype) => ({
        label: rtype.is_public ? rtype.label : `${rtype.label} (not public)`,
        value: rtype.key,
      })),
    ];
    const selected = types.find((rtype) => rtype.key === data.props.typeKey);
    const availableFields = (selected?.fields ?? []).map((field) => ({
      value: field.key,
      label: field.label,
    }));
    return {
      ...BASE_FIELDS,
      typeKey: { ...BASE_FIELDS.typeKey, options: typeOptions } as SelectField,
      fields: { ...BASE_FIELDS.fields, availableFields } satisfies FieldsPickerField,
    };
  },
  resolveData: async ({ props }, { changed, trigger }) => {
    if (trigger !== 'load' && !changed.typeKey && !changed.fields) {
      return { props };
    }
    if (!props.typeKey) {
      return { props: { ...props, fieldMeta: [], typeIsPublic: null } };
    }
    const types = await loadTypes();
    if (types.length === 0) {
      // Couldn't reach the admin API (see `loadTypes`) — leave whatever was
      // baked in last time rather than wiping it.
      return { props };
    }
    const rtype = types.find((t) => t.key === props.typeKey);
    if (!rtype) {
      return { props: { ...props, fieldMeta: [], typeIsPublic: null } };
    }
    const byKey = new Map(rtype.fields.map((field) => [field.key, field]));
    const fieldMeta: FieldMetaEntry[] = (props.fields ?? []).map((key) => {
      const def = byKey.get(key);
      return def
        ? { key, type: def.type, label: def.label, choices: choicesOf(def) }
        : { key, type: 'text', label: key, choices: [] };
    });
    return { props: { ...props, fieldMeta, typeIsPublic: rtype.is_public } };
  },
  render: RecordsListRender,
};

export type { RecordsListRenderProps };
