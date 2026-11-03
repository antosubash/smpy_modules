/**
 * `RecordStats` block: the render side. One effect fetches every item's
 * number from the anonymous public stats route; a number that is loading or
 * failed shows a dash, never an error on a public page. The route stops at
 * `max_count` like the listing's total: a capped count shows as the ceiling
 * and a `+`, and a capped sum (no value) as the dash.
 */

import {
  StatsView,
  type StatsWidgetProps,
} from '@simple-module-py/pagebuilder/pagebuilder/ui/components/widgets/stats-widget';
import { useEffect, useMemo, useState } from 'react';

import { formatNumber } from '../../utils/locale';
import { fetchPublicStat, type PublicStat } from '../../utils/public-api';
import { useDateLocale } from './FieldValues';

export interface RecordStatItem {
  typeKey: string;
  metric: 'count' | 'sum';
  /** The number field summed; ignored for `count`. */
  field: string;
  /** One filter term, as the list block's. */
  filter: string;
  label: string;
  prefix: string;
  suffix: string;
  iconUrl?: string;
}

export interface RecordStatsProps {
  title: string;
  subtitle: string;
  surface: StatsWidgetProps['surface'];
  items: RecordStatItem[];
  /** `?locale=` on every request; blank is the site's default content locale. */
  locale: string;
  tenant: string;
  apiPrefix: string;
}

export const STAT_ITEMS_MAX = 6;

/** What shows in place of a number that is loading or failed to load. */
const PLACEHOLDER = '–';

/**
 * Cap a stored list at {@link STAT_ITEMS_MAX} and drop entries the block
 * cannot count. Stored data may predate the editor's limits or have been
 * written through the API, and a public page must still render it.
 */
export function clampStatItems(items: readonly RecordStatItem[] | undefined): RecordStatItem[] {
  if (!Array.isArray(items)) return [];
  return items
    .filter(
      (item) =>
        item !== null &&
        typeof item === 'object' &&
        (item.metric === 'count' || item.metric === 'sum'),
    )
    .slice(0, STAT_ITEMS_MAX);
}

/** The `metric` query value, or null when the item cannot be asked. */
function metricOf(item: RecordStatItem): string | null {
  if (!item.typeKey?.trim()) return null;
  if (item.metric === 'count') return 'count';
  return item.field?.trim() ? `sum:${item.field.trim()}` : null;
}

function formatValue(item: RecordStatItem, stat: PublicStat | null, locale: string | undefined) {
  if (stat === null || stat.value === null) return PLACEHOLDER;
  const text = formatNumber(stat.value, locale, { maximumFractionDigits: 2 });
  // The `+` belongs to the number, so it sits inside the author's affixes.
  const more = stat.capped ? '+' : '';
  return `${item.prefix ?? ''}${text}${more}${item.suffix ?? ''}`;
}

export function RecordStatsRender({
  title,
  subtitle,
  surface,
  items,
  locale,
  tenant,
  apiPrefix,
}: RecordStatsProps) {
  const numberLocale = useDateLocale({ locale });
  // `resolveData` never runs on an anonymous public page, so clamp here too.
  const safe = useMemo(() => clampStatItems(items), [items]);
  // Values by the key of the request that produced them, never by position: a
  // reorder, a delete or a locale change must not show one frame of another
  // item's number while the effect catches up. The key carries the block-wide
  // parts (prefix, locale, tenant) too.
  const [values, setValues] = useState<Record<string, PublicStat | null>>({});

  // Only what changes the requests: editing a label must not refetch.
  const itemKeys = safe.map((item) =>
    JSON.stringify([
      apiPrefix ?? '',
      locale ?? '',
      tenant ?? '',
      item.typeKey ?? '',
      metricOf(item),
      item.filter ?? '',
    ]),
  );
  const fetchKey = JSON.stringify(itemKeys);

  useEffect(() => {
    const keys = JSON.parse(fetchKey) as string[];
    const controller = new AbortController();
    Promise.allSettled(
      keys.map((key) => {
        const [prefix, itemLocale, itemTenant, typeKey, metric, filter] = JSON.parse(key) as [
          string,
          string,
          string,
          string,
          string | null,
          string,
        ];
        return metric === null
          ? Promise.reject(new Error('incomplete stat'))
          : fetchPublicStat(prefix, typeKey, {
              metric,
              filter,
              locale: itemLocale,
              tenant: itemTenant,
              signal: controller.signal,
            });
      }),
    ).then((results) => {
      if (controller.signal.aborted) return;
      setValues(
        Object.fromEntries(
          keys.map((key, i) => {
            const r = results[i];
            return [key, r.status === 'fulfilled' ? r.value : null];
          }),
        ),
      );
    });
    return () => controller.abort();
  }, [fetchKey]);

  const shown = safe.map((item, index) => ({
    value: formatValue(item, values[itemKeys[index]] ?? null, numberLocale),
    label: item.label,
    iconUrl: item.iconUrl || undefined,
  }));

  return <StatsView title={title} subtitle={subtitle} surface={surface} items={shown} />;
}
