import { useCallback, useMemo } from 'react';
import type { CalendarState } from '../ui/calendar/types';
import { useDocumentLang } from '../ui/hooks/useDocumentLang';
import { CategoryFilter } from '../ui/public/CategoryFilter';
import { LanguageSwitch } from '../ui/public/LanguageSwitch';
import { PublicCalendarGrid } from '../ui/public/PublicCalendarGrid';
import { PublicHead } from '../ui/public/PublicHead';
import { SubscribeBox } from '../ui/public/SubscribeBox';
import type { PublicIndexProps } from '../ui/public/types';
import { UpcomingList } from '../ui/public/UpcomingList';
import { keys, useT } from '../ui/utils/i18n';
import { PageLocale } from '../ui/utils/PageLocale';

/** `?view=calendar&date=…` keeps a copied link on the same month. Nothing else in the query
 *  is touched (the category, the page). */
function mirror(state: CalendarState) {
  const url = new URL(window.location.href);
  url.searchParams.set('view', 'calendar');
  url.searchParams.set('date', state.date);
  window.history.replaceState(window.history.state, '', url);
}

function initialState(): Partial<CalendarState> {
  const date = new URLSearchParams(window.location.search).get('date');
  return date && /^\d{4}-\d{2}-\d{2}$/.test(date) ? { date } : {};
}

function Pager({ props, base }: { props: PublicIndexProps; base: string }) {
  const { t } = useT();
  const copy = keys.events.public.index;
  if (props.page_count < 2) return null;
  const href = (page: number) => {
    const q = new URLSearchParams();
    if (props.category) q.set('category', props.category);
    if (page > 1) q.set('page', String(page));
    const text = q.toString();
    return text ? `${base}?${text}` : base;
  };
  return (
    <nav aria-label={t(copy.pagination)} className="flex items-center gap-4 text-sm">
      {props.page > 1 ? (
        <a href={href(props.page - 1)} rel="prev" className="underline">
          {t(copy.previous)}
        </a>
      ) : null}
      <span>{t(copy.page_of, { page: props.page, count: props.page_count })}</span>
      {props.page < props.page_count ? (
        <a href={href(props.page + 1)} rel="next" className="underline">
          {t(copy.next)}
        </a>
      ) : null}
    </nav>
  );
}

function PublicIndexPage(props: PublicIndexProps) {
  const { t } = useT();
  const copy = keys.events.public.index;
  useDocumentLang(props.locale);
  const base = props.calendar?.url ?? window.location.pathname;
  const title = props.title;
  const initial = useMemo(initialState, []);
  const onState = useCallback(mirror, []);
  const tab = (view: 'list' | 'calendar', label: string) => {
    const q = new URLSearchParams();
    if (props.category) q.set('category', props.category);
    if (view === 'calendar') q.set('view', 'calendar');
    const text = q.toString();
    return (
      <a
        href={text ? `${base}?${text}` : base}
        aria-current={props.view === view ? 'page' : undefined}
        className={props.view === view ? 'font-semibold underline' : 'underline'}
      >
        {label}
      </a>
    );
  };
  return (
    <>
      <PublicHead head={props.head} locale={props.locale} alternates={props.alternates} />
      <main className="mx-auto max-w-4xl space-y-6 p-4" aria-label={t(copy.region)}>
        <header className="space-y-2">
          <h1 className="text-2xl font-semibold">{title}</h1>
          {props.calendar?.description ? <p>{props.calendar.description}</p> : null}
          <LanguageSwitch alternates={props.alternates} locale={props.locale} />
        </header>
        <nav className="flex gap-4 text-sm" aria-label={t(copy.tabs)}>
          {tab('list', t(copy.tab_list))}
          {tab('calendar', t(copy.tab_calendar))}
        </nav>
        <CategoryFilter categories={props.categories} active={props.category} base={base} />
        {props.view === 'calendar' ? (
          <PublicCalendarGrid
            apiUrl={props.api_url}
            calendars={props.calendar ? [props.calendar] : props.calendars}
            categories={props.categories}
            defaultTimezone={props.default_timezone}
            initial={initial}
            onState={onState}
          />
        ) : (
          <>
            <UpcomingList groups={props.groups} locale={props.locale} />
            <Pager props={props} base={base} />
          </>
        )}
        <SubscribeBox feedUrl={props.feed_url} />
      </main>
    </>
  );
}

export default function PublicIndex(props: PublicIndexProps) {
  return (
    <PageLocale locale={props.locale}>
      <PublicIndexPage {...props} />
    </PageLocale>
  );
}
