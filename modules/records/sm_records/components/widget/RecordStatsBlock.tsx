/**
 * `RecordStats` Puck block: up to six live numbers from public record types
 * (a count, or the sum of an indexed number field). Config side; the render
 * is `RecordStatsRender.tsx`. Types and fields are offered from the admin
 * `listTypes()` inside the editor only; the public page never calls it.
 */

import type { ComponentConfig } from '@puckeditor/core';
import {
  createImageField,
  mediaLibraryAdapter,
} from '@simple-module-py/pagebuilder/pagebuilder/ui/fields';

import { keys, type Translate, translate } from '../../utils/i18n';
import { DEFAULT_PUBLIC_PREFIX } from '../../utils/public-api';
import type { TypeRead } from '../../utils/types';
import {
  clampStatItems,
  type RecordStatItem,
  type RecordStatsProps,
  RecordStatsRender,
  STAT_ITEMS_MAX,
} from './RecordStatsRender';
import { loadTypes } from './RecordsListBlock';

export type { RecordStatItem };
export { clampStatItems, RecordStatsRender };

const NUMBER_TYPES = new Set(['number', 'integer']);

type Option = { label: string; value: string };
type BlockFields = NonNullable<ComponentConfig<RecordStatsProps>['fields']>;

/** A new block's first item, and every item added to it. */
const DEFAULT_ITEM: RecordStatItem = {
  typeKey: '',
  metric: 'count',
  field: '',
  filter: '',
  label: 'Records',
  prefix: '',
  suffix: '',
};

/** An unindexed field is refused `not_indexed` by the endpoint, so it is not
 *  offered; a text field cannot be summed. */
function sumFieldOptions(types: TypeRead[], chosen: Set<string>): Option[] {
  const seen = new Set<string>();
  const out: Option[] = [];
  for (const rtype of types) {
    if (!chosen.has(rtype.key)) continue;
    for (const field of rtype.fields) {
      if (!NUMBER_TYPES.has(field.type) || !field.indexed || seen.has(field.key)) continue;
      seen.add(field.key);
      out.push({ label: `${rtype.label}: ${field.label}`, value: field.key });
    }
  }
  return out;
}

function buildFields(tr: Translate, typeOptions: Option[], fieldOptions: Option[]): BlockFields {
  const k = keys.records.stats;
  const choose = { label: tr(keys.records.fields.choose), value: '' };
  return {
    title: { type: 'text', label: tr(k.title) },
    subtitle: { type: 'textarea', label: tr(k.subtitle) },
    items: {
      type: 'array',
      label: tr(k.items),
      arrayFields: {
        label: { type: 'text', label: tr(k.item_label) },
        typeKey: { type: 'select', label: tr(k.item_type), options: [choose, ...typeOptions] },
        metric: {
          type: 'select',
          label: tr(k.item_metric),
          options: [
            { label: tr(k.item_metric_count), value: 'count' },
            { label: tr(k.item_metric_sum), value: 'sum' },
          ],
        },
        field: { type: 'select', label: tr(k.item_field), options: [choose, ...fieldOptions] },
        filter: { type: 'text', label: tr(k.item_filter) },
        prefix: { type: 'text', label: tr(k.item_prefix) },
        suffix: { type: 'text', label: tr(k.item_suffix) },
        iconUrl: createImageField(mediaLibraryAdapter, tr(k.item_icon)),
      },
      defaultItemProps: DEFAULT_ITEM,
      min: 1,
      max: STAT_ITEMS_MAX,
    },
    surface: {
      type: 'select',
      label: tr(k.surface),
      options: [
        { label: tr(k.surface_default), value: 'default' },
        { label: tr(k.surface_lime), value: 'lime' },
        { label: tr(k.surface_cards), value: 'cards' },
      ],
    },
    locale: { type: 'text', label: tr(k.locale) },
    tenant: { type: 'text', label: tr(k.tenant) },
    apiPrefix: { type: 'text', label: tr(k.api_prefix) },
  };
}

export const RecordStatsBlock: ComponentConfig<RecordStatsProps> = {
  label: keys.records.stats.label,
  // Labels are catalogue keys here (pagebuilder's `localizeConfig` resolves
  // them); `resolveFields` supplies translated ones once the editor runs.
  fields: buildFields((key) => key, [], []),
  defaultProps: {
    title: '',
    subtitle: '',
    surface: 'default',
    items: [{ ...DEFAULT_ITEM }],
    locale: '',
    tenant: '',
    apiPrefix: DEFAULT_PUBLIC_PREFIX,
  },
  resolveFields: async (data) => {
    const types = await loadTypes();
    const chosen = new Set((data.props.items ?? []).map((item) => item?.typeKey ?? ''));
    return buildFields(
      translate,
      // Like the list block: a type that is not public renders nothing on the
      // site (its stats route is a 404), so the author is told in the picker.
      types.map((rtype) => ({
        label: rtype.is_public
          ? rtype.label
          : translate(keys.records.widget.type_not_public, { label: rtype.label }),
        value: rtype.key,
      })),
      sumFieldOptions(types, chosen),
    );
  },
  // Once on load, never per keystroke.
  resolveData: ({ props }, { trigger }) =>
    trigger === 'load' ? { props: { ...props, items: clampStatItems(props.items) } } : { props },
  render: RecordStatsRender,
};
