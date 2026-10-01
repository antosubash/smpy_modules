/**
 * One record's selected field values, for the `RecordsList` widget's list,
 * cards and table layouts. Split out of `RecordsListRender.tsx` (300-line cap)
 * when `media` values stopped being plain text.
 */

import type { CSSProperties, ReactNode } from 'react';

import type { PublicRecordItem } from '../../utils/public-api';
import { formatPublicValue, publicMediaSrc } from './format';
import { PublicMediaImage } from './PublicMediaImage';
import type { FieldMetaEntry, RecordsListProps } from './types';

const MUTED_STYLE: CSSProperties = { color: 'var(--pb-body-color)', opacity: 0.7 };

/** One value, or `null` for a `media` value there is nothing to show for —
 *  see `format.ts::publicMediaSrc` for when that is (on a stock host: always). */
export function publicValue(
  meta: FieldMetaEntry,
  item: PublicRecordItem,
  mediaUrlTemplate: string | null,
): ReactNode {
  const value = item.data[meta.key];
  if (meta.type !== 'media') return formatPublicValue(meta, value);
  const src = publicMediaSrc(value, mediaUrlTemplate);
  return src ? <PublicMediaImage src={src} alt={item.display_title} /> : null;
}

/** "Label: value" per selected field, skipping a field with nothing to show
 *  rather than printing its label beside an empty space. */
export function FieldValues({
  item,
  props,
  mediaUrlTemplate,
}: {
  item: PublicRecordItem;
  props: RecordsListProps;
  mediaUrlTemplate: string | null;
}) {
  if (props.fieldMeta.length === 0) return null;
  return (
    <>
      {props.fieldMeta.map((meta) => {
        const value = publicValue(meta, item, mediaUrlTemplate);
        if (value === null) return null;
        return (
          <span key={meta.key} className="text-sm" style={MUTED_STYLE}>
            <span className="font-medium">{meta.label}:</span> {value}
          </span>
        );
      })}
    </>
  );
}
