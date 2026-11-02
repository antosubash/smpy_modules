/**
 * `ImageStats` block: the render side. One effect fetches every item's number
 * from the anonymous public stats route; a number that is loading or failed
 * shows a dash, never an error on a public page. The route is bounded: a
 * capped count shows as the bound and a `+`, an unavailable total (`null`) as
 * the dash.
 */

import { usePage } from '@inertiajs/react';
import {
  StatsView,
  type StatsWidgetProps,
} from '@simple-module-py/pagebuilder/pagebuilder/components/widgets/stats-widget';
import { useEffect, useMemo, useState } from 'react';

import { fetchPublicStat, type PublicStat, type StatMetric } from '../../utils/api-public';
import { useT } from '../../utils/i18n';

export interface ImageStatItem {
  metric: StatMetric;
  /** A public collection's slug; '' counts every public collection. Ignored for `collections`. */
  collection: string;
  label: string;
  prefix: string;
  suffix: string;
  iconUrl?: string;
}

export interface ImageStatsProps {
  title: string;
  subtitle: string;
  surface: StatsWidgetProps['surface'];
  items: ImageStatItem[];
}

export const STAT_ITEMS_MAX = 6;

/** What shows in place of a number that is loading or failed to load. */
const PLACEHOLDER = '–';
const METRICS = new Set(['images', 'located', 'collections']);

/** Cap a stored list and drop entries the block cannot count: stored data may
 *  predate the editor's limits, and a public page must still render it. */
export function clampStatItems(items: readonly ImageStatItem[] | undefined): ImageStatItem[] {
  if (!Array.isArray(items)) return [];
  return items
    .filter((item) => item !== null && typeof item === 'object' && METRICS.has(item.metric))
    .slice(0, STAT_ITEMS_MAX);
}

function formatValue(item: ImageStatItem, stat: PublicStat | null, locale: string | undefined) {
  if (stat === null || stat.value === null) return PLACEHOLDER;
  let text: string;
  try {
    text = new Intl.NumberFormat(locale, { maximumFractionDigits: 2 }).format(stat.value);
  } catch {
    text = new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 }).format(stat.value);
  }
  // The `+` belongs to the number, so it sits inside the author's affixes.
  const more = stat.capped ? '+' : '';
  return `${item.prefix ?? ''}${text}${more}${item.suffix ?? ''}`;
}

/** The page's language when there is one (public viewer or editor preview),
 *  else the console's; never the browser's. */
function useNumberLocale(): string | undefined {
  const props = usePage().props as unknown as {
    locale?: string | null;
    page?: { locale?: string | null } | null;
  };
  const { locale } = useT();
  return props?.locale || props?.page?.locale || locale;
}

export function ImageStatsRender({ title, subtitle, surface, items }: ImageStatsProps) {
  const numberLocale = useNumberLocale();
  // `resolveData` never runs on an anonymous public page, so clamp here too.
  const safe = useMemo(() => clampStatItems(items), [items]);
  // Values by the key of the request that produced them, never by position: a
  // reorder or a delete must not show one frame of another item's number.
  const [values, setValues] = useState<Record<string, PublicStat | null>>({});

  // Only what changes the requests: editing a label must not refetch.
  const itemKeys = safe.map((item) =>
    JSON.stringify([item.metric, item.metric === 'collections' ? '' : (item.collection ?? '')]),
  );
  const fetchKey = JSON.stringify(itemKeys);

  useEffect(() => {
    const keys = JSON.parse(fetchKey) as string[];
    const controller = new AbortController();
    Promise.allSettled(
      keys.map((key) => {
        const [metric, collection] = JSON.parse(key) as [StatMetric, string];
        return fetchPublicStat({ metric, collection, signal: controller.signal });
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
