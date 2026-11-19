/**
 * The `EventsCalendar` block as a visitor sees it: PR 3's `Calendar`, read-only, over the public
 * calendars the block names. This file is a chunk of its own (the block registers it through
 * `lazyBlock`), so FullCalendar loads only on a page that renders a calendar.
 *
 * It reuses the public page's grid (`PublicCalendarGrid`): the same zone rule
 * (`publicGridZone`), the same plugin slots for the public surface and a detail whose one action
 * opens the event's public page. Its data is the anonymous occurrences route, limited to the
 * calendars the server resolved from the stored slugs: one that stopped being public is simply
 * not there, and when nothing resolves the block renders nothing (the editor is told how many).
 */

import { useEffect, useMemo, useState } from 'react';
import { PublicCalendarGrid } from '../public/PublicCalendarGrid';
import type { PublicCalendar, PublicCategory } from '../public/types';
import { keys, useT } from '../utils/i18n';
import { PageLocale } from '../utils/PageLocale';
import { type BlockCalendars, fetchBlockCalendars } from './api-blocks';
import { BlockBoundary } from './BlockBoundary';
import { type EventsCalendarProps, minHeight, VIEWS } from './calendarProps';
import { oneOf, slugsOf } from './limits';
import { useContentLocale } from './useContentLocale';

export const OCCURRENCES_URL = '/api/events/public/occurrences';
const copy = keys.events.blocks;

type WithPuck = { puck?: { isEditing?: boolean } };

type Loaded = { answer: BlockCalendars | null; failed: boolean; loading: boolean };

function useCalendars(slugs: string[], locale: string): Loaded {
  const [state, setState] = useState<Loaded>({ answer: null, failed: false, loading: true });
  const key = `${slugs.join('\u0000')}|${locale}`;
  // biome-ignore lint/correctness/useExhaustiveDependencies: `key` stands for the query it names
  useEffect(() => {
    const controller = new AbortController();
    fetchBlockCalendars(slugs, locale, controller.signal)
      .then((answer) => setState({ answer, failed: false, loading: false }))
      .catch(() => {
        if (!controller.signal.aborted) setState({ answer: null, failed: true, loading: false });
      });
    return () => controller.abort();
  }, [key]);
  return state;
}

function Inner(props: EventsCalendarProps & WithPuck) {
  const { t } = useT();
  const locale = useContentLocale();
  const slugs = slugsOf(props.calendars);
  const { answer, failed, loading } = useCalendars(slugs, locale ?? '');
  const height = minHeight(props.height);
  const view = oneOf(props.defaultView, VIEWS, 'month');
  const editing = props.puck?.isEditing === true;
  const calendars = useMemo<PublicCalendar[]>(
    () =>
      (answer?.calendars ?? []).map((c) => ({
        ...c,
        description: null,
        url: '',
        feed_url: '',
      })),
    [answer],
  );
  const categories = useMemo<PublicCategory[]>(() => answer?.categories ?? [], [answer]);
  const ids = useMemo(() => calendars.map((c) => c.id), [calendars]);
  if (loading) {
    return (
      <div className="container mx-auto px-4 py-4">
        <div data-events-calendar="" style={{ minHeight: height }} aria-busy="true" />
      </div>
    );
  }
  if (failed || calendars.length === 0) {
    const missing = slugs.length - calendars.length;
    return editing && !failed && missing > 0 ? (
      <p className="container mx-auto px-4 py-2 text-sm text-muted-foreground" data-editor-only="">
        {t(copy.editor_hint.unresolved, { count: missing })}
      </p>
    ) : (
      <></>
    );
  }
  return (
    <div className="container mx-auto px-4 py-4">
      <section
        data-events-calendar=""
        style={{ minHeight: height }}
        aria-label={t(copy.calendar.label)}
      >
        <PublicCalendarGrid
          apiUrl={OCCURRENCES_URL}
          calendars={calendars}
          categories={categories}
          defaultTimezone={answer?.default_timezone ?? 'UTC'}
          initial={{ view }}
          limitTo={slugs.length > 0 ? ids : undefined}
        />
      </section>
    </div>
  );
}

export function EventsCalendarRender(props: EventsCalendarProps & WithPuck) {
  const locale = useContentLocale();
  const inner = (
    <BlockBoundary>
      <Inner {...props} />
    </BlockBoundary>
  );
  return locale ? <PageLocale locale={locale}>{inner}</PageLocale> : inner;
}
