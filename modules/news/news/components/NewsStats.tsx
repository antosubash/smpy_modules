import type { ComponentConfig } from '@puckeditor/core';
import {
  StatsView,
  type StatsWidgetProps,
} from '@simple-module-py/pagebuilder/pagebuilder/components/widgets/stats-widget';
import {
  createImageField,
  mediaLibraryAdapter,
} from '@simple-module-py/pagebuilder/pagebuilder/fields';
import { useEffect, useMemo, useState } from 'react';

import { useContentLocale } from '../hooks/useContentLocale';
import { keys } from '../utils/i18n';
import { intlLocale } from '../utils/locale';
import { fetchPublishedCount } from '../utils/stats-api';

export interface NewsStatItem {
  /** `page` counts the page's own language; `all` counts every language. */
  language: 'page' | 'all';
  category: string;
  label: string;
  prefix: string;
  suffix: string;
  iconUrl?: string;
}

export interface NewsStatsProps {
  title: string;
  subtitle: string;
  surface: StatsWidgetProps['surface'];
  items: NewsStatItem[];
}

export const STAT_ITEMS_MAX = 6;

/** What shows in place of a number that is loading or failed to load. */
const PLACEHOLDER = '–';

/**
 * Cap a stored list at {@link STAT_ITEMS_MAX} and drop entries the block cannot
 * count. Stored data may predate the editor's limits or have been written
 * through the API, and a public page must still render it rather than throw.
 */
export function clampStatItems(items: readonly NewsStatItem[] | undefined): NewsStatItem[] {
  if (!Array.isArray(items)) return [];
  return items
    .filter(
      (item) =>
        item !== null &&
        typeof item === 'object' &&
        (item.language === 'page' || item.language === 'all'),
    )
    .slice(0, STAT_ITEMS_MAX);
}

function formatValue(item: NewsStatItem, value: number | null, locale: string | undefined) {
  if (value === null) return PLACEHOLDER;
  const text = new Intl.NumberFormat(intlLocale(locale), { maximumFractionDigits: 2 }).format(
    value,
  );
  return `${item.prefix ?? ''}${text}${item.suffix ?? ''}`;
}

export function NewsStatsRender({ title, subtitle, surface, items }: NewsStatsProps) {
  // The page's language, not a field on the block (see `useContentLocale`).
  const locale = useContentLocale();
  // `resolveData` never runs on an anonymous public page, so clamp here too.
  const safe = useMemo(() => clampStatItems(items), [items]);
  const [values, setValues] = useState<(number | null)[]>([]);

  // Only what changes the requests: editing a label must not refetch.
  const fetchKey = JSON.stringify(
    safe.map((item) => [item.category ?? '', item.language === 'page' ? (locale ?? null) : null]),
  );

  useEffect(() => {
    const specs = JSON.parse(fetchKey) as [string, string | null][];
    const controller = new AbortController();
    setValues([]);
    Promise.allSettled(
      specs.map(([category, itemLocale]) =>
        fetchPublishedCount({ category, locale: itemLocale, signal: controller.signal }),
      ),
    ).then((results) => {
      if (controller.signal.aborted) return;
      // A failed fetch is a dash, not an error box: a broken API must not put
      // one on a public page.
      setValues(results.map((r) => (r.status === 'fulfilled' ? r.value : null)));
    });
    return () => controller.abort();
  }, [fetchKey]);

  const shown = safe.map((item, index) => ({
    value: formatValue(item, values[index] ?? null, locale),
    label: item.label,
    iconUrl: item.iconUrl || undefined,
  }));

  return <StatsView title={title} subtitle={subtitle} surface={surface} items={shown} />;
}

/**
 * The palette entry. Labels are catalogue keys, resolved by pagebuilder's
 * `localizeConfig` (see `NewsFeedBlock`).
 */
export const NewsStatsBlock: ComponentConfig<NewsStatsProps> = {
  label: keys.news.stats.label,
  fields: {
    title: { type: 'text', label: keys.news.stats.title },
    subtitle: { type: 'textarea', label: keys.news.stats.subtitle },
    items: {
      type: 'array',
      label: keys.news.stats.items,
      arrayFields: {
        label: { type: 'text', label: keys.news.stats.item_label },
        category: { type: 'text', label: keys.news.stats.item_category },
        language: {
          type: 'select',
          label: keys.news.stats.item_language,
          options: [
            { label: keys.news.stats.item_language_page, value: 'page' },
            { label: keys.news.stats.item_language_all, value: 'all' },
          ],
        },
        prefix: { type: 'text', label: keys.news.stats.item_prefix },
        suffix: { type: 'text', label: keys.news.stats.item_suffix },
        iconUrl: createImageField(mediaLibraryAdapter, keys.news.stats.item_icon),
      },
      defaultItemProps: {
        language: 'page',
        category: '',
        label: 'Articles published',
        prefix: '',
        suffix: '',
      },
      min: 1,
      max: STAT_ITEMS_MAX,
    },
    surface: {
      type: 'select',
      label: keys.news.stats.surface,
      options: [
        { label: keys.news.stats.surface_default, value: 'default' },
        { label: keys.news.stats.surface_lime, value: 'lime' },
        { label: keys.news.stats.surface_cards, value: 'cards' },
      ],
    },
  },
  defaultProps: {
    title: '',
    subtitle: '',
    surface: 'default',
    items: [
      { language: 'page', category: '', label: 'Articles published', prefix: '', suffix: '' },
    ],
  },
  // Once on load, never per keystroke (the `NewsFeedBlock` precedent).
  resolveData: ({ props }, { trigger }) =>
    trigger === 'load' ? { props: { ...props, items: clampStatItems(props.items) } } : { props },
  render: NewsStatsRender,
};
