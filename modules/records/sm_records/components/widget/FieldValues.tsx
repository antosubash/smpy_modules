/**
 * One record's selected field values, for the `RecordsList` widget's list,
 * cards and table layouts. Split out of `RecordsListRender.tsx` (300-line cap)
 * when `media` values stopped being plain text.
 */

import { usePage } from '@inertiajs/react';
import type { CSSProperties, ReactNode } from 'react';

import { useT } from '../../utils/i18n';
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
  locale: string | undefined,
): ReactNode {
  const value = item.data[meta.key];
  if (meta.type !== 'media') return formatPublicValue(meta, value, locale);
  const src = publicMediaSrc(value, mediaUrlTemplate);
  return src ? <PublicMediaImage src={src} alt={item.display_title} /> : null;
}

/** What the page around the widget says its language is: the public viewer
 *  sends `locale`, the page editor (whose canvas renders the same block) the
 *  page being edited — the same two props news' `useContentLocale` reads. */
interface PageLocaleProps {
  locale?: string | null;
  page?: { locale?: string | null } | null;
}

/** The locale the widget's dates are written in (#189): the page's own
 *  language, since the dates are part of the page a visitor reads; else the
 *  language the widget lists, when one is set; else the console's — never the
 *  browser's. A German page shows German dates even to a reader whose console
 *  is in English. */
export function useDateLocale(props: Pick<RecordsListProps, 'locale'>): string | undefined {
  const { locale } = useT();
  const page = usePage().props as unknown as PageLocaleProps;
  return page?.locale || page?.page?.locale || props.locale || locale;
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
  const locale = useDateLocale(props);
  if (props.fieldMeta.length === 0) return null;
  return (
    <>
      {props.fieldMeta.map((meta) => {
        const value = publicValue(meta, item, mediaUrlTemplate, locale);
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
