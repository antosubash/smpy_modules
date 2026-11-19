/** An external entry's detail: plain text only (React's escaping is the only path to the page),
 *  where it comes from, and a link to the source when the feed gave a web address. No edit,
 *  move, remind or register control exists here. */
import { localTimeText, timeText } from '../../calendar/time/format';
import type { DetailProps } from '../../calendar/types';
import { keys, useT } from '../../utils/i18n';
import { Name } from '../../utils/isolate';

/** The one rule for "a link a browser may be sent to": http or https with a host. */
export function isWebUrl(value: string | null | undefined): value is string {
  if (!value) return false;
  try {
    const url = new URL(value);
    return (
      (url.protocol === 'http:' || url.protocol === 'https:') &&
      url.hostname !== '' &&
      url.username === '' &&
      url.password === ''
    );
  } catch {
    return false;
  }
}

export default function ExternalDetail({ occurrence: o, gridTimeZone }: DetailProps) {
  const { t, locale } = useT();
  const copy = keys.events.subscriptions;
  const own = localTimeText(o, gridTimeZone, locale, false);
  return (
    <div className="space-y-2 text-sm" data-testid="external-detail">
      <h3 className="font-semibold">
        <Name>{o.title}</Name>
      </h3>
      <p>{timeText(o, gridTimeZone, locale)}</p>
      {own ? <p className="text-muted-foreground">{own}</p> : null}
      <p className="text-muted-foreground">{t(copy.from_label, { label: o.origin_label ?? '' })}</p>
      {isWebUrl(o.url) ? (
        <p>
          <a href={o.url} target="_blank" rel="noopener noreferrer nofollow" className="underline">
            {t(copy.open_source_link)}
          </a>
        </p>
      ) : null}
      <p className="text-xs text-muted-foreground">{t(copy.read_only_note)}</p>
    </div>
  );
}
