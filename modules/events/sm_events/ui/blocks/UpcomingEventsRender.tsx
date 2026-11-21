/**
 * The `UpcomingEvents` block as a visitor sees it: the next public occurrences, fetched
 * client-side from the anonymous route (as news' feed does), so a block's data has its own short
 * cache and never goes stale inside its page's.
 *
 * Text only, never markup. The page's language comes from the page (`useContentLocale`), and the
 * dates are the event's own clock as the server sent it. While loading, when there is nothing to
 * show, and when the fetch fails, a visitor sees nothing at all (a heading over an empty list
 * reads as a broken section); the editor gets a hint instead.
 */

import { useEffect, useState } from 'react';
import type { PublicListItem } from '../public/types';
import { ItemBody } from '../public/UpcomingList';
import { keys, useT } from '../utils/i18n';
import { PageLocale } from '../utils/PageLocale';
import { fetchBlockCalendars, fetchUpcoming } from './api-blocks';
import { BlockBoundary } from './BlockBoundary';
import { clampCount, oneOf, selectionOf } from './limits';
import { useContentLocale } from './useContentLocale';

export type UpcomingEventsProps = {
  heading: string;
  calendars: { slug: string }[];
  category: string;
  count: number;
  layout: 'list' | 'cards';
  showImages: boolean;
};

export const HEADING_MAX = 200;
export const LAYOUTS = ['list', 'cards'] as const;
const copy = keys.events.blocks;

/** What Puck hands a block's render beside its props. */
type WithPuck = { puck?: { isEditing?: boolean } };

type State = { items: PublicListItem[] | null; failed: boolean };

function useUpcoming(props: UpcomingEventsProps, locale: string): State {
  const [state, setState] = useState<State>({ items: null, failed: false });
  const { slugs, bad } = selectionOf(props.calendars);
  const count = clampCount(props.count);
  const category = typeof props.category === 'string' ? props.category : '';
  const key = `${bad}|${slugs.join('\u0000')}|${category}|${count}|${locale}`;
  // biome-ignore lint/correctness/useExhaustiveDependencies: `key` stands for the query it names
  useEffect(() => {
    // A selection that cannot be read means nothing, so nothing is asked for.
    if (bad) {
      setState({ items: [], failed: false });
      return;
    }
    const controller = new AbortController();
    fetchUpcoming({ slugs, category, count, locale }, controller.signal)
      .then((items) => setState({ items, failed: false }))
      // An empty list and a failed fetch look the same to a visitor on purpose: a broken API must
      // not put an error box on a public page.
      .catch(() => {
        if (!controller.signal.aborted) setState({ items: [], failed: true });
      });
    return () => controller.abort();
  }, [key]);
  return state;
}

/** How many of the chosen calendars the public no longer sees (the editor's hint only). */
function useUnresolved(props: UpcomingEventsProps, locale: string, editing: boolean): number {
  const [missing, setMissing] = useState(0);
  const { slugs } = selectionOf(props.calendars);
  const key = `${slugs.join('\u0000')}|${locale}`;
  // biome-ignore lint/correctness/useExhaustiveDependencies: `key` stands for the slugs
  useEffect(() => {
    if (!editing || slugs.length === 0) {
      setMissing(0);
      return;
    }
    const controller = new AbortController();
    fetchBlockCalendars(slugs, locale, controller.signal)
      .then((answer) => setMissing(Math.max(0, slugs.length - answer.calendars.length)))
      .catch(() => {});
    return () => controller.abort();
  }, [key, editing]);
  return missing;
}

function Cards({
  items,
  locale,
  images,
}: {
  items: PublicListItem[];
  locale: string;
  images: boolean;
}) {
  return (
    <ul className="grid items-start gap-4 sm:grid-cols-2 lg:grid-cols-3">
      {items.map((item) => (
        <li key={item.key} className="space-y-1 overflow-hidden rounded border p-3">
          {images && item.image ? (
            <img
              src={item.image}
              alt=""
              loading="lazy"
              className="mb-2 aspect-video w-full rounded object-cover"
            />
          ) : null}
          <ItemBody item={item} locale={locale} />
        </li>
      ))}
    </ul>
  );
}

function Inner(props: UpcomingEventsProps & WithPuck) {
  const { t } = useT();
  const locale = useContentLocale();
  const editing = props.puck?.isEditing === true;
  const { items, failed } = useUpcoming(props, locale ?? '');
  const missing = useUnresolved(props, locale ?? '', editing);
  const unreadable = selectionOf(props.calendars).bad;
  const heading =
    typeof props.heading === 'string' ? props.heading.slice(0, HEADING_MAX).trim() : '';
  const layout = oneOf(props.layout, LAYOUTS, 'list');
  const hints = [
    unreadable
      ? t(copy.editor_hint.selection_unreadable)
      : failed
        ? t(copy.editor_hint.failed)
        : items?.length === 0
          ? t(copy.editor_hint.empty)
          : null,
    missing > 0 ? t(copy.editor_hint.unresolved, { count: missing }) : null,
  ].filter((hint): hint is string => hint !== null);
  const hint =
    editing && hints.length > 0 ? (
      <p className="container mx-auto px-4 py-2 text-sm text-muted-foreground" data-editor-only="">
        {hints.join(' ')}
      </p>
    ) : null;
  if (items === null || items.length === 0) return hint ?? <></>;
  const shown = locale ?? 'en';
  return (
    <section
      className="container mx-auto space-y-3 px-4 py-4"
      aria-label={heading || t(copy.upcoming.label)}
    >
      {heading ? <h2 className="text-xl font-semibold">{heading}</h2> : null}
      {layout === 'cards' ? (
        <Cards items={items} locale={shown} images={props.showImages !== false} />
      ) : (
        <ul className="divide-y">
          {items.map((item) => (
            <li key={item.key} className="space-y-1 py-3">
              <ItemBody item={item} locale={shown} />
            </li>
          ))}
        </ul>
      )}
      {hint}
    </section>
  );
}

export function UpcomingEventsRender(props: UpcomingEventsProps & WithPuck) {
  const locale = useContentLocale();
  const inner = (
    <BlockBoundary>
      <Inner {...props} />
    </BlockBoundary>
  );
  return locale ? <PageLocale locale={locale}>{inner}</PageLocale> : inner;
}
