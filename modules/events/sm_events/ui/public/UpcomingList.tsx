import { daySpan, localSpan, monthName } from '../utils/datetime';
import { keys, useT } from '../utils/i18n';
import type { MonthGroup, PublicListItem } from './types';

/** The time of one item on the event's own clock, with its zone named when it differs from the
 *  calendar's. */
type Translate = ReturnType<typeof useT>['t'];

export function itemTime(item: PublicListItem, locale: string, t: Translate) {
  const copy = keys.events.public.item;
  if (item.all_day)
    return daySpan(item.start_date ?? item.start_local.slice(0, 10), item.end_date, locale);
  const text = localSpan(item.start_local, item.end_local, locale);
  return item.show_timezone ? t(copy.in_zone, { time: text, zone: item.timezone }) : text;
}

/** "in English", worded in the page's language, for a title that is not in it. */
function otherLanguage(lang: string, locale: string, t: Translate): string {
  const language = new Intl.DisplayNames([locale], { type: 'language' }).of(lang) ?? lang;
  return t(keys.events.public.item.in_language, { language });
}

/** What one occurrence shows: title link, markers, time, place and summary. The index wraps it
 *  in a list row; a block's card wraps it in its own. */
export function ItemBody({ item, locale }: { item: PublicListItem; locale: string }) {
  const { t } = useT();
  const copy = keys.events.public.item;
  return (
    <>
      <a
        href={item.url}
        // The language of this title and of the page it opens, when it is not the visitor's.
        lang={item.lang !== locale ? item.lang : undefined}
        hrefLang={item.lang !== locale ? item.lang : undefined}
        className={
          item.status === 'cancelled' ? 'font-medium line-through' : 'font-medium underline'
        }
      >
        <bdi>{item.title}</bdi>
      </a>
      {item.lang !== locale ? (
        <span
          className="ml-2 rounded border px-1 text-xs font-medium uppercase text-muted-foreground"
          title={otherLanguage(item.lang, locale, t)}
          role="img"
          aria-label={otherLanguage(item.lang, locale, t)}
        >
          {item.lang}
        </span>
      ) : null}
      {item.status === 'cancelled' ? (
        <span className="ml-2 text-sm font-medium">{t(copy.cancelled)}</span>
      ) : null}
      {item.rescheduled ? (
        <span className="ml-2 text-sm font-medium">{t(copy.rescheduled)}</span>
      ) : null}
      <p className="text-sm text-muted-foreground">
        <time dateTime={item.start_local}>{itemTime(item, locale, t)}</time>
        {item.all_day ? <> · {t(copy.all_day)}</> : null}
        {item.venue_name ? <> · {item.venue_name}</> : null}
        {item.attendance_mode === 'online' ? <> · {t(copy.online)}</> : null}
        {item.attendance_mode === 'hybrid' ? <> · {t(copy.hybrid)}</> : null}
      </p>
      {item.summary ? <p className="text-sm">{item.summary}</p> : null}
    </>
  );
}

export function ItemRow({ item, locale }: { item: PublicListItem; locale: string }) {
  return (
    <li className="space-y-1 py-3">
      <ItemBody item={item} locale={locale} />
    </li>
  );
}

export function UpcomingList({ groups, locale }: { groups: MonthGroup[]; locale: string }) {
  const { t } = useT();
  if (groups.length === 0) {
    return <p className="text-muted-foreground">{t(keys.events.public.index.empty)}</p>;
  }
  return (
    <div className="space-y-6">
      {groups.map((group) => (
        <section key={group.month} aria-labelledby={`month-${group.month}`}>
          <h2 id={`month-${group.month}`} className="text-lg font-semibold capitalize">
            {monthName(group.month, locale)}
          </h2>
          <ul className="divide-y">
            {group.items.map((item) => (
              <ItemRow key={item.key} item={item} locale={locale} />
            ))}
          </ul>
        </section>
      ))}
    </div>
  );
}
