/**
 * `RecordForm` Puck block (#101, design §8): a working contact form or
 * newsletter signup on a published page, or in the site header or footer
 * (registered with `layout: true` in `pagebuilder-blocks.ts`).
 *
 * Built the way `RecordsListBlock.tsx` is: the type picker and the field
 * list of the label overrides call the session-gated admin API from
 * `resolveFields`/`resolveData`, which only the Puck *editor* runs — `<Render>`
 * on the public page calls neither. Field labels are catalogue keys at module
 * scope (resolved by pagebuilder's `localizeConfig`, which walks into
 * `arrayFields` too), and translated with `translate` once Puck resolves them.
 *
 * The block holds no trust: it names a type, and the type decides what is
 * public (`RecordFormProps`).
 */

import type { ArrayField, ComponentConfig, CustomField, SelectField } from '@puckeditor/core';
import { listTypes } from '../../../utils/api';
import { keys, type Translate, translate } from '../../../utils/i18n';
import type { TypeRead } from '../../../utils/types';
import { RecordFormRender } from './RecordFormRender';
import type { LabelOverride, RecordFormProps } from './types';

type BlockFields = NonNullable<ComponentConfig<RecordFormProps>['fields']>;

const block = keys.records.public_submissions.block;

function hiddenField<Value>(): CustomField<Value> {
  return { type: 'custom', visible: false, render: () => <></> };
}

const asKey: Translate = (key) => key;

function buildFields(tr: Translate) {
  return {
    typeKey: {
      type: 'select',
      label: tr(block.field_type_key),
      options: [{ label: tr(keys.records.fields.choose), value: '' }],
    },
    title: { type: 'text', label: tr(block.field_title) },
    intro: { type: 'textarea', label: tr(block.field_intro) },
    submitLabel: { type: 'text', label: tr(block.field_submit_label) },
    successTitle: { type: 'text', label: tr(block.field_success_title) },
    successBody: { type: 'textarea', label: tr(block.field_success_body) },
    labels: {
      type: 'array',
      label: tr(block.field_labels),
      // Called at render, so the non-hook `translate` is safe here.
      getItemSummary: (item: LabelOverride) => item.field || translate(block.label_new),
      defaultItemProps: { field: '', label: '', help: '' },
      arrayFields: {
        field: {
          type: 'select',
          label: tr(block.label_field),
          options: [{ label: tr(keys.records.fields.choose), value: '' }],
        },
        label: { type: 'text', label: tr(block.label_label) },
        help: { type: 'text', label: tr(block.label_help) },
      },
    },
    kindHint: hiddenField<string>(),
  } satisfies BlockFields;
}

/** Module scope, so it holds the catalogue keys; `localizeConfig` resolves
 *  them when the editor mounts, and `resolveFields` replaces them later. */
const BASE_FIELDS = buildFields(asKey);

async function loadTypes(): Promise<TypeRead[]> {
  try {
    return (await listTypes()).items.filter((rtype) => rtype.public_submissions?.kind);
  } catch {
    return []; // not logged in, or a blip mid-edit: never break the editor
  }
}

/** The fields a visitor fills on ``rtype``'s form — what an override can name. */
function publicFieldsOf(rtype: TypeRead | undefined): { label: string; value: string }[] {
  const config = rtype?.public_submissions;
  if (!rtype || !config) return [];
  const names = [...(config.kind === 'subscription' ? ['sm_email'] : []), ...config.public_fields];
  return names.flatMap((key) => {
    const def = rtype.fields.find((field) => field.key === key);
    return def ? [{ label: def.label, value: key }] : [];
  });
}

export const RecordFormBlock: ComponentConfig<RecordFormProps> = {
  label: block.block_label,
  fields: BASE_FIELDS,
  defaultProps: {
    typeKey: '',
    title: '',
    intro: '',
    submitLabel: '',
    successTitle: '',
    successBody: '',
    labels: [],
    kindHint: '',
  },
  resolveFields: async (data) => {
    const types = await loadTypes();
    const fields = buildFields(translate);
    const choose = { label: translate(keys.records.fields.choose), value: '' };
    const typeOptions = [
      choose,
      ...types.map((rtype) => ({
        label: rtype.public_submissions?.enabled
          ? rtype.label
          : translate(block.type_disabled, { label: rtype.label }),
        value: rtype.key,
      })),
    ];
    const selected = types.find((rtype) => rtype.key === data.props.typeKey);
    const labels = fields.labels;
    return {
      ...fields,
      typeKey: { ...fields.typeKey, options: typeOptions } as SelectField,
      labels: {
        ...labels,
        arrayFields: {
          ...labels.arrayFields,
          field: {
            ...labels.arrayFields.field,
            options: [choose, ...publicFieldsOf(selected)],
          } as SelectField,
        },
      } as ArrayField<LabelOverride[]>,
    };
  },
  resolveData: async ({ props }, { changed, trigger }) => {
    if (trigger !== 'load' && !changed.typeKey) return { props };
    const types = await loadTypes();
    if (types.length === 0) return { props };
    const kind = types.find((rtype) => rtype.key === props.typeKey)?.public_submissions?.kind;
    return { props: { ...props, kindHint: kind ?? '' } };
  },
  render: RecordFormRender,
};
