import { useDocumentLang } from '../ui/hooks/useDocumentLang';
import { CancelledBanner } from '../ui/public/CancelledBanner';
import { EventPlace } from '../ui/public/EventPlace';
import { EventWhen } from '../ui/public/EventWhen';
import { localSpan } from '../ui/public/format';
import { LanguageSwitch } from '../ui/public/LanguageSwitch';
import { PublicHead } from '../ui/public/PublicHead';
import { RichText } from '../ui/public/RichText';
import { SubEvents } from '../ui/public/SubEvents';
import type { PublicEventProps } from '../ui/public/types';
import { keys, useT } from '../ui/utils/i18n';
import { parseRule, summarise } from '../ui/utils/recurrence';

/** The rule as a sentence, from the normalised text and the first start, in the page's language. */
function ruleText(p: PublicEventProps): string {
  if (!p.series) return '';
  const rule = parseRule(p.series.rule, p.series.start_local, p.timezone);
  return rule ? summarise(rule, p.series.start_local, p.locale) : p.series.rule;
}

export default function PublicEvent(p: PublicEventProps) {
  const { t } = useT();
  const copy = keys.events.public.event;
  useDocumentLang(p.locale);
  const cancelledDate = p.when?.status === 'cancelled' && !p.cancelled;
  return (
    <>
      <PublicHead
        title={p.title}
        description={p.summary}
        canonical={p.canonical_url}
        alternates={p.alternates}
        noindex={!p.index_in_search}
        image={p.image}
        locale={p.locale}
        jsonLd={p.json_ld}
      />
      <main className="mx-auto max-w-3xl space-y-6 p-4">
        {p.cancelled || p.when?.status === 'cancelled' ? (
          <CancelledBanner occurrence={cancelledDate} />
        ) : null}
        <header className="space-y-2">
          {p.parent ? (
            <p className="text-sm">
              <a href={p.parent.url} className="underline">
                {t(copy.part_of, { title: p.parent.title })}
              </a>
            </p>
          ) : null}
          <h1 className="text-2xl font-semibold">
            <bdi>{p.title}</bdi>
          </h1>
          {p.summary ? <p className="text-lg">{p.summary}</p> : null}
          <LanguageSwitch alternates={p.alternates} locale={p.locale} />
        </header>
        {p.image ? (
          <img src={p.image} alt="" className="max-h-80 w-full rounded-md object-cover" />
        ) : null}
        <section aria-labelledby="when-title" className="space-y-2">
          <h2 id="when-title" className="font-semibold">
            {t(copy.when)}
          </h2>
          {p.when ? <EventWhen when={p.when} timezone={p.timezone} locale={p.locale} /> : null}
          {p.series ? (
            <div className="space-y-2">
              <p className="text-sm text-muted-foreground">
                {t(copy.series)}: {ruleText(p)}
              </p>
              <h3 className="text-sm font-semibold">{t(copy.next_dates)}</h3>
              <ul className="space-y-1">
                {p.series.next.map((n) => {
                  const time = localSpan(n.start_local, n.end_local, p.locale);
                  return (
                    <li key={n.url}>
                      <a href={n.url} className="underline">
                        {n.status === 'cancelled' ? t(copy.next_cancelled, { time }) : time}
                      </a>
                    </li>
                  );
                })}
              </ul>
            </div>
          ) : null}
        </section>
        <EventPlace place={p.place} />
        {p.organiser ? <p>{t(copy.organiser, { name: p.organiser })}</p> : null}
        <p className="text-sm text-muted-foreground">
          {p.category ? <>{p.category.name} · </> : null}
          <a href={p.calendar.url} className="underline">
            {p.calendar.name}
          </a>
        </p>
        <RichText nodes={p.description_tree} />
        <SubEvents items={p.sub_events} locale={p.locale} />
        <p className="flex flex-wrap gap-4">
          {p.registration_url ? (
            <a href={p.registration_url} rel="noopener nofollow" className="font-medium underline">
              {t(copy.register)}
            </a>
          ) : null}
          <a href={p.ics_url} className="underline">
            {t(copy.add_to_calendar)}
          </a>
        </p>
      </main>
    </>
  );
}
