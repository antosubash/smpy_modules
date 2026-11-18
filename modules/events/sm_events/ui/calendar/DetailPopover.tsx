/** The occurrence's detail in a popover anchored to its element. Closing returns focus to
 *  that element, so a keyboard user lands where they were. The default body shows the title
 *  (with a language badge when the text fell back), the time in the grid's zone and, when it
 *  differs, the event's own, the calendar, the status and the actions. */
import { Popover, PopoverAnchor, PopoverContent } from '@simple-module-py/ui/components/ui/popover';
import { type ComponentType, type ReactNode, useRef } from 'react';
import { keys, useT } from '../utils/i18n';
import { Name } from '../utils/isolate';
import { statusWord } from './EventChip';
import { localTimeText, timeText } from './time/format';
import type { CalendarInfo, DetailProps, Occurrence } from './types';

export type Selected = { occurrence: Occurrence; element: HTMLElement };

function languageName(code: string, locale: string | undefined): string {
  try {
    return new Intl.DisplayNames(locale, { type: 'language' }).of(code) ?? code;
  } catch {
    return code;
  }
}

export function DefaultDetail({ occurrence: o, gridTimeZone, actions, lockReason }: DetailProps) {
  const { t, locale } = useT();
  const copy = keys.events.calendar.detail;
  const own = localTimeText(o, gridTimeZone, locale);
  const word = statusWord(o, t) ?? (o.event_status ? t(statusKey(o.event_status)) : null);
  return (
    <div className="space-y-2 text-sm" data-testid="calendar-detail">
      <h3 className="flex items-center gap-2 font-semibold">
        <Name>{o.title}</Name>
        {o.lang && locale && o.lang !== locale.split('-')[0] ? (
          <span
            className="rounded border px-1 text-xs uppercase"
            title={t(copy.lang_fallback, { language: languageName(o.lang, locale) })}
          >
            {o.lang}
            <span className="sr-only">
              {t(copy.lang_fallback, { language: languageName(o.lang, locale) })}
            </span>
          </span>
        ) : null}
      </h3>
      <p>
        <span className="sr-only">{t(copy.grid_time, { zone: gridTimeZone })}: </span>
        {timeText(o, gridTimeZone, locale)}
      </p>
      {own ? (
        <p className="text-muted-foreground">
          {t(copy.event_time, { zone: o.timezone })}: {own}
        </p>
      ) : null}
      {word ? <p>{word}</p> : null}
      {lockReason ? <p className="text-muted-foreground">{lockReason}</p> : null}
      {actions ? <div className="flex flex-wrap gap-2 pt-1">{actions}</div> : null}
    </div>
  );
}

const statusKey = (status: string): string =>
  status === 'published'
    ? keys.events.list.status_published
    : status === 'in_review'
      ? keys.events.list.status_in_review
      : keys.events.list.status_draft;

type Props = {
  selected: Selected | null;
  calendar: CalendarInfo | undefined;
  gridTimeZone: string;
  actions: ReactNode;
  lockReason: string | null;
  Detail?: ComponentType<DetailProps>;
  onClose: () => void;
  restoreFocus: (selected: Selected) => void;
};

export function DetailPopover({
  selected,
  calendar,
  gridTimeZone,
  actions,
  lockReason,
  Detail,
  onClose,
  restoreFocus,
}: Props) {
  const { t } = useT();
  const last = useRef<Selected | null>(null);
  if (selected) last.current = selected;
  const Body = Detail ?? DefaultDetail;
  return (
    <Popover open={selected !== null} onOpenChange={(open) => !open && onClose()}>
      {selected ? <PopoverAnchor virtualRef={{ current: selected.element }} /> : null}
      <PopoverContent
        className="w-80"
        aria-label={t(keys.events.calendar.detail.title)}
        onCloseAutoFocus={(event) => {
          event.preventDefault();
          if (last.current) restoreFocus(last.current);
        }}
      >
        {selected ? (
          <>
            {calendar ? (
              <p className="mb-2 flex items-center gap-2 text-xs text-muted-foreground">
                <span
                  aria-hidden="true"
                  className="inline-block size-3 rounded-sm border"
                  style={{ backgroundColor: calendar.color }}
                />
                <Name>{calendar.name}</Name>
              </p>
            ) : null}
            <Body
              occurrence={selected.occurrence}
              gridTimeZone={gridTimeZone}
              close={onClose}
              actions={actions}
              lockReason={lockReason}
              Default={DefaultDetail}
            />
          </>
        ) : null}
      </PopoverContent>
    </Popover>
  );
}
