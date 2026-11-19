/** "Remind me": follow an event with one or more lead times. Console only (the calendar's
 *  detail popover and the editor's header); the public pages never carry it, so they stay
 *  cacheable and show nothing about who is signed in.
 *
 *  An inline disclosure rather than a second popover: the button says what is set, and opens a
 *  small group of checkboxes under it. Focus goes to the first box on open, Escape closes only
 *  the group and returns to the button, and every state is words, never a dead control. */
import { Button } from '@simple-module-py/ui/components/ui/button';
import { Checkbox } from '@simple-module-py/ui/components/ui/checkbox';
import { Label } from '@simple-module-py/ui/components/ui/label';
import { useEffect, useId, useRef, useState } from 'react';
import { keys, useT } from '../utils/i18n';
import { leadLabel, leadsSummary } from './leadText';
import { useFollow } from './useFollow';

const REASONS: Record<string, string> = {
  disabled: keys.events.reminders.delivery.reason_disabled,
  no_public_base_url: keys.events.reminders.delivery.reason_no_public_base_url,
  no_mail_transport: keys.events.reminders.delivery.reason_no_mail_transport,
  console_mail: keys.events.reminders.delivery.reason_console_mail,
  worker_access_unavailable: keys.events.reminders.delivery.reason_worker_access_unavailable,
};

export function RemindMe({ eventId, eventZone }: { eventId: string; eventZone: string }) {
  const { t, locale } = useT();
  const copy = keys.events.reminders.control;
  const { state, saving, error, save, clearError } = useFollow(eventId);
  const [open, setOpen] = useState(false);
  const [picked, setPicked] = useState<number[]>([]);
  const panel = useId();
  const toggle = useRef<HTMLButtonElement>(null);
  const first = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (open) first.current?.focus();
  }, [open]);

  if (state.kind === 'loading' || state.kind === 'hidden') return null;
  if (state.kind === 'unavailable') {
    return (
      <p className="text-xs text-muted-foreground" data-testid="remind-unavailable">
        {t(copy.unavailable)}
        {state.reason && REASONS[state.reason] ? ` ${t(REASONS[state.reason])}` : ''}
      </p>
    );
  }
  const { follow, status } = state;
  const following = follow.leads.length > 0;
  const close = () => {
    setOpen(false);
    clearError();
    toggle.current?.focus();
  };
  const begin = () => {
    setPicked(following ? follow.leads : follow.defaults);
    setOpen((now) => !now);
  };
  const zone = Intl.DateTimeFormat().resolvedOptions().timeZone;
  const when = (iso: string) =>
    new Intl.DateTimeFormat(locale, { dateStyle: 'medium', timeStyle: 'short' }).format(
      new Date(iso),
    );

  return (
    <div className="w-full space-y-2" data-testid="remind-me">
      <Button
        ref={toggle}
        type="button"
        size="sm"
        variant={following ? 'default' : 'outline'}
        aria-expanded={open}
        aria-controls={panel}
        onClick={begin}
      >
        {following
          ? t(copy.reminding, { leads: leadsSummary(t, follow.leads) })
          : t(copy.remind_me)}
      </Button>
      {!follow.deliverable && following ? (
        <p role="status" className="text-xs text-destructive">
          {t(keys.events.errors.reminders_no_access)}
        </p>
      ) : null}
      {open ? (
        // biome-ignore lint/a11y/useSemanticElements: a fieldset would restyle the popover body
        <div
          id={panel}
          role="group"
          aria-label={t(copy.panel_title)}
          className="space-y-2 rounded-md border p-2"
          onKeyDown={(event) => {
            if (event.key !== 'Escape') return;
            event.stopPropagation();
            close();
          }}
        >
          {!follow.deliverable ? (
            <p role="status" className="text-xs text-destructive">
              {t(keys.events.errors.reminders_no_access)}
            </p>
          ) : null}
          <ul className="space-y-1">
            {status.leads.map((lead, index) => {
              const id = `${panel}-${lead}`;
              return (
                <li key={lead} className="flex items-center gap-2">
                  <Checkbox
                    ref={index === 0 ? first : undefined}
                    id={id}
                    checked={picked.includes(lead)}
                    onCheckedChange={(on) =>
                      setPicked((now) => (on ? [...now, lead] : now.filter((x) => x !== lead)))
                    }
                  />
                  <Label htmlFor={id}>{leadLabel(t, lead)}</Label>
                </li>
              );
            })}
          </ul>
          {following ? (
            <ul className="space-y-0.5 text-xs text-muted-foreground" aria-label={t(copy.already)}>
              {[...follow.leads]
                .sort((a, b) => a - b)
                .map((lead) => {
                  const due = follow.next_due[String(lead)];
                  return (
                    <li key={lead}>
                      {due
                        ? t(copy.next_due, { lead: leadLabel(t, lead), when: when(due) })
                        : t(copy.too_late, { lead: leadLabel(t, lead) })}
                    </li>
                  );
                })}
            </ul>
          ) : null}
          <p className="text-xs text-muted-foreground">
            {t(copy.time_zone, { zone, event_zone: eventZone })}
          </p>
          {error ? (
            <p role="alert" className="text-xs text-destructive">
              {error}
            </p>
          ) : null}
          <div className="flex flex-wrap gap-2">
            <Button
              type="button"
              size="sm"
              disabled={saving || picked.length === 0}
              onClick={async () => {
                if (await save([...picked].sort((a, b) => a - b))) close();
              }}
            >
              {saving ? t(copy.saving) : t(copy.save)}
            </Button>
            {following ? (
              <Button
                type="button"
                size="sm"
                variant="outline"
                disabled={saving}
                onClick={async () => {
                  if (await save([])) close();
                }}
              >
                {t(copy.stop)}
              </Button>
            ) : null}
          </div>
          {picked.length === 0 && !following ? (
            <p className="text-xs text-muted-foreground">{t(copy.none_chosen)}</p>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
