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
import { t } from '@simple-module-py/i18n';
import { listTypes } from '../../utils/api';
import { DEFAULT_PUBLIC_PREFIX } from '../../utils/public-api';
import type { Translate } from '../../utils/translate';
import { choicesOf } from '../../utils/values';
import { FieldsPicker, type FieldsPickerField } from './FieldsPicker';
import { RecordsListRender } from './RecordsListRender';
import type { FieldMetaEntry, RecordsListProps } from './types';

type BlockFields = NonNullable<ComponentConfig<RecordsListProps>['fields']>;

/** A `Fields<T>` entry for a prop with no editor UI of its own —
 *  `fieldMeta`/`typeIsPublic` below are written only by `resolveData`.
 *  `visible: false` drops it from the sidebar; the empty fragment — not
 *  `null` — is `NewsFeedRender`'s own trick for the same reason: Puck's
 *  `render` must return an element. */
function hiddenField<Value>(): CustomField<Value> {
  return { type: 'custom', visible: false, render: () => <></> };
}

/**
 * The Puck field labels for this block (L2), built fresh on every call
 * rather than as a module-scope constant: the host globs every module's
 * `puck-blocks.ts` eagerly, before `configureI18n()` ever runs
 * (`host/client_app/app.tsx`/`blocks.ts`), so a `t()` call baked into a
 * top-level object literal here would run before i18next has any messages
 * and freeze that way forever (the same risk CLAUDE.md flags for a Zod
 * schema built at module scope). `resolveFields` below is a function Puck
 * calls later, well after boot, so calling the non-hook `t` inside it is
 * safe and picks up the active locale each time.
 *
 * `satisfies`, not a type annotation: an annotation would widen each entry
 * to the `Field<T>` union immediately, and `resolveFields` needs the
 * concrete literal type of `.fields` (a `CustomField`) to spread it safely —
 * spreading a widened union would mix in members (`TextField`, …) that don't
 * have a `render` to spread from.
 */
function buildBaseFields(tr: Translate = t) {
  return {
    typeKey: {
      type: 'select',
      label: tr('records.widget.field_type_key', { defaultValue: 'Record type' }),
      options: [{ label: tr('records.fields.choose', { defaultValue: '— choose —' }), value: '' }],
    },
    fields: {
      type: 'custom',
      label: tr('records.widget.field_fields', {
        defaultValue: 'Fields to show (beyond the title)',
      }),
      render: FieldsPicker,
    },
    filter: {
      type: 'text',
      label: tr('records.widget.field_filter', {
        defaultValue: 'Filter (e.g. status:eq:paid — one term, indexed fields only)',
      }),
    },
    sort: {
      type: 'text',
      label: tr('records.widget.field_sort', {
        defaultValue: 'Sort (e.g. -published_at for newest first)',
      }),
    },
    locale: {
      type: 'text',
      label: tr('records.widget.field_locale', {
        defaultValue: 'Locale (blank = default content locale)',
      }),
    },
    tenant: {
      type: 'text',
      label: tr('records.widget.field_tenant', {
        defaultValue: 'Tenant (multi-tenant hosts only — blank uses the host default)',
      }),
    },
    limit: {
      type: 'number',
      label: tr('records.widget.field_limit', { defaultValue: 'How many' }),
      min: 1,
      max: 50,
    },
    layout: {
      type: 'select',
      label: tr('records.widget.field_layout', { defaultValue: 'Layout' }),
      options: [
        { label: tr('records.widget.layout_list', { defaultValue: 'List' }), value: 'list' },
        { label: tr('records.widget.layout_cards', { defaultValue: 'Cards' }), value: 'cards' },
        { label: tr('records.widget.layout_table', { defaultValue: 'Table' }), value: 'table' },
      ],
    },
    title: { type: 'text', label: tr('records.widget.field_title', { defaultValue: 'Heading' }) },
    emptyText: {
      type: 'text',
      label: tr('records.widget.field_empty_text', {
        defaultValue: 'Text shown when there are no records',
      }),
    },
    linkTemplate: {
      type: 'text',
      label: tr('records.widget.field_link_template', {
        defaultValue: 'Link template ({slug} or {uuid}; blank = no link)',
      }),
    },
    apiPrefix: {
      type: 'text',
      label: tr('records.widget.field_api_prefix', {
        defaultValue:
          'Public API prefix (advanced — only change if the Records settings screen shows a different one)',
      }),
    },
    fieldMeta: hiddenField<FieldMetaEntry[]>(),
    typeIsPublic: hiddenField<boolean | null>(),
  } satisfies BlockFields;
}

// The static field shape `ComponentConfig.fields` needs at module-evaluation
// time — before `resolveFields` has ever run and before i18n is configured
// (see `buildBaseFields`'s own comment). Built by an identity translator that
// returns each `defaultValue`, so it never calls i18next at module scope and
// cannot drift from the translated builder. English here is the accepted gap
// (L2): Puck calls `resolveFields` to get the real, translated labels as soon
// as the block is added to a page or its data changes, so these are only ever
// visible, if at all, for the first paint of a brand new block in the editor
// — never on the public page, and never to an anonymous visitor.
const BASE_FIELDS = buildBaseFields(
  (_key: string, opts: { defaultValue: string }) => opts.defaultValue,
);

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
  // The block's own name in Puck's block palette — module-scope, evaluated
  // before i18n is configured (see `buildBaseFields`'s comment), and Puck
  // has no per-render hook for a `ComponentConfig`'s own `label` the way
  // `resolveFields` gives one for field labels. Left English (L2's accepted
  // gap), same reasoning as `BASE_FIELDS` below.
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
    tenant: '',
    limit: 10,
    layout: 'list',
    title: '',
    emptyText: '',
    linkTemplate: '',
    apiPrefix: DEFAULT_PUBLIC_PREFIX,
  },
  resolveFields: async (data) => {
    const types = await loadTypes();
    const fields = buildBaseFields();
    const typeOptions = [
      { label: t('records.fields.choose', { defaultValue: '— choose —' }), value: '' },
      ...types.map((rtype) => ({
        label: rtype.is_public
          ? rtype.label
          : t('records.widget.type_not_public', {
              label: rtype.label,
              defaultValue: '{label} (not public)',
            }),
        value: rtype.key,
      })),
    ];
    const selected = types.find((rtype) => rtype.key === data.props.typeKey);
    const availableFields = (selected?.fields ?? []).map((field) => ({
      value: field.key,
      label: field.label,
      type: field.type,
    }));
    return {
      ...fields,
      typeKey: { ...fields.typeKey, options: typeOptions } as SelectField,
      fields: { ...fields.fields, availableFields } satisfies FieldsPickerField,
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
    const rtype = types.find((candidate) => candidate.key === props.typeKey);
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
